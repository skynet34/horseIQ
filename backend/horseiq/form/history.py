"""Loading past runs and selecting the ones a form calculation may use.

Leakage rule: only races strictly before the target race date are ever visible
(`load_runs(before=...)` and `select_history` both enforce it).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import Engine, select

from ..db import schema as s

LENGTH_M = 2.4  # approximate length of a horse ("boy"), metres


@dataclass(frozen=True)
class Run:
    race_id: int
    race_date: date
    track: str  # racetrack code
    surface: str | None
    distance_m: int
    going: str | None
    race_class: str | None
    field_size: int  # 0 = unknown (race only partly imported)
    horse_id: int
    pos: int | None
    time_s: float | None
    time_status: str  # REAL (official time) / ESTIMATED (from winner time + margins)
    winner_time_s: float | None
    weight_kg: float | None
    early_speed: float | None = None  # measured (Accurace) if present
    late_speed: float | None = None
    extra_distance_m: float | None = None
    data_status: str = "REAL"

    @property
    def speed(self) -> float | None:
        return self.distance_m / self.time_s if self.time_s else None


class FormSettings(BaseModel):
    """Mode A ('days') and Mode B ('races') are independent: only the selected one applies."""

    mode: Literal["days", "races"] = "days"
    days: int = Field(400, ge=30, le=1095)
    races: int = Field(3, ge=1, le=30)
    track_scope: Literal["same", "any"] = "same"
    surface_scope: Literal["same", "any"] = "same"
    distance_tolerance_m: int | None = Field(200, ge=0, le=2000)  # None = any distance


@dataclass(frozen=True)
class TargetRace:
    race_date: date
    track: str
    surface: str | None
    distance_m: int


def select_history(runs: list[Run], target: TargetRace, settings: FormSettings) -> list[Run]:
    """1) leakage cut  2) track/surface/distance filters  3) newest first  4) mode A *or* mode B."""
    ok = [r for r in runs if r.race_date < target.race_date and r.pos is not None]
    if settings.track_scope == "same":
        ok = [r for r in ok if r.track == target.track]
    if settings.surface_scope == "same" and target.surface:
        ok = [r for r in ok if r.surface == target.surface]
    if settings.distance_tolerance_m is not None:
        ok = [r for r in ok if abs(r.distance_m - target.distance_m) <= settings.distance_tolerance_m]
    ok.sort(key=lambda r: (r.race_date, r.race_id), reverse=True)
    if settings.mode == "days":
        since = target.race_date - timedelta(days=settings.days)
        return [r for r in ok if r.race_date >= since]
    return ok[: settings.races]


MARGIN_WORDS = {"BURUN": 0.05, "KISA BAS": 0.1, "BAS": 0.2, "BOYUN": 0.3, "UZAK": 15.0}


def margin_to_lengths(text: str | None) -> float | None:
    """TJK 'Fark' text -> lengths. '1 1/2' -> 1.5, 'Boyun' -> 0.3. None if unreadable."""
    if not text:
        return None
    from ..domain import fold

    t = re.sub(r"\bBOY\b", "", fold(text)).strip()
    if t in MARGIN_WORDS:
        return MARGIN_WORDS[t]
    total = 0.0
    found = False
    for part in t.split():
        if re.fullmatch(r"\d+", part):
            total += int(part)
            found = True
        elif re.fullmatch(r"\d+/\d+", part):
            a, b = part.split("/")
            total += int(a) / int(b)
            found = True
    return total if found else None


def load_runs(engine: Engine, before: date | None = None, world: Literal["REAL", "DEMO"] = "REAL") -> dict[int, list[Run]]:
    """All finished runs (optionally only before a date), grouped by horse. REAL and DEMO never mix."""
    r, res, t, e = s.races, s.race_results, s.racetracks, s.race_entries
    status_ok = (r.c.data_status == "DEMO") if world == "DEMO" else (r.c.data_status != "DEMO")
    q = (
        select(
            r.c.id, r.c.race_date, t.c.code, r.c.surface, r.c.distance_m, r.c.going, r.c.race_class, r.c.data_status,
            res.c.horse_id, res.c.finish_pos, res.c.finish_time_s, res.c.margin_text, res.c.status, e.c.weight_kg,
        )
        .join(t, t.c.id == r.c.racetrack_id)
        .join(res, res.c.race_id == r.c.id)
        .outerjoin(e, (e.c.race_id == r.c.id) & (e.c.horse_id == res.c.horse_id))
        .where(status_ok, r.c.has_results.is_(True), r.c.distance_m.is_not(None))
    )
    if before is not None:
        q = q.where(r.c.race_date < before)
    perf = {}
    with engine.connect() as conn:
        rows = conn.execute(q).all()
        for p in conn.execute(
            select(
                s.horse_performances.c.race_id, s.horse_performances.c.horse_id, s.horse_performances.c.early_speed_mps,
                s.horse_performances.c.late_speed_mps, s.horse_performances.c.total_distance_m,
            ).where(s.horse_performances.c.data_status == "REAL")
        ):
            perf[(p.race_id, p.horse_id)] = p

    by_race: dict[int, list] = {}
    for row in rows:
        by_race.setdefault(row.id, []).append(row)
    out: dict[int, list[Run]] = {}
    for race_id, rws in by_race.items():
        finishers = sorted([x for x in rws if x.finish_pos], key=lambda x: x.finish_pos)
        # races known only partly (e.g. from single horses' history pages): the field size is unknown
        # unless the finishing positions we hold are exactly 1..n -> 0 = unknown (opposition skipped)
        complete = [x.finish_pos for x in finishers] == list(range(1, len(finishers) + 1))
        field_size = sum(1 for x in rws if x.status != "SCRATCHED") if complete else 0
        winner_time = next((x.finish_time_s for x in finishers if x.finish_pos == 1 and x.finish_time_s), None)
        # derive missing times from cumulative margins when only the winner's time is known
        est: dict[int, float] = {}
        if winner_time:
            cum = 0.0
            for x in finishers[1:]:
                gap = margin_to_lengths(x.margin_text)
                if gap is None:
                    break
                cum += gap
                est[x.horse_id] = winner_time + cum * LENGTH_M / (x.distance_m / winner_time)
        for x in rws:
            pm = perf.get((race_id, x.horse_id))
            time_s, ts = x.finish_time_s, "REAL"
            if time_s is None and x.horse_id in est:
                time_s, ts = est[x.horse_id], "ESTIMATED"
            run = Run(
                race_id=race_id, race_date=x.race_date, track=x.code, surface=x.surface, distance_m=x.distance_m,
                going=x.going, race_class=x.race_class, field_size=field_size, horse_id=x.horse_id,
                pos=x.finish_pos, time_s=time_s, time_status=ts, winner_time_s=winner_time, weight_kg=x.weight_kg,
                early_speed=pm.early_speed_mps if pm else None, late_speed=pm.late_speed_mps if pm else None,
                extra_distance_m=(pm.total_distance_m - x.distance_m) if pm and pm.total_distance_m else None,
                data_status=x.data_status,
            )
            out.setdefault(x.horse_id, []).append(run)
    return out
