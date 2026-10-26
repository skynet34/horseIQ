"""Chronological backtest: re-run past races using only information available before each race.

For every race with official results in [start, end]:
  1. form + speed model from runs strictly before the race date (FormCache / select_history),
  2. form ranking, a single simulation (seed fixed) and a small Monte Carlo,
  3. comparison with the official result.
Metrics are reported next to a random-pick baseline; nothing is tuned on the test period.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from statistics import mean

from sqlalchemy import Engine, select

from ..db import schema as s
from ..form.history import FormSettings
from ..service import FormCache, build_context
from ..sim.engine import LENGTH_M, simulate
from ..sim.montecarlo import monte_carlo


@dataclass
class RaceEval:
    race_id: int
    race_date: date
    track: str
    surface: str | None
    distance_m: int
    field_size: int
    coverage: float  # share of runners with form data
    form_winner_hit: bool
    sim_winner_hit: bool
    mc_winner_hit: bool
    sim_top3_hit: bool  # actual winner inside simulated top 3
    mc_winner_prob_of_actual: float
    spearman_form: float | None
    spearman_sim: float | None
    winner_time_err_s: float | None
    margin_err_len: float | None  # |sim - actual| beaten lengths, mean over runners


@dataclass
class BacktestReport:
    world: str
    settings: dict
    races: list[RaceEval] = field(default_factory=list)

    def summary(self) -> dict:
        if not self.races:
            return {"races": 0}
        r = self.races

        def agg(rows: list[RaceEval]) -> dict:
            ll = [math.log(max(x.mc_winner_prob_of_actual, 1e-3)) for x in rows]
            return {
                "races": len(rows),
                "random_winner_rate": round(mean(1 / x.field_size for x in rows), 3),
                "form_winner_rate": round(mean(x.form_winner_hit for x in rows), 3),
                "sim_winner_rate": round(mean(x.sim_winner_hit for x in rows), 3),
                "mc_winner_rate": round(mean(x.mc_winner_hit for x in rows), 3),
                "winner_in_sim_top3": round(mean(x.sim_top3_hit for x in rows), 3),
                "random_top3_rate": round(mean(min(1, 3 / x.field_size) for x in rows), 3),
                "mc_logloss_winner": round(-mean(ll), 3),
                "random_logloss_winner": round(mean(math.log(x.field_size) for x in rows), 3),
                "spearman_form": _m([x.spearman_form for x in rows]),
                "spearman_sim": _m([x.spearman_sim for x in rows]),
                "winner_time_mae_s": _m([abs(x.winner_time_err_s) for x in rows if x.winner_time_err_s is not None]),
                "margin_mae_len": _m([x.margin_err_len for x in rows]),
                "mean_coverage": round(mean(x.coverage for x in rows), 3),
            }

        out = {"overall": agg(r)}
        for name, key in (("by_track", lambda x: x.track), ("by_surface", lambda x: x.surface or "?"), ("by_distance", _dist_bucket), ("by_coverage", _cov_bucket)):
            groups = defaultdict(list)
            for x in r:
                groups[key(x)].append(x)
            out[name] = {k: agg(v) for k, v in sorted(groups.items())}
        return out


def _m(vals):
    vals = [v for v in vals if v is not None]
    return round(mean(vals), 3) if vals else None


def _dist_bucket(x: RaceEval) -> str:
    return "≤1300" if x.distance_m <= 1300 else "1301-1700" if x.distance_m <= 1700 else "1701-2100" if x.distance_m <= 2100 else ">2100"


def _cov_bucket(x: RaceEval) -> str:
    return "veri %0-49" if x.coverage < 0.5 else "veri %50-79" if x.coverage < 0.8 else "veri %80-100"


def spearman(a: list[int], b: list[int]) -> float | None:
    n = len(a)
    if n < 3:
        return None
    ra = {h: i for i, h in enumerate(a)}
    rb = {h: i for i, h in enumerate(b)}
    common = [h for h in a if h in rb]
    n = len(common)
    if n < 3:
        return None
    d2 = sum((ra[h] - rb[h]) ** 2 for h in common)
    return 1 - 6 * d2 / (n * (n * n - 1))


def run_backtest(
    engine: Engine, start: date, end: date, settings: FormSettings, world: str = "REAL", mc_n: int = 20, max_races: int | None = None, progress=None
) -> BacktestReport:
    r, res = s.races, s.race_results
    status_ok = (r.c.data_status == "DEMO") if world == "DEMO" else (r.c.data_status != "DEMO")
    with engine.connect() as conn:
        race_ids = [x.id for x in conn.execute(select(r.c.id).where(status_ok, r.c.has_results.is_(True), r.c.race_date >= start, r.c.race_date <= end).order_by(r.c.race_date, r.c.id))]
        actual: dict[int, list] = defaultdict(list)
        for row in conn.execute(select(res.c.race_id, res.c.horse_id, res.c.finish_pos, res.c.finish_time_s).where(res.c.race_id.in_(race_ids), res.c.finish_pos.is_not(None))):
            actual[row.race_id].append(row)
    if max_races:
        race_ids = race_ids[:max_races]
    cache = FormCache(engine)
    report = BacktestReport(world, settings.model_dump())
    for i, rid in enumerate(race_ids):
        act = sorted(actual.get(rid, []), key=lambda x: x.finish_pos)
        if len(act) < 3:
            continue
        ctx = build_context(engine, rid, settings, cache)
        runners_ids = {x.horse_id for x in ctx.runners}
        act = [a for a in act if a.horse_id in runners_ids]
        if len(act) < 3:
            continue
        act_order = [a.horse_id for a in act]
        form_order = sorted(ctx.forms, key=lambda h: -(ctx.forms[h].form_score if ctx.forms[h].form_score is not None else -1))
        sim = simulate(ctx.runners, ctx.target.distance_m, seed=rid, geometry=ctx.geometry, record_frames=False)
        sim_order = [o["horse_id"] for o in sim.order]
        mc = monte_carlo(ctx.runners, ctx.target.distance_m, n=mc_n, base_seed=rid * 1000, geometry=ctx.geometry)
        mc_probs = {h: v["win"] for h, v in mc["horses"].items()}
        mc_pick = max(mc_probs, key=mc_probs.get)
        # winner time error and per-horse beaten-length error
        wt_err = None
        if act[0].finish_time_s and sim.order[0]["time_s"]:
            wt_err = sim.order[0]["time_s"] - act[0].finish_time_s
        margin_errs = []
        sim_gap = {o["horse_id"]: o.get("gap_win_len") for o in sim.order}
        if act[0].finish_time_s:
            v = ctx.target.distance_m / act[0].finish_time_s
            for a in act:
                if a.finish_time_s and sim_gap.get(a.horse_id) is not None:
                    margin_errs.append(abs((a.finish_time_s - act[0].finish_time_s) * v / LENGTH_M - sim_gap[a.horse_id]))
        cov = sum(1 for f in ctx.forms.values() if f.data_status != "NO_DATA") / max(1, len(ctx.forms))
        # smoothed MC probability of the actual winner (add-one so log-loss stays finite)
        p_act = (mc_probs.get(act_order[0], 0) * mc_n + 1) / (mc_n + len(ctx.runners))
        report.races.append(
            RaceEval(
                rid, ctx.race["race_date"], ctx.race["track_code"], ctx.target.surface, ctx.target.distance_m, len(ctx.runners), round(cov, 3),
                form_order[0] == act_order[0], sim_order[0] == act_order[0], mc_pick == act_order[0], act_order[0] in sim_order[:3],
                round(p_act, 4), spearman(form_order, act_order), spearman(sim_order, act_order), wt_err,
                round(mean(margin_errs), 2) if margin_errs else None,
            )
        )
        if progress:
            progress(i + 1, len(race_ids))
    return report
