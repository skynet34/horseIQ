"""Repeated simulation with different seeds -> win / top-3 frequencies.

Frequencies are model outputs, not calibrated probabilities: they must be checked against real
results (see backtest) before being presented as odds of anything.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from .engine import Geometry, Intervention, Runner, simulate


def _one(args) -> list[int]:
    runners, distance, seed, intervention, geometry = args
    res = simulate(runners, distance, seed, intervention, geometry, record_frames=False)
    return [o["horse_id"] for o in res.order]


def monte_carlo(
    runners: list[Runner], distance_m: int, n: int = 200, base_seed: int = 1, intervention: Intervention | None = None,
    geometry: Geometry = Geometry(), workers: int = 0,
) -> dict:
    jobs = [(runners, distance_m, base_seed + i, intervention, geometry) for i in range(n)]
    if workers and workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            orders = list(ex.map(_one, jobs, chunksize=max(1, n // (workers * 4))))
    else:
        orders = [_one(j) for j in jobs]
    wins, top3, pos_sum = Counter(), Counter(), Counter()
    for order in orders:
        wins[order[0]] += 1
        for hid in order[:3]:
            top3[hid] += 1
        for i, hid in enumerate(order, start=1):
            pos_sum[hid] += i
    return {
        "n": n,
        "horses": {
            r.horse_id: {"win": wins[r.horse_id] / n, "top3": top3[r.horse_id] / n, "mean_pos": pos_sum[r.horse_id] / n}
            for r in runners
        },
    }
