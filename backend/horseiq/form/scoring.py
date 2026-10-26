"""Explainable weighted form score + the per-horse running profile fed to the simulator.

Component weights are starting assumptions (to be tuned by backtesting), not truths:
    speed 30 · finish 25 · stamina 15 · extra distance 10 · opposition/result 10 · trend 10
Components that cannot be computed from the available data are dropped and the remaining
weights renormalised; each component records whether it is REAL, ESTIMATED or missing.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date
from statistics import median, pstdev

from .history import FormSettings, Run, TargetRace, select_history
from .speed_model import SpeedModel

WEIGHTS = {"speed": 0.30, "finish": 0.25, "stamina": 0.15, "extra_distance": 0.10, "opposition": 0.10, "trend": 0.10}
KG_EFFECT_MPS = 0.02  # ASSUMED: 1 kg extra weight ≈ -0.02 m/s


def recency_weights(runs: list[Run], target_date: date, mode: str) -> list[float]:
    """Newest first. Last-3 → 50/30/20 as specified; further runs decay by 2/3 each.
    In day mode an additional 1-year half-life discounts old runs."""
    base = [0.5, 0.3, 0.2]
    w = [base[i] if i < 3 else 0.2 * (2 / 3) ** (i - 2) for i in range(len(runs))]
    if mode == "days":
        w = [wi * 0.5 ** ((target_date - r.race_date).days / 365) for wi, r in zip(w, runs)]
    total = sum(w) or 1.0
    return [wi / total for wi in w]


@dataclass
class Component:
    score: float | None  # 0..100, 50 = average
    status: str  # REAL / ESTIMATED / MISSING
    note: str = ""


@dataclass
class SimProfile:
    cruise_speed: float  # m/s the horse can sustain over today's trip (fresh, unimpeded)
    early_pref: float  # 0 = settles at the back, 1 = wants the lead
    kick: float  # 0..1 strength of final acceleration
    stamina: float  # 0..1 resistance to fatigue
    start_skill: float  # 0..1
    consistency_sd: float  # m/s race-to-race noise
    status: dict[str, str] = field(default_factory=dict)


@dataclass
class HorseForm:
    horse_id: int
    runs_used: int
    run_ids: list[int]
    components: dict[str, Component]
    form_score: float | None
    confidence: float  # 0..1
    data_status: str  # REAL / ESTIMATED / NO_DATA
    profile: SimProfile

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def compute_form(
    horse_id: int, runs: list[Run], target: TargetRace, settings: FormSettings, model: SpeedModel, weight_kg: float | None = None, field_mean_kg: float | None = None
) -> HorseForm:
    hist = select_history(runs, target, settings)
    par_today = model.expected(target.distance_m, target.surface, target.track)
    if not hist:
        return _no_data(horse_id, par_today, weight_kg, field_mean_kg)

    w = recency_weights(hist, target.race_date, settings.mode)
    figs = [model.figure(r) for r in hist]
    pairs = [(wi, f, r) for wi, f, r in zip(w, figs, hist) if f is not None]
    comps: dict[str, Component] = {}

    # 1) speed / time performance
    if pairs:
        tw = sum(p[0] for p in pairs)
        zbar = sum(wi * f for wi, f, _ in pairs) / tw
        any_est = any(r.time_status != "REAL" for _, _, r in pairs)
        comps["speed"] = Component(_clip(50 + 15 * zbar, 0, 100), "ESTIMATED" if any_est else "REAL", f"ağırlıklı hız figürü {zbar:+.2f}")
    else:
        zbar = 0.0
        comps["speed"] = Component(None, "MISSING", "derece yok")

    # 2) finishing power: only measurable with sectionals
    late = [(wi, r.late_speed / r.speed) for wi, r in zip(w, hist) if r.late_speed and r.speed]
    if late:
        tw = sum(x[0] for x in late)
        ratio = sum(wi * x for wi, x in late) / tw
        comps["finish"] = Component(_clip(50 + 400 * (ratio - 1.0), 0, 100), "REAL", f"son 400 m / ortalama hız {ratio:.3f}")
    else:
        comps["finish"] = Component(None, "MISSING", "ara derece (Accurace) yok")

    # 3) stamina: figures in runs at least as long as today vs. shorter ones
    long_runs = [(wi, f) for wi, f, r in pairs if r.distance_m >= target.distance_m]
    short_runs = [(wi, f) for wi, f, r in pairs if r.distance_m < target.distance_m]
    if long_runs:
        lf = sum(wi * f for wi, f in long_runs) / sum(wi for wi, _ in long_runs)
        comps["stamina"] = Component(_clip(50 + 15 * lf, 0, 100), "ESTIMATED", "bugünkü mesafe ve üzerindeki koşular")
    else:
        comps["stamina"] = Component(None, "MISSING", "bu mesafe veya uzununda koşu yok")

    # 4) extra ground covered: tracking only
    extra = [(wi, r.extra_distance_m) for wi, r in zip(w, hist) if r.extra_distance_m is not None]
    if extra:
        ex = sum(wi * x for wi, x in extra) / sum(wi for wi, _ in extra)
        comps["extra_distance"] = Component(_clip(70 - 2 * ex, 0, 100), "REAL", f"ortalama +{ex:.1f} m")
    else:
        comps["extra_distance"] = Component(None, "MISSING", "konum takibi yok")

    # 5) result vs. opposition: finishing percentile, nudged by race quality (winner's figure)
    res = []
    for wi, r in zip(w, hist):
        if r.pos and r.field_size > 1:
            pct = 1 - (r.pos - 1) / (r.field_size - 1)
            q = 0.0
            if r.winner_time_s:
                q = (r.distance_m / r.winner_time_s - model.expected(r.distance_m, r.surface, r.track, r.going)) / model.sd
            res.append((wi, pct + 0.1 * _clip(q, -2, 2)))
    if res:
        val = sum(wi * x for wi, x in res) / sum(wi for wi, _ in res)
        comps["opposition"] = Component(_clip(100 * val, 0, 100), "REAL", "sıralama yüzdesi + yarış kalitesi")
    else:
        comps["opposition"] = Component(None, "MISSING")

    # 6) trend: newest half vs older half of figures
    if len(pairs) >= 2:
        k = max(1, len(pairs) // 2)
        recent = sum(f for _, f, _ in pairs[:k]) / k
        older = sum(f for _, f, _ in pairs[k:]) / max(1, len(pairs) - k)
        comps["trend"] = Component(_clip(50 + 20 * (recent - older), 0, 100), "ESTIMATED", f"{recent - older:+.2f}")
    else:
        comps["trend"] = Component(None, "MISSING", "tek koşu")

    avail = {k: c for k, c in comps.items() if c.score is not None}
    tw = sum(WEIGHTS[k] for k in avail)
    score = sum(WEIGHTS[k] * c.score for k, c in avail.items()) / tw if tw else None

    profile = _profile(hist, pairs, zbar, target, model, par_today, weight_kg, field_mean_kg)
    confidence = _clip(len(pairs) / 5, 0.1, 1.0) * (1.0 if any(c.status == "REAL" for c in avail.values()) else 0.7)
    if any(r.data_status == "DEMO" for r in hist):
        status = "DEMO"
    else:
        status = "REAL" if all(r.time_status == "REAL" for r in hist) else "ESTIMATED"
    return HorseForm(horse_id, len(hist), [r.race_id for r in hist], comps, score, round(confidence, 2), status, profile)


def _profile(hist, pairs, zbar, target, model, par_today, weight_kg, field_mean_kg) -> SimProfile:
    st: dict[str, str] = {}
    cruise = par_today + zbar * model.sd
    st["cruise_speed"] = "ESTIMATED"  # from official times, normalized
    if weight_kg and field_mean_kg:
        cruise -= KG_EFFECT_MPS * (weight_kg - field_mean_kg)

    # running style: measured early speed if available, else distance-preference proxy
    early = [r.early_speed / r.speed for r in hist if r.early_speed and r.speed]
    if early:
        early_pref = _clip(0.5 + 6 * (sum(early) / len(early) - 1.0), 0, 1)
        st["early_pref"] = "REAL"
    else:
        # horses relatively better at shorter trips are treated as more speed-oriented (ASSUMED proxy)
        diffs = [(math.log(r.distance_m / target.distance_m), f) for _, f, r in pairs]
        if len(diffs) >= 2 and pstdev([d for d, _ in diffs]) > 0.01:
            mx = sum(d for d, _ in diffs) / len(diffs)
            my = sum(f for _, f in diffs) / len(diffs)
            slope = sum((d - mx) * (f - my) for d, f in diffs) / sum((d - mx) ** 2 for d, _ in diffs)
            early_pref = _clip(0.5 - 0.25 * slope, 0.15, 0.85)  # weak proxy -> damped
            st["early_pref"] = "ESTIMATED"
        else:
            early_pref = 0.5
            st["early_pref"] = "ASSUMED"

    late = [r.late_speed / r.speed for r in hist if r.late_speed and r.speed]
    if late:
        kick = _clip(0.5 + 6 * (sum(late) / len(late) - 1.0), 0, 1)
        st["kick"] = "REAL"
    else:
        kick = _clip(1 - early_pref * 0.8 + 0.1 * zbar, 0.1, 0.9)
        st["kick"] = "ESTIMATED"

    long_f = [f for _, f, r in pairs if r.distance_m >= target.distance_m]
    stamina = _clip(0.5 + 0.2 * ((sum(long_f) / len(long_f)) - zbar), 0.1, 0.9) if long_f else 0.5
    st["stamina"] = "ESTIMATED" if long_f else "ASSUMED"
    sd = pstdev([f for _, f, _ in pairs]) * model.sd if len(pairs) >= 3 else model.sd * 0.8
    st["consistency_sd"] = "ESTIMATED" if len(pairs) >= 3 else "ASSUMED"
    st["start_skill"] = "ASSUMED"
    return SimProfile(round(cruise, 3), round(early_pref, 3), round(kick, 3), round(stamina, 3), 0.5, round(_clip(sd, 0.08, 0.45), 3), st)


def _no_data(horse_id: int, par_today: float, weight_kg, field_mean_kg) -> HorseForm:
    cruise = par_today - 0.05  # placeholder; replaced by the field median in build_field_forms
    if weight_kg and field_mean_kg:
        cruise -= KG_EFFECT_MPS * (weight_kg - field_mean_kg)
    prof = SimProfile(cruise, 0.5, 0.5, 0.5, 0.5, 0.35, {k: "NO_DATA" for k in ("cruise_speed", "early_pref", "kick", "stamina", "start_skill", "consistency_sd")})
    comps = {k: Component(None, "MISSING", "filtreye uygun koşu yok") for k in WEIGHTS}
    return HorseForm(horse_id, 0, [], comps, None, 0.0, "NO_DATA", prof)


def build_field_forms(entries: list[dict], runs_by_horse: dict[int, list[Run]], target: TargetRace, settings: FormSettings, model: SpeedModel) -> dict[int, HorseForm]:
    """entries: [{'horse_id', 'weight_kg'}...] (non-scratched). No-data horses get the field median
    cruise speed minus a small penalty — clearly flagged NO_DATA, never presented as real form."""
    kgs = [e["weight_kg"] for e in entries if e.get("weight_kg")]
    mean_kg = sum(kgs) / len(kgs) if kgs else None
    forms = {
        e["horse_id"]: compute_form(e["horse_id"], runs_by_horse.get(e["horse_id"], []), target, settings, model, e.get("weight_kg"), mean_kg)
        for e in entries
    }
    known = [f.profile.cruise_speed for f in forms.values() if f.data_status != "NO_DATA"]
    if known:
        med = median(known)
        for f in forms.values():
            if f.data_status == "NO_DATA":
                f.profile.cruise_speed = round(med - 0.1, 3)
    return forms
