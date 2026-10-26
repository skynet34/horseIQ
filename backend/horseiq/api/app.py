"""HorseIQ HTTP API (FastAPI).  Run:  uvicorn horseiq.api.app:app --reload  (from backend/)"""
from __future__ import annotations

import random
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, insert, select

from ..config import get_settings
from ..db import get_engine
from ..db import schema as s
from ..form.history import FormSettings
from ..service import FormCache, build_context
from ..sim.engine import ENGINE_VERSION, Intervention, simulate
from ..sim.montecarlo import monte_carlo

app = FastAPI(title="HorseIQ API", version=ENGINE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=list(get_settings().cors_origins), allow_methods=["*"], allow_headers=["*"])
_cache: FormCache | None = None

World = Literal["REAL", "DEMO"]


def cache() -> FormCache:
    global _cache
    if _cache is None:
        _cache = FormCache(get_engine())
    return _cache


def _world_filter(world: World):
    return (s.races.c.data_status == "DEMO") if world == "DEMO" else (s.races.c.data_status != "DEMO")


@app.get("/api/health")
def health():
    return {"ok": True, "engine": ENGINE_VERSION}


@app.get("/api/meta")
def meta():
    eng = get_engine()
    cfg = get_settings()
    with eng.connect() as conn:
        counts = {st: n for st, n in conn.execute(select(s.races.c.data_status, func.count()).group_by(s.races.c.data_status))}
        horses = {st: n for st, n in conn.execute(select(s.horses.c.data_status, func.count()).group_by(s.horses.c.data_status))}
        tracking = conn.execute(select(func.count()).select_from(s.sectional_times)).scalar()
    return {
        "races": counts,
        "horses": horses,
        "sectional_rows": tracking,
        "tjk_api_configured": bool(cfg.tjk_auth_key),
        "accurace_configured": bool(cfg.accurace_api_key),
        "engine": ENGINE_VERSION,
    }


@app.get("/api/dates")
def dates(world: World = "REAL", limit: int = 120):
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(s.races.c.race_date).where(_world_filter(world)).group_by(s.races.c.race_date).order_by(s.races.c.race_date.desc()).limit(limit)
        ).all()
    return [r.race_date.isoformat() for r in rows]


@app.get("/api/meetings")
def meetings(world: World = "REAL", day: date | None = None):
    """Races of a day grouped by hippodrome. Without a date: today, else the latest day with races."""
    eng = get_engine()
    r, t = s.races, s.racetracks
    with eng.connect() as conn:
        if day is None:
            today = date.today()
            has_today = conn.execute(select(func.count()).select_from(r).where(_world_filter(world), r.c.race_date == today)).scalar()
            day = today if has_today else conn.execute(select(func.max(r.c.race_date)).where(_world_filter(world))).scalar()
        if day is None:
            return {"date": None, "meetings": []}
        n_runners = (
            select(s.race_entries.c.race_id, func.count().label("n"))
            .where(s.race_entries.c.scratched.is_(False))
            .group_by(s.race_entries.c.race_id)
            .subquery()
        )
        rows = conn.execute(
            select(r.c.id, r.c.race_no, r.c.post_time, r.c.distance_m, r.c.surface, r.c.going, r.c.race_class, r.c.has_results, r.c.data_status, t.c.code, t.c.name, n_runners.c.n)
            .join(t, t.c.id == r.c.racetrack_id)
            .outerjoin(n_runners, n_runners.c.race_id == r.c.id)
            .where(_world_filter(world), r.c.race_date == day)
            .order_by(t.c.name, r.c.race_no)
        ).all()
    out: dict[str, dict] = {}
    for x in rows:
        m = out.setdefault(x.code, {"track_code": x.code, "track_name": x.name, "races": []})
        m["races"].append(
            {"id": x.id, "race_no": x.race_no, "post_time": x.post_time, "distance_m": x.distance_m, "surface": x.surface, "going": x.going,
             "race_class": x.race_class, "has_results": x.has_results, "data_status": x.data_status, "runners": x.n or 0}
        )
    return {"date": day.isoformat(), "meetings": list(out.values())}


@app.get("/api/races/{race_id}")
def race(race_id: int):
    ctx = _ctx(race_id, FormSettings())
    return _race_payload(ctx)


class SimRequest(BaseModel):
    settings: FormSettings = Field(default_factory=FormSettings)
    seed: int | None = None
    intervention: Intervention | None = None


class MCRequest(BaseModel):
    settings: FormSettings = Field(default_factory=FormSettings)
    n: int = Field(100, ge=10, le=1000)


def _ctx(race_id: int, settings: FormSettings):
    try:
        return build_context(get_engine(), race_id, settings, cache())
    except KeyError:
        raise HTTPException(404, "Koşu bulunamadı")


def _race_payload(ctx) -> dict:
    race = ctx.race
    return {
        "id": race["id"],
        "date": race["race_date"].isoformat(),
        "track_code": race["track_code"],
        "track_name": race["track_name"],
        "race_no": race["race_no"],
        "post_time": race["post_time"],
        "distance_m": race["distance_m"],
        "surface": race["surface"],
        "going": race["going"],
        "race_class": race["race_class"],
        "has_results": race["has_results"],
        "data_status": race["data_status"],
        "source_system": race["source_system"],
        "geometry": {"home_straight_m": ctx.geometry.home_straight_m, "turn_radius_m": ctx.geometry.turn_radius_m, "assumed": race.get("home_straight_m") is None},
        "speed_model": {"fitted": ctx.model.fitted, "n_fit": ctx.model.n_fit},
        "runners": [
            {
                "horse_id": e["horse_id"], "program_no": e["program_no"], "name": e["name"], "gate": e["gate"], "jockey": e["jockey"],
                "weight_kg": e["weight_kg"], "jockey_changed": e["jockey_changed"],
                "form": _form_payload(ctx.forms[e["horse_id"]]),
            }
            for e in ctx.entries
        ],
        "scratched": [{"program_no": e["program_no"], "name": e["name"]} for e in ctx.scratched],
    }


def _form_payload(f) -> dict:
    return {
        "score": round(f.form_score, 1) if f.form_score is not None else None,
        "runs_used": f.runs_used,
        "status": f.data_status,
        "confidence": f.confidence,
        "components": {k: {"score": None if c.score is None else round(c.score, 1), "status": c.status, "note": c.note} for k, c in f.components.items()},
        "profile": {k: v for k, v in f.profile.__dict__.items()},
    }


def _actual(race_id: int) -> list[dict] | None:
    r, e, h = s.race_results, s.race_entries, s.horses
    with get_engine().connect() as conn:
        rows = conn.execute(
            select(r.c.horse_id, r.c.finish_pos, r.c.finish_time_s, r.c.margin_text, r.c.status, e.c.program_no, h.c.name)
            .join(h, h.c.id == r.c.horse_id)
            .outerjoin(e, (e.c.race_id == r.c.race_id) & (e.c.horse_id == r.c.horse_id))
            .where(r.c.race_id == race_id)
            .order_by(r.c.finish_pos.is_(None), r.c.finish_pos)
        ).all()
    return [dict(x._mapping) for x in rows] or None


def _store_run(ctx, seed: int, settings: FormSettings, intervention, kind: str, order: list[dict] | None = None, mc: dict | None = None) -> int:
    weakest = "DEMO" if ctx.world == "DEMO" else ("ESTIMATED" if any(f.data_status != "REAL" for f in ctx.forms.values()) else "REAL")
    with get_engine().begin() as conn:
        run_id = conn.execute(
            insert(s.simulation_runs).values(
                race_id=ctx.race["id"], seed=seed, engine_version=ENGINE_VERSION, form_settings=settings.model_dump(),
                intervention=intervention.__dict__ if intervention else None, kind=kind, data_status=weakest,
            )
        ).inserted_primary_key[0]
        rows = []
        for hid, f in ctx.forms.items():
            o = next((x for x in order or [] if x["horse_id"] == hid), None)
            m = (mc or {}).get("horses", {}).get(hid, {})
            rows.append({"run_id": run_id, "horse_id": hid, "sim_pos": o["pos"] if o else None, "sim_time_s": o["time_s"] if o else None,
                         "win_prob": m.get("win"), "top3_prob": m.get("top3"), "form_score": f.form_score})
        conn.execute(insert(s.simulation_results), rows)
    return run_id


@app.post("/api/races/{race_id}/simulate")
def simulate_race(race_id: int, req: SimRequest):
    ctx = _ctx(race_id, req.settings)
    if len(ctx.runners) < 2:
        raise HTTPException(422, "Koşuda en az iki at olmalı")
    seed = req.seed if req.seed is not None else random.randint(1, 2**31 - 1)
    normal = simulate(ctx.runners, ctx.target.distance_m, seed, geometry=ctx.geometry)
    out = {"race": _race_payload(ctx), "seed": seed, "normal": normal.__dict__, "actual": _actual(race_id) if ctx.race["has_results"] else None}
    out["normal_run_id"] = _store_run(ctx, seed, req.settings, None, "SINGLE", normal.order)
    if req.intervention:
        if req.intervention.horse_id not in {r.horse_id for r in ctx.runners}:
            raise HTTPException(422, "Müdahale edilen at bu koşuda yok")
        iv = simulate(ctx.runners, ctx.target.distance_m, seed, req.intervention, geometry=ctx.geometry)
        out["intervention"] = iv.__dict__
        out["intervention_run_id"] = _store_run(ctx, seed, req.settings, req.intervention, "SINGLE", iv.order)
        before = {o["horse_id"]: o["pos"] for o in normal.order}
        out["comparison"] = [
            {"horse_id": o["horse_id"], "program_no": o["program_no"], "name": o["name"], "before": before[o["horse_id"]], "after": o["pos"],
             "time_delta_s": round((o["time_s"] or 0) - (next(x["time_s"] for x in normal.order if x["horse_id"] == o["horse_id"]) or 0), 2)}
            for o in iv.order
        ]
    return out


@app.post("/api/races/{race_id}/montecarlo")
def montecarlo_race(race_id: int, req: MCRequest):
    ctx = _ctx(race_id, req.settings)
    res = monte_carlo(ctx.runners, ctx.target.distance_m, n=req.n, base_seed=race_id * 7919, geometry=ctx.geometry)
    _store_run(ctx, race_id * 7919, req.settings, None, "MONTE_CARLO", mc=res)
    return res
