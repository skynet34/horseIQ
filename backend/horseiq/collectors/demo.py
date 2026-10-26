"""Synthetic DEMO world. Every record is data_status=DEMO and every horse name starts with 'DEMO'.

Purpose: exercise the pipeline end-to-end (import -> form -> simulation -> backtest) while real
TJK access is pending. Each fictional horse has hidden ability / distance optimum / surface
preference; results are drawn from a simple generative model that is deliberately independent
of the HorseIQ simulator, so a backtest on this data only checks that the pipeline can recover
a planted signal. It says nothing about real-world accuracy.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta

from ..domain import DataStatus, EntryRecord, RaceRecord, Surface

SOURCE = "DEMO"
TRACKS = ["İstanbul", "Ankara", "İzmir"]
SYLLABLES = ["KA", "RA", "DE", "MİR", "TAŞ", "SU", "YEL", "ÇA", "LIK", "BO", "RAN", "ŞE", "NAZ", "TU", "AY", "KUŞ", "DAĞ", "FIR"]
JOCKEYS = [f"DEMO JOKEY {c}" for c in "ABCDEFGHIJKLMN"]


@dataclass
class _Horse:
    name: str
    ability: float  # m/s above par at its best distance
    opt_dist: float
    turf_pref: float  # + likes turf, - likes dirt
    birth_year: int


def _par_speed(distance: float, surface: Surface) -> float:
    base = 17.6 - 1.05 * math.log(distance / 1000.0) * 1.6
    return base - (0.35 if surface == Surface.DIRT else 0.0)


def generate(start: date, end: date, n_horses: int = 180, seed: int = 7, today_card: date | None = None) -> list[RaceRecord]:
    rng = random.Random(seed)
    names: set[str] = set()
    horses: list[_Horse] = []
    while len(horses) < n_horses:
        nm = "DEMO " + "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 3)))
        if nm in names:
            continue
        names.add(nm)
        horses.append(
            _Horse(
                nm,
                ability=rng.gauss(0, 0.35),
                opt_dist=rng.choice([1200, 1400, 1600, 1800, 2000, 2200]) + rng.uniform(-100, 100),
                turf_pref=rng.gauss(0, 0.15),
                birth_year=rng.randint(2019, 2023),
            )
        )
    home = {h.name: TRACKS[i % len(TRACKS)] for i, h in enumerate(horses)}
    races: list[RaceRecord] = []
    d = start
    while d <= end:
        if d.weekday() in (2, 4, 5, 6):  # meetings Wed/Fri/Sat/Sun
            for track in TRACKS:
                if rng.random() < 0.55:
                    races.extend(_meeting(rng, horses, home, track, d, with_results=True))
        d += timedelta(days=1)
    if today_card:
        for track in TRACKS[:2]:
            races.extend(_meeting(rng, horses, home, track, today_card, with_results=False))
    return races


def _meeting(rng, horses, home, track, d, with_results: bool) -> list[RaceRecord]:
    out = []
    pool = [h for h in horses if home[h.name] == track] + rng.sample(horses, 12)
    for no in range(1, rng.randint(6, 8) + 1):
        surface = Surface.TURF if rng.random() < 0.55 else Surface.DIRT
        distance = rng.choice([1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900, 2000, 2100, 2200, 2400])
        field = rng.sample(pool, k=min(len(pool), rng.randint(7, 12)))
        field = list({h.name: h for h in field}.values())
        rec = RaceRecord(
            race_date=d,
            racetrack=track,
            race_no=no,
            source_system=SOURCE,
            data_status=DataStatus.DEMO,
            distance_m=distance,
            surface=surface,
            going="Normal" if surface == Surface.TURF else "Normal",
            post_time=f"{13 + no // 2}:{'30' if no % 2 else '00'}",
            race_class=rng.choice(["Maiden", "Şartlı 1", "Şartlı 3", "Handikap 15", "Handikap 17", "KV-8"]),
            has_results=with_results,
        )
        gates = list(range(1, len(field) + 1))
        rng.shuffle(gates)
        times = []
        for i, h in enumerate(field):
            v = _par_speed(distance, surface) + h.ability
            v -= 0.55 * abs(math.log(distance / h.opt_dist))
            v += h.turf_pref if surface == Surface.TURF else -h.turf_pref
            v += rng.gauss(0, 0.18)  # race-day noise
            t = distance / v
            if rng.random() < 0.03:
                t += rng.uniform(0.8, 3.0)  # trouble in running
            times.append(t)
        order = sorted(range(len(field)), key=lambda i: times[i])
        for i, h in enumerate(field):
            pos = order.index(i) + 1
            rec.entries.append(
                EntryRecord(
                    horse_name=h.name,
                    program_no=i + 1,
                    gate=gates[i],
                    jockey_name=rng.choice(JOCKEYS),
                    weight_kg=rng.choice([52, 54, 55, 56, 57, 58, 60]),
                    birth_year=h.birth_year,
                    finish_pos=pos if with_results else None,
                    finish_time_s=round(times[i], 2) if with_results else None,
                    result_status="FINISHED" if with_results else None,
                )
            )
        out.append(rec)
    return out
