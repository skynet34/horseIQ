"""Accurace tracking-data integration.

Reports downloaded by hand ("Raporu indir", PDF) are read by `pdf_report` (OCR) into the
interchange JSON below; the API client stays inactive until Accurace grants access.


Status (2026-10-26): no Accurace API key, licence or archive. accurace.net/robots.txt
disallows /network/*, so race pages are not crawled. This module defines:

  * the interchange JSON HorseIQ accepts (see docs/DATA_ACCESS.md, "Accurace JSON"),
  * `parse_tracking_json` -> HorseTrackingRecord,
  * `import_tracking`     -> sectional_times / horse_tracking_points / horse_performances (REAL),
  * `AccuraceClient`      -> to be completed with the real endpoints once access is granted.

When the API arrives only `AccuraceClient._fetch_race` needs writing: it must return the same
HorseTrackingRecord objects, and everything downstream (form engine, simulator) already uses them.
"""
from __future__ import annotations

import difflib
from datetime import date
from typing import Any

from sqlalchemy import Engine, and_, insert, select, update

from ...db import schema as s
from ...domain import HorseTrackingRecord, SectionalRecord, TrackingPoint, fold
from ..importer import ID_NAMESPACE, ImportReport, track_code

SOURCE = "ACCURACE"


class AccuraceAccessError(RuntimeError):
    pass


class AccuraceClient:
    def __init__(self, api_key: str | None, base_url: str | None):
        if not api_key or not base_url:
            raise AccuraceAccessError(
                "ACCURACE_API_KEY / ACCURACE_API_BASE_URL tanımlı değil. Accurace erişimi lisans gerektirir."
            )
        self.api_key, self.base_url = api_key, base_url

    def race(self, day: date, track: str, race_no: int) -> list[HorseTrackingRecord]:  # pragma: no cover
        raise NotImplementedError("Accurace API dokümantasyonu geldiğinde uç noktalar burada tanımlanacak.")


def parse_tracking_json(obj: dict[str, Any]) -> list[HorseTrackingRecord]:
    """HorseIQ Accurace interchange format:
    {"date": "2026-10-18", "track": "ISTANBUL", "race_no": 1,
     "horses": [{"accurace_id": "..", "name": "..", "program_no": 3,
                 "total_distance_m": 1412.5, "avg_speed_mps": 16.1, "max_speed_mps": 18.0,
                 "sectionals": [{"from_m": 0, "to_m": 200, "time_s": 12.9, "position": 2}, ...],
                 "points": [{"t_ms": 0, "distance_m": 0, "lat": .., "lon": .., "speed_mps": 0,
                             "rail_distance_m": 1.2, "position": 4}, ...]}]}
    """
    day = date.fromisoformat(obj["date"])
    out = []
    for h in obj["horses"]:
        out.append(
            HorseTrackingRecord(
                race_date=day,
                racetrack=obj["track"],
                race_no=int(obj["race_no"]),
                source_system=SOURCE,
                source_horse_id=h.get("accurace_id"),
                horse_name=h["name"],
                program_no=h.get("program_no"),
                total_distance_m=h.get("total_distance_m"),
                avg_speed_mps=h.get("avg_speed_mps"),
                max_speed_mps=h.get("max_speed_mps"),
                sectionals=[SectionalRecord(**x) for x in h.get("sectionals", [])],
                points=[TrackingPoint(**x) for x in h.get("points", [])],
                extra=h.get("extra") or {},
            )
        )
    return out


def import_tracking(engine: Engine, records: list[HorseTrackingRecord], source_ref: str = "") -> ImportReport:
    """Attach tracking data to races/horses that already exist (imported from TJK)."""
    report = ImportReport(SOURCE, source_ref)
    with engine.begin() as conn:
        for r in records:
            ref = f"{r.race_date} {r.racetrack} #{r.race_no} {r.horse_name}"
            race = conn.execute(
                select(s.races.c.id)
                .join(s.racetracks, s.racetracks.c.id == s.races.c.racetrack_id)
                .where(and_(s.racetracks.c.code == track_code(r.racetrack), s.races.c.race_date == r.race_date, s.races.c.race_no == r.race_no))
            ).first()
            if race is None:
                report.error("Koşu veritabanında yok; önce TJK programı/sonucu içe aktarılmalı", ref)
                continue
            horse_id = None
            if r.source_horse_id:
                row = conn.execute(
                    select(s.horse_source_ids.c.horse_id).where(
                        s.horse_source_ids.c.source_system == ID_NAMESPACE.get(SOURCE, SOURCE),
                        s.horse_source_ids.c.source_horse_id == r.source_horse_id,
                    )
                ).first()
                horse_id = row.horse_id if row else None
            if horse_id is None:
                # name within this race (TJK CSV has no program numbers): exact fold, then close match
                entries = conn.execute(
                    select(s.race_entries.c.id, s.race_entries.c.horse_id, s.race_entries.c.program_no, s.horses.c.name)
                    .join(s.horses, s.horses.c.id == s.race_entries.c.horse_id)
                    .where(s.race_entries.c.race_id == race.id)
                ).all()
                by_key = {fold(e.name): e for e in entries}
                hit = by_key.get(fold(r.horse_name))
                if hit is None:
                    close = difflib.get_close_matches(fold(r.horse_name), list(by_key), n=1, cutoff=0.85)
                    hit = by_key[close[0]] if close else None
                    if hit is not None:
                        report.warn(f"'{r.horse_name}' benzer isimle '{hit.name}' ile eşleştirildi", ref)
                if hit is not None:
                    if r.program_no is not None and hit.program_no is not None and hit.program_no != r.program_no:
                        report.error(f"Program no uyuşmuyor: TJK {hit.program_no}, Accurace {r.program_no}", ref)
                        continue
                    horse_id = hit.horse_id
                    if r.program_no is not None and hit.program_no is None:
                        conn.execute(update(s.race_entries).where(s.race_entries.c.id == hit.id).values(program_no=r.program_no))
            if horse_id is None and r.program_no is not None:
                row = conn.execute(
                    select(s.race_entries.c.horse_id).where(s.race_entries.c.race_id == race.id, s.race_entries.c.program_no == r.program_no)
                ).first()
                if row:
                    horse_id = row.horse_id
                    if r.source_horse_id:
                        conn.execute(
                            insert(s.horse_source_ids).values(
                                horse_id=horse_id, source_system=SOURCE, source_horse_id=r.source_horse_id, match_method="PROGRAM_NO"
                            )
                        )
            if horse_id is None:
                report.error("At eşleştirilemedi (Accurace id / program no)", ref)
                continue
            audit = {"source_system": SOURCE, "data_status": "REAL"}
            exists = conn.execute(
                select(s.horse_performances.c.id).where(
                    s.horse_performances.c.race_id == race.id, s.horse_performances.c.horse_id == horse_id, s.horse_performances.c.source_system == SOURCE
                )
            ).first()
            if exists:
                report.warn("Takip verisi zaten var, atlandı", ref)
                continue
            early, late = _early_late(r.sectionals)
            conn.execute(
                insert(s.horse_performances).values(
                    race_id=race.id, horse_id=horse_id, avg_speed_mps=r.avg_speed_mps, max_speed_mps=r.max_speed_mps,
                    total_distance_m=r.total_distance_m, early_speed_mps=early, late_speed_mps=late,
                    extra=r.extra or None, **audit,
                )
            )
            for sec in r.sectionals:
                conn.execute(insert(s.sectional_times).values(race_id=race.id, horse_id=horse_id, **sec.__dict__, **audit))
            if r.points:
                conn.execute(
                    insert(s.horse_tracking_points),
                    [{"race_id": race.id, "horse_id": horse_id, "source_system": SOURCE, **p.__dict__} for p in r.points],
                )
            report.results_upserted += 1
    return report


def _early_late(secs: list[SectionalRecord]) -> tuple[float | None, float | None]:
    if not secs:
        return None, None
    secs = sorted(secs, key=lambda x: x.from_m)
    end = secs[-1].to_m

    def speed(sel):
        d = sum(x.to_m - x.from_m for x in sel)
        t = sum(x.time_s for x in sel)
        return d / t if t else None

    return speed([x for x in secs if x.to_m <= 400]), speed([x for x in secs if x.from_m >= end - 400])
