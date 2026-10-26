"""Source-independent normalized records.

Every collector (TJK API, saved TJK pages, Accurace, demo generator) converts its input
into these dataclasses; the importer is the only code that writes them to the database.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class DataStatus(str, Enum):
    REAL = "REAL"  # directly verified race data (official result, measured sectional)
    ESTIMATED = "ESTIMATED"  # derived from real results but not measured (e.g. pace profile)
    DEMO = "DEMO"  # fully synthetic


class Surface(str, Enum):
    TURF = "TURF"  # Çim
    DIRT = "DIRT"  # Kum
    SYNTHETIC = "SYNTHETIC"  # Sentetik


SURFACE_TR = {Surface.TURF: "Çim", Surface.DIRT: "Kum", Surface.SYNTHETIC: "Sentetik"}


def parse_surface(text: str | None) -> Surface | None:
    if not text:
        return None
    t = fold(text)
    if "CIM" in t or "TURF" in t or "GRASS" in t:
        return Surface.TURF
    if "SENTETIK" in t or "SYNTH" in t or "TAPETA" in t:
        return Surface.SYNTHETIC
    if "KUM" in t or "DIRT" in t or "SAND" in t:
        return Surface.DIRT
    return None


def fold(text: str) -> str:
    """Upper-case ASCII fold for matching Turkish names: 'Şanlıurfa' -> 'SANLIURFA'."""
    t = text.replace("ı", "i").replace("İ", "I")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().upper()


def parse_race_time(text: str | None) -> float | None:
    """TJK finishing time '1.24.36' / '1:24.36' / '84.36' -> seconds."""
    if not text:
        return None
    t = text.strip().replace(",", ".")
    m = re.fullmatch(r"(?:(\d+)[.:])?(\d{1,2})[.:](\d{1,2})", t)
    if m:
        minutes = int(m.group(1) or 0)
        return minutes * 60 + int(m.group(2)) + int(m.group(3)) / (10 ** len(m.group(3)))
    try:
        return float(t)
    except ValueError:
        return None


@dataclass
class EntryRecord:
    horse_name: str
    program_no: int | None = None
    source_horse_id: str | None = None  # stable TJK horse id when the source exposes one
    gate: int | None = None  # start kulvarı
    jockey_name: str | None = None
    source_jockey_id: str | None = None
    jockey_apprentice: bool | None = None
    weight_kg: float | None = None
    age_text: str | None = None
    sex: str | None = None
    sire: str | None = None
    dam: str | None = None
    birth_year: int | None = None
    trainer: str | None = None
    scratched: bool = False  # koşmaz
    jockey_changed: bool = False
    # result fields (None for program-only records)
    finish_pos: int | None = None
    finish_time_s: float | None = None
    margin_text: str | None = None
    result_status: str | None = None  # FINISHED / DNF / DISQUALIFIED / SCRATCHED


@dataclass
class RaceRecord:
    race_date: date
    racetrack: str
    race_no: int
    source_system: str
    data_status: DataStatus
    distance_m: int | None = None
    surface: Surface | None = None
    going: str | None = None  # pist durumu
    post_time: str | None = None
    race_class: str | None = None
    conditions: str | None = None
    source_race_id: str | None = None
    has_results: bool = False
    entries: list[EntryRecord] = field(default_factory=list)


@dataclass
class SectionalRecord:
    """Measured split (e.g. Accurace) for one horse: time to cover [from_m, to_m)."""

    from_m: float
    to_m: float
    time_s: float
    speed_mps: float | None = None
    position: int | None = None


@dataclass
class TrackingPoint:
    t_ms: int
    distance_m: float | None = None
    lat: float | None = None
    lon: float | None = None
    speed_mps: float | None = None
    rail_distance_m: float | None = None
    position: int | None = None


@dataclass
class HorseTrackingRecord:
    race_date: date
    racetrack: str
    race_no: int
    source_system: str
    source_horse_id: str | None
    horse_name: str
    program_no: int | None
    total_distance_m: float | None = None
    avg_speed_mps: float | None = None
    max_speed_mps: float | None = None
    sectionals: list[SectionalRecord] = field(default_factory=list)
    points: list[TrackingPoint] = field(default_factory=list)
