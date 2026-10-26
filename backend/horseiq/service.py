"""Glue between the database, the form engine and the simulator (used by API, CLI and backtest)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Engine, select

from .db import schema as s
from .form.history import FormSettings, Run, TargetRace, load_runs
from .form.scoring import HorseForm, build_field_forms
from .form.speed_model import SpeedModel, fit
from .sim.engine import Geometry, Runner


@dataclass
class RaceContext:
    race: dict
    entries: list[dict]  # non-scratched runners
    scratched: list[dict]
    target: TargetRace
    forms: dict[int, HorseForm]
    model: SpeedModel
    runners: list[Runner]
    geometry: Geometry
    world: str  # REAL / DEMO


def race_row(engine: Engine, race_id: int) -> dict | None:
    r, t = s.races, s.racetracks
    with engine.connect() as conn:
        row = conn.execute(
            select(r, t.c.code.label("track_code"), t.c.name.label("track_name"), t.c.home_straight_m, t.c.turn_radius_m)
            .join(t, t.c.id == r.c.racetrack_id)
            .where(r.c.id == race_id)
        ).first()
    return dict(row._mapping) if row else None


def race_entries(engine: Engine, race_id: int) -> list[dict]:
    e, h, j = s.race_entries, s.horses, s.jockeys
    with engine.connect() as conn:
        rows = conn.execute(
            select(e.c.horse_id, e.c.program_no, e.c.gate, e.c.weight_kg, e.c.scratched, e.c.jockey_changed, h.c.name, j.c.name.label("jockey"))
            .join(h, h.c.id == e.c.horse_id)
            .outerjoin(j, j.c.id == e.c.jockey_id)
            .where(e.c.race_id == race_id)
            .order_by(e.c.program_no)
        ).all()
    return [dict(x._mapping) for x in rows]


class FormCache:
    """Runs and speed model per (world, cutoff date): avoids reloading for every race of a day."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self._runs: dict[str, dict[int, list[Run]]] = {}
        self._models: dict[tuple[str, date], SpeedModel] = {}

    def runs(self, world: str) -> dict[int, list[Run]]:
        if world not in self._runs:
            self._runs[world] = load_runs(self.engine, None, world)  # filtered by date at use time
        return self._runs[world]

    def model(self, world: str, cutoff: date) -> SpeedModel:
        key = (world, cutoff)
        if key not in self._models:
            all_runs = [r for rs in self.runs(world).values() for r in rs if r.race_date < cutoff]
            self._models[key] = fit(all_runs)
        return self._models[key]

    def invalidate(self) -> None:
        self._runs.clear()
        self._models.clear()


def build_context(engine: Engine, race_id: int, settings: FormSettings, cache: FormCache) -> RaceContext:
    race = race_row(engine, race_id)
    if race is None:
        raise KeyError(race_id)
    world = "DEMO" if race["data_status"] == "DEMO" else "REAL"
    all_entries = race_entries(engine, race_id)
    entries = [e for e in all_entries if not e["scratched"]]
    target = TargetRace(race["race_date"], race["track_code"], race["surface"], race["distance_m"] or 1400)
    model = cache.model(world, race["race_date"])
    runs = cache.runs(world)
    # leakage guard: hand the form engine only runs strictly before the race date
    past = {hid: [r for r in runs.get(hid, []) if r.race_date < race["race_date"]] for hid in (e["horse_id"] for e in entries)}
    forms = build_field_forms(entries, past, target, settings, model)
    runners = [Runner(e["horse_id"], e["program_no"] or i + 1, e["name"], e["gate"] or e["program_no"] or i + 1, forms[e["horse_id"]].profile) for i, e in enumerate(entries)]
    geometry = Geometry(
        home_straight_m=race.get("home_straight_m") or Geometry.home_straight_m,
        turn_radius_m=race.get("turn_radius_m") or Geometry.turn_radius_m,
    )
    return RaceContext(race, entries, [e for e in all_entries if e["scratched"]], target, forms, model, runners, geometry, world)
