"""HorseIQ race engine: time-stepped, interacting runners.

Physics (per runner, every dt):
  * energy E (1.0 at the start). Running at speed v drains  dE/dt = (v/vc)^3 · vc/D,
    so a horse running its cruise speed vc all the way empties E exactly at the line.
    From that, the speed it can still sustain to the finish is  v_sus = vc · sqrt(E·D/remaining).
  * a finishing reserve (kick) becomes available only in the final sprint.
  * acceleration / deceleration limits; exhaustion caps speed once E < 0.
Interaction:
  * runners occupy (distance s, lateral offset `lane` in metres from the rail);
    a runner cannot pass through one ahead in the same band - it is held to its speed
    and must find a lateral gap (moving out costs ground on turns);
  * front-runners near the lead may duel for it: faster early fractions, extra energy cost;
  * in the last 800 m a runner may respond to a rival's move by kicking early;
  * user interventions (start, blocked, late sprint, traffic) are applied to one runner and
    everything else is recomputed, so other runners react to the changed race.
Randomness comes from per-runner streams seeded by (seed, horse_id) and drawn identically each
step, so a normal run and an intervention run share the same luck except for what the
intervention changes.

Coefficients marked ASSUMED are plausible starting values, not measured. Calibrate on real data.
"""
from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

from ..form.scoring import SimProfile

ENGINE_VERSION = "0.4.0"
LENGTH_M = 2.4  # ASSUMED average horse length ("boy")
BAND_M = 0.85  # lateral distance below which two runners are in each other's path
STALL_M = 1.05  # ASSUMED starting-stall width
A_MAX = 3.6  # m/s² peak acceleration from the stalls (ASSUMED)
D_MAX = 1.6  # m/s² max easing
LAT_V = 0.7  # m/s max lateral movement

Phase = Literal["early", "final_turn", "final_straight"]
InterventionType = Literal["start", "blocked", "late", "traffic"]


@dataclass(frozen=True)
class Geometry:
    home_straight_m: float = 400.0  # ASSUMED generic; per-hippodrome values go in racetracks table
    back_straight_m: float = 600.0
    turn_radius_m: float = 110.0

    def on_turn(self, remaining: float) -> bool:
        """Course laid out backwards from the finish: straight, turn, straight, turn, ..."""
        turn_len = math.pi * self.turn_radius_m
        x = remaining
        straight = self.home_straight_m
        while True:
            if x <= straight:
                return False
            x -= straight
            if x <= turn_len:
                return True
            x -= turn_len
            straight = self.back_straight_m

    def turn_mask(self, distance: int) -> list[bool]:
        """on_turn() for every whole metre of remaining distance (cached lookup for the hot loop)."""
        return _turn_mask(self, int(distance))

    def final_turn(self, distance: float) -> tuple[float, float]:
        """(start, end) of the final turn in metres-from-start."""
        end = distance - self.home_straight_m
        return max(0.0, end - math.pi * self.turn_radius_m), end


@lru_cache(maxsize=64)
def _turn_mask(geometry: Geometry, distance: int) -> list[bool]:
    return [geometry.on_turn(m + 0.5) for m in range(distance + 1)]


@lru_cache(maxsize=4096)
def _speed_factor(distance: int, kick_bucket: int, cruise_bucket: int, geometry: Geometry) -> float:
    """Ratio between a runner's running speed and its profile average speed, found by
    simulating it alone (no noise) until the solo time matches distance / cruise."""
    cruise = cruise_bucket / 10
    prof = SimProfile(cruise, 0.5, kick_bucket / 20, 0.5, 1.0, 0.0, {})
    factor = 1.0
    for _ in range(3):
        res = simulate([Runner(0, 1, "solo", 1, prof)], distance, seed=0, geometry=geometry, dt=0.2, record_frames=False, _calibrating=factor)
        t = res.order[0]["time_s"] or distance / cruise
        factor *= t / (distance / cruise)
    return factor


@dataclass(frozen=True)
class Runner:
    horse_id: int
    program_no: int
    name: str
    gate: int
    profile: SimProfile


@dataclass(frozen=True)
class Intervention:
    horse_id: int
    type: InterventionType
    phase: Phase | None = None  # default per type

    def resolved_phase(self) -> Phase:
        if self.phase:
            return self.phase
        return {"start": "early", "blocked": "final_straight", "late": "final_straight", "traffic": "final_turn"}[self.type]


@dataclass
class _State:
    r: Runner
    rng: random.Random
    vc: float
    s: float = 0.0
    lane: float = 0.0
    v: float = 0.0
    E: float = 1.0
    reserve: float = 0.0
    kick_at: float = 400.0  # remaining distance at which the sprint starts
    kicking: bool = False
    dueling: bool = False
    settled: bool = False  # gave up the lead fight
    start_delay: float = 0.0
    finished_t: float | None = None
    blocked_until: float = -1.0
    lane_locked_until: float = -1.0
    squeeze_until: float = -1.0
    boxed_time: float = 0.0
    day_form: float = 0.0
    aggression: float = 0.5
    responded: bool = False
    held: bool = False
    ground: float = 0.0  # actual ground covered (incl. extra on turns)
    events_logged: set = field(default_factory=set)


@dataclass
class SimResult:
    seed: int
    distance_m: int
    order: list[dict]  # finishing order with times / margins
    frames: list[dict]  # sampled positions for the animation
    events: list[dict]
    dt: float


def _rng(seed: int, horse_id: int) -> random.Random:
    return random.Random(zlib.crc32(f"{seed}:{horse_id}".encode()))


def simulate(
    runners: list[Runner],
    distance_m: int,
    seed: int,
    intervention: Intervention | None = None,
    geometry: Geometry = Geometry(),
    dt: float = 0.2,
    frame_every_s: float = 0.25,
    record_frames: bool = True,
    _calibrating: float | None = None,
) -> SimResult:
    D = float(distance_m)
    turn = geometry.turn_mask(distance_m)
    states: list[_State] = []
    for r in runners:
        rng = _rng(seed, r.horse_id)
        p = r.profile
        st = _State(r=r, rng=rng, vc=0.0)
        # pre-race draws (fixed count, same for normal and intervention runs)
        st.day_form = rng.gauss(0.0, p.consistency_sd)
        st.aggression = min(1.0, max(0.0, p.early_pref + rng.gauss(0, 0.15)))
        reaction = abs(rng.gauss(0.12, 0.08))
        slow_start = rng.random() < 0.03 + 0.04 * (1 - p.start_skill) and _calibrating is None  # background event
        slow_extra = rng.uniform(0.4, 1.0)
        kick_jitter = rng.gauss(0, 40)
        st.start_delay = reaction + (slow_extra if slow_start else 0.0)
        # The profile cruise speed is an *average* speed incl. the standing start and the pace
        # shape; scale it so an unimpeded solo run reproduces distance / cruise.
        avg = p.cruise_speed + st.day_form
        factor = _calibrating if _calibrating is not None else _speed_factor(distance_m, round(p.kick * 20), round(p.cruise_speed * 10), geometry)
        st.vc = avg * factor
        st.reserve = 0.01 + 0.035 * p.kick  # ASSUMED anaerobic reserve, released in the sprint
        st.E = 1.0 - st.reserve  # total budget stays 1.0 so average speed matches the profile
        st.kick_at = 250 + 300 * p.kick + kick_jitter
        st.lane = (r.gate - 1) * STALL_M if r.gate else 0.0
        if slow_start:
            _log_once(st, [], "slow_start", 0.0)
        states.append(st)

    events: list[dict] = []
    for st in states:
        if "slow_start" in st.events_logged:
            events.append({"t": 0.0, "horse_id": st.r.horse_id, "type": "slow_start", "text": f"{st.r.program_no} numara starta geç çıktı"})

    ft0, ft1 = geometry.final_turn(D)
    phase_window = {"early": (0.0, min(350.0, D * 0.25)), "final_turn": (ft0, ft1), "final_straight": (ft1, D - 60)}

    iv_state = None
    iv_from = iv_to = 0.0
    iv_applied = False
    iv_released = False
    if intervention:
        iv_state = next((x for x in states if x.r.horse_id == intervention.horse_id), None)
        iv_from, iv_to = phase_window[intervention.resolved_phase()]
        if iv_state and intervention.type == "start":
            iv_state.start_delay += 0.9
            iv_applied = True
            events.append({"t": 0.0, "horse_id": iv_state.r.horse_id, "type": "iv_start", "text": f"{iv_state.r.program_no} numara startta kaldı (müdahale)", "intervention": True})
        if iv_state and intervention.type == "late":
            iv_state.kick_at = max(80.0, min(iv_state.kick_at, D - iv_from) - 260)
            iv_state.responded = True  # the jockey also ignores rivals' moves
            iv_applied = True
            events.append({"t": 0.0, "horse_id": iv_state.r.horse_id, "type": "iv_late", "text": f"{iv_state.r.program_no} numara sprinte geç başlayacak (müdahale)", "intervention": True})

    t = 0.0
    frames: list[dict] = []
    next_frame = 0.0
    max_t = D / 8.0
    while t < max_t:
        active = [x for x in states if x.finished_t is None]
        if not active:
            break
        order = sorted(states, key=lambda x: -x.s)
        lead_s = order[0].s

        # --- leadership contest (early part of the race) ---
        lead_pack = [x for x in active if lead_s - x.s < 1.5 * LENGTH_M and x.s < 0.6 * D and not x.settled and x.aggression > 0.55]
        duel = len(lead_pack) >= 2
        for x in active:
            was = x.dueling
            x.dueling = duel and x in lead_pack
            if x.dueling and not was and "duel" not in x.events_logged:
                _log_once(x, events, "duel", t, f"{x.r.program_no} numara liderlik mücadelesine girdi")

        # --- intervention trigger ---
        if iv_state and not iv_applied and intervention and intervention.type in ("blocked", "traffic") and iv_state.s >= iv_from and iv_state.finished_t is None:
            iv_applied = True
            if intervention.type == "blocked":
                iv_state.blocked_until = t + 3.2
                iv_state.lane_locked_until = t + 3.2
                events.append({"t": round(t, 2), "horse_id": iv_state.r.horse_id, "type": "iv_blocked", "text": f"{iv_state.r.program_no} numaranın önü kapandı (müdahale)", "intervention": True})
            else:
                iv_state.lane_locked_until = t + 5.0
                iv_state.blocked_until = t + 5.0
                events.append({"t": round(t, 2), "horse_id": iv_state.r.horse_id, "type": "iv_traffic", "text": f"{iv_state.r.program_no} numara trafiğe takıldı (müdahale)", "intervention": True})

        # --- decide target speeds ---
        targets: dict[int, float] = {}
        kickers = [y for y in active if y.kicking]
        for x in active:
            # fixed number of draws per runner per step, whatever its state: keeps streams aligned
            noise, respond_draw, settle_draw = x.rng.gauss(0, 0.01), x.rng.random(), x.rng.random()
            if t < x.start_delay:
                targets[x.r.horse_id] = 0.0
                continue
            rem = D - x.s
            p = x.r.profile
            if not x.kicking and rem <= x.kick_at:
                x.kicking = True
                x.E += x.reserve
                if rem > 200 and "move" not in x.events_logged and x.s < lead_s - 2 * LENGTH_M:
                    _log_once(x, events, "move", t, f"{x.r.program_no} numara atağa kalktı")
            # response to a rival's early move (last 800 m)
            if not x.kicking and not x.responded and rem < 800:
                for y in kickers:
                    if y is not x and 0 < y.s - x.s < 4 * LENGTH_M and abs(y.lane - x.lane) < 4:
                        x.responded = True
                        if respond_draw < 0.35 + 0.4 * x.aggression and x.E > 0.15:
                            x.kicking = True
                            x.E += x.reserve * 0.6  # early kick: part of the reserve is spent less efficiently
                            _log_once(x, events, "respond", t, f"{x.r.program_no} numara {y.r.program_no} numaranın atağına cevap verdi")
                        break
            v_sus = x.vc * math.sqrt(max(x.E, 0.0) * D / max(rem, 1.0))
            if x.kicking:
                # top speed is physiological: time lost earlier cannot be fully bought back (ASSUMED cap)
                target = min(v_sus, x.vc * (1.05 + 0.04 * p.kick))
            else:
                frac = x.s / D
                style = (p.early_pref - 0.5) * 0.05 * (1.0 if frac < 0.35 else 0.3)
                # before the sprint the jockey holds the planned pace: saved energy waits for the sprint
                target = min(v_sus, x.vc) * (1 + style)
                if x.dueling:
                    target *= 1 + 0.02 + 0.025 * x.aggression  # ASSUMED duel surge
                if x.dueling and settle_draw < 0.05 * (1 - x.aggression) * dt * 10:
                    x.settled = True  # jockey takes a pull and lets the rival go
            # a tired horse slows to a laboured gallop, it does not stop (ASSUMED floor 80 % of cruise)
            target = max(target, x.vc * 0.80)
            if x.E <= 0:
                target = min(target, x.vc * 0.86)  # exhaustion
            if t < x.blocked_until:
                target = min(target, x.v * 0.9, x.vc * 0.85)
            if t < x.squeeze_until:
                target -= 0.35
            if x is iv_state and intervention and intervention.type == "start" and t < x.start_delay + 2.0:
                target = min(target, x.vc * 0.75)
            targets[x.r.horse_id] = max(0.0, target * (1 + noise))

        # --- traffic: cannot run through the horse ahead in the same band ---
        for x in active:
            x.held = False
        running = [x for x in order if x.finished_t is None]
        for i, x in enumerate(running):
            if targets.get(x.r.horse_id, 0) == 0:
                continue
            near = running[max(0, i - 6): i + 7]  # sorted by distance: only neighbours can interact
            ahead = _blocker(x, running[max(0, i - 6):i])
            if ahead is None:
                _drift_to_rail(x, near, t, dt)
                continue
            gap = ahead.s - x.s
            tgt = targets[x.r.horse_id]
            if tgt > ahead.v and gap < 3.2 * LENGTH_M / 2:
                # try to switch out (or in) to a free lane
                moved = t >= x.lane_locked_until and _try_lateral(x, near, dt)
                if not moved:
                    targets[x.r.horse_id] = min(tgt, ahead.v + 0.05 * gap)
                    x.held = True
                    x.boxed_time += dt
                    if x.boxed_time > 1.5 and D - x.s < 700 and "boxed" not in x.events_logged:
                        _log_once(x, events, "boxed", t, f"{x.r.program_no} numara {ahead.r.program_no} numaranın arkasında sıkıştı")
            else:
                _drift_to_rail(x, near, t, dt)

        # intervention aftermath: a blocked/traffic horse that is released swings out and squeezes neighbours
        if iv_state and iv_applied and not iv_released and intervention and intervention.type in ("blocked", "traffic") and t >= iv_state.blocked_until:
            iv_released = True
            iv_state.lane += 2.0
            for y in active:
                if y is not iv_state and 0 < y.lane - iv_state.lane + 2.0 < 3.0 and abs(y.s - iv_state.s) < 2 * LENGTH_M:
                    y.squeeze_until = t + 1.2
                    y.lane += 0.8
                    _log_once(y, events, "squeezed", t, f"{y.r.program_no} numara {iv_state.r.program_no} numaranın dışa açılmasından etkilendi")

        # --- integrate ---
        for x in active:
            tgt = targets.get(x.r.horse_id, 0.0)
            if tgt > x.v:
                a = A_MAX * max(0.15, 1 - x.v / (x.vc * 1.25))
                x.v = min(tgt, x.v + a * dt)
            else:
                x.v = max(tgt, x.v - D_MAX * dt)
            ds_ground = x.v * dt
            rem = D - x.s
            on_turn = turn[min(len(turn) - 1, max(0, int(rem)))]
            ds = ds_ground * (geometry.turn_radius_m / (geometry.turn_radius_m + x.lane)) if on_turn else ds_ground
            drain = (x.v / x.vc) ** 3 * x.vc / D * dt if x.vc > 0 else 0
            if x.dueling:
                drain *= 1.08  # ASSUMED: racing head-to-head costs extra
            x.E -= drain
            if x.s + ds >= D:
                frac = (D - x.s) / ds if ds > 0 else 0
                x.finished_t = t + frac * dt
                x.ground += ds_ground * frac
                x.s = D
            else:
                x.s += ds
                x.ground += ds_ground

        # --- no overlapping: enforce minimum spacing within a band ---
        order = sorted(states, key=lambda x: -x.s)
        for i, x in enumerate(order):
            if x.finished_t is not None:
                continue
            for y in order[max(0, i - 4):i]:
                if y.finished_t is None and abs(y.lane - x.lane) < BAND_M and y.s >= x.s and y.s - x.s < LENGTH_M:
                    x.s = max(0.0, y.s - LENGTH_M)  # nose stays one length behind the runner ahead
                    x.v = min(x.v, y.v)

        t += dt
        if record_frames and t >= next_frame:
            frames.append({"t": round(t, 2), "h": [[round(x.s, 1), round(x.lane, 2), round(x.v, 2), round(max(x.E, 0), 3)] for x in states]})
            next_frame += frame_every_s

    finished = sorted(states, key=lambda x: (x.finished_t is None, x.finished_t or 0, -x.s))
    order_out = _results(finished, D)
    if record_frames:
        frames.append({"t": round(t, 2), "h": [[round(x.s, 1), round(x.lane, 2), round(x.v, 2), round(max(x.E, 0), 3)] for x in states]})
    events.sort(key=lambda e: e["t"])
    return SimResult(seed, distance_m, order_out, frames, events, dt)


def _log_once(x: _State, events: list, kind: str, t: float, text: str = "") -> None:
    if kind in x.events_logged:
        return
    x.events_logged.add(kind)
    if text:
        events.append({"t": round(t, 2), "horse_id": x.r.horse_id, "type": kind, "text": text})


def _blocker(x: _State, ahead: list[_State]) -> _State | None:
    best = None
    for y in ahead:
        if y.finished_t is not None or y.s - x.s > 2.5 * LENGTH_M:
            continue
        if abs(y.lane - x.lane) < BAND_M and y.s > x.s:
            if best is None or y.s < best.s:
                best = y
    return best


def _lane_free(x: _State, lane: float, order: list[_State]) -> bool:
    if lane < 0:
        return False
    for y in order:
        if y is x or y.finished_t is not None:
            continue
        if abs(y.lane - lane) < BAND_M and abs(y.s - x.s) < LENGTH_M * 1.1:
            return False
    return True


def _try_lateral(x: _State, order: list[_State], dt: float) -> bool:
    step = LAT_V * dt
    for direction in (+1, -1):  # prefer going outside: inside gaps are rarer
        probe = x.lane + direction * BAND_M
        if _lane_free(x, probe, order):
            x.lane = max(0.0, x.lane + direction * step * 3)
            return True
    return False


def _drift_to_rail(x: _State, order: list[_State], t: float, dt: float) -> None:
    if x.lane <= 0 or t < x.lane_locked_until:
        return
    target = max(0.0, x.lane - LAT_V * dt * 0.5)
    if _lane_free(x, target, order):
        x.lane = target


def _results(finished: list[_State], D: float) -> list[dict]:
    out = []
    win_t = finished[0].finished_t if finished and finished[0].finished_t else None
    prev_t = win_t
    for pos, x in enumerate(finished, start=1):
        ft = x.finished_t
        row = {
            "pos": pos,
            "horse_id": x.r.horse_id,
            "program_no": x.r.program_no,
            "name": x.r.name,
            "time_s": round(ft, 2) if ft else None,
            "ground_m": round(x.ground, 1),
            "energy_left": round(max(x.E, 0.0), 3),
        }
        if ft and win_t:
            v_ref = D / ft  # average-speed based conversion (approximate, see docs)
            row["gap_prev_s"] = round(ft - prev_t, 3) if pos > 1 else 0.0
            row["gap_win_s"] = round(ft - win_t, 3)
            row["gap_prev_len"] = round((ft - prev_t) * v_ref / LENGTH_M, 2) if pos > 1 else 0.0
            row["gap_win_len"] = round((ft - win_t) * v_ref / LENGTH_M, 2)
            row["gap_prev_text"] = lengths_text(row["gap_prev_len"]) if pos > 1 else "Kazanan"
            prev_t = ft
        out.append(row)
    return out


def lengths_text(lengths: float) -> str:
    """Approximate TJK-style margin wording from lengths."""
    if lengths < 0.08:
        return "Burun"
    if lengths < 0.15:
        return "Kısa baş"
    if lengths < 0.25:
        return "Baş"
    if lengths < 0.4:
        return "Boyun"
    if lengths > 15:
        return "Uzak"
    q = round(lengths * 4) / 4
    whole, frac = int(q), q - int(q)
    frac_txt = {0.25: "1/4", 0.5: "1/2", 0.75: "3/4"}.get(frac, "")
    if whole == 0:
        return f"{frac_txt} boy"
    return f"{whole} {frac_txt} boy".replace("  ", " ")
