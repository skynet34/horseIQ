"""Normalizing finishing speeds across distance, surface, track and going.

speed ≈ a_surface + b_surface · ln(distance) + track_offset[track, surface] + going_offset[surface, going]

Fitted by least squares on runs *before* the target date only, so pars carry no future information.
A run's speed figure is its residual divided by the residual SD (a z-score): 0 = par, +1 = one
SD faster than an average runner over the same conditions. 1200 m and 1600 m races therefore
become comparable without comparing raw times.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import pstdev

from .history import Run

# Generic fallback (used only when there is too little history to fit). ASSUMED values.
# ~17.1 m/s at 1200 m and ~16.1 m/s at 2400 m on turf; dirt ~0.4 m/s slower.
FALLBACK = {"TURF": (27.3, -1.44), "DIRT": (26.9, -1.44), "SYNTHETIC": (27.1, -1.44)}
MIN_FIT = 40


@dataclass
class SpeedModel:
    coef: dict[str, tuple[float, float]] = field(default_factory=dict)
    track_off: dict[tuple[str, str], float] = field(default_factory=dict)
    going_off: dict[tuple[str, str], float] = field(default_factory=dict)
    sd: float = 0.35
    n_fit: int = 0
    fitted: bool = False

    def expected(self, distance: float, surface: str | None, track: str | None = None, going: str | None = None) -> float:
        surf = surface or "TURF"
        a, b = self.coef.get(surf) or FALLBACK.get(surf, FALLBACK["TURF"])
        v = a + b * math.log(distance)
        v += self.track_off.get((track or "", surf), 0.0)
        v += self.going_off.get((surf, going or ""), 0.0)
        return v

    def figure(self, run: Run) -> float | None:
        if run.speed is None:
            return None
        return (run.speed - self.expected(run.distance_m, run.surface, run.track, run.going)) / self.sd


def fit(runs: list[Run]) -> SpeedModel:
    model = SpeedModel()
    data = [r for r in runs if r.speed and 8 < r.speed < 20]
    model.n_fit = len(data)
    if len(data) < MIN_FIT:
        return model
    by_surf: dict[str, list[Run]] = defaultdict(list)
    for r in data:
        by_surf[r.surface or "TURF"].append(r)
    for surf, rs in by_surf.items():
        if len(rs) < MIN_FIT // 2:
            continue
        xs = [math.log(r.distance_m) for r in rs]
        ys = [r.speed for r in rs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx < 1e-6:  # single distance only: keep generic slope
            b = FALLBACK.get(surf, FALLBACK["TURF"])[1]
        else:
            b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        model.coef[surf] = (my - b * mx, b)
    # shrunk mean residuals for track and going (k=30 pseudo-observations toward 0)
    for key_fn, target in ((lambda r: (r.track, r.surface or "TURF"), model.track_off), (lambda r: (r.surface or "TURF", r.going or ""), model.going_off)):
        acc: dict = defaultdict(list)
        for r in data:
            acc[key_fn(r)].append(r.speed - model.expected(r.distance_m, r.surface, r.track if target is model.going_off else None))
        for k, vals in acc.items():
            target[k] = sum(vals) / (len(vals) + 30)
    resid = [r.speed - model.expected(r.distance_m, r.surface, r.track, r.going) for r in data]
    model.sd = max(0.12, pstdev(resid))
    model.fitted = True
    return model
