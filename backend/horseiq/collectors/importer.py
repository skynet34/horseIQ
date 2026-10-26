"""Idempotent writer for normalized race records.

- Re-importing the same race updates it instead of duplicating (unique track/date/race_no).
- Horses are matched by source id first; name-only matches are flagged in the report.
- A DEMO record is never merged into a REAL race (and vice versa): that is reported as an error.
- Entries that disappear from a newer card of the same race are marked scratched (koşmaz).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import Connection, Engine, and_, insert, select, update

from ..db import schema as s
from ..domain import DataStatus, EntryRecord, RaceRecord, fold

# Source systems that share TJK's horse id namespace.
ID_NAMESPACE = {"TJK_API": "TJK", "TJK_HTML": "TJK", "TJK_JSON": "TJK"}

TRACK_NAMES = {
    "ISTANBUL": "İstanbul",
    "ANKARA": "Ankara",
    "IZMIR": "İzmir",
    "ADANA": "Adana",
    "BURSA": "Bursa",
    "KOCAELI": "Kocaeli",
    "ELAZIG": "Elazığ",
    "DIYARBAKIR": "Diyarbakır",
    "SANLIURFA": "Şanlıurfa",
    "ANTALYA": "Antalya",
}
TRACK_ALIASES = {"VELIEFENDI": "ISTANBUL", "DBAKIR": "DIYARBAKIR", "YESILOBA": "ADANA", "OSMANGAZI": "BURSA"}


def track_code(name: str) -> str:
    code = fold(name).split(" (")[0].strip()
    code = code.replace(" HIPODROMU", "").strip()
    return TRACK_ALIASES.get(code, code)


@dataclass
class ImportReport:
    source_system: str
    source_ref: str = ""
    races_inserted: int = 0
    races_updated: int = 0
    entries_upserted: int = 0
    results_upserted: int = 0
    issues: list[dict] = field(default_factory=list)

    def warn(self, msg: str, ref: str = "") -> None:
        self.issues.append({"level": "warning", "message": msg, "ref": ref})

    def error(self, msg: str, ref: str = "") -> None:
        self.issues.append({"level": "error", "message": msg, "ref": ref})

    @property
    def errors(self) -> list[dict]:
        return [i for i in self.issues if i["level"] == "error"]

    def summary(self) -> str:
        return (
            f"{self.source_system} {self.source_ref}: +{self.races_inserted} koşu, "
            f"~{self.races_updated} güncellendi, {self.entries_upserted} katılım, "
            f"{self.results_upserted} sonuç, {len(self.errors)} hata, "
            f"{len(self.issues) - len(self.errors)} uyarı"
        )


class Importer:
    def __init__(self, engine: Engine):
        self.engine = engine

    def import_races(self, records: Iterable[RaceRecord], source_system: str, source_ref: str = "") -> ImportReport:
        report = ImportReport(source_system, source_ref)
        with self.engine.begin() as conn:
            for rec in records:
                ref = f"{rec.race_date} {rec.racetrack} #{rec.race_no}"
                problems = validate_race(rec)
                for p in problems:
                    report.error(p, ref)
                if problems:
                    continue
                self._import_race(conn, rec, report, ref)
            conn.execute(
                insert(s.import_logs).values(
                    source_system=source_system,
                    source_ref=source_ref[:256],
                    races_inserted=report.races_inserted,
                    races_updated=report.races_updated,
                    entries_upserted=report.entries_upserted,
                    results_upserted=report.results_upserted,
                    issues=report.issues[:500],
                )
            )
        return report

    # -- races -----------------------------------------------------------------
    def _import_race(self, conn: Connection, rec: RaceRecord, report: ImportReport, ref: str) -> None:
        track_id = self._track(conn, rec)
        existing = conn.execute(
            select(s.races).where(
                and_(s.races.c.racetrack_id == track_id, s.races.c.race_date == rec.race_date, s.races.c.race_no == rec.race_no)
            )
        ).first()
        values = {
            "post_time": rec.post_time,
            "distance_m": rec.distance_m,
            "surface": rec.surface.value if rec.surface else None,
            "going": rec.going,
            "race_class": rec.race_class,
            "conditions": rec.conditions,
        }
        if existing is None:
            race_id = conn.execute(
                insert(s.races).values(
                    racetrack_id=track_id,
                    race_date=rec.race_date,
                    race_no=rec.race_no,
                    has_results=rec.has_results,
                    source_system=rec.source_system,
                    source_id=rec.source_race_id,
                    data_status=rec.data_status.value,
                    **values,
                )
            ).inserted_primary_key[0]
            report.races_inserted += 1
        else:
            if (existing.data_status == DataStatus.DEMO.value) != (rec.data_status == DataStatus.DEMO):
                report.error(f"{rec.data_status.value} kayıt {existing.data_status} koşu ile karıştırılamaz", ref)
                return
            race_id = existing.id
            changes = {k: v for k, v in values.items() if v is not None and v != existing._mapping[k]}
            if rec.has_results and not existing.has_results:
                changes["has_results"] = True
            if changes:
                conn.execute(update(s.races).where(s.races.c.id == race_id).values(**changes))
                report.races_updated += 1

        seen: set[int] = set()
        for entry in rec.entries:
            horse_id = self._horse(conn, rec, entry, report, ref)
            if horse_id is None:
                continue
            if horse_id in seen:
                report.error(f"Aynı at koşuda iki kez: {entry.horse_name}", ref)
                continue
            seen.add(horse_id)
            jockey_id = self._jockey(conn, rec, entry)
            self._upsert(
                conn,
                s.race_entries,
                {"race_id": race_id, "horse_id": horse_id},
                {
                    "jockey_id": jockey_id,
                    "program_no": entry.program_no,
                    "gate": entry.gate,
                    "weight_kg": entry.weight_kg,
                    "age_text": entry.age_text,
                    "scratched": entry.scratched,
                    "jockey_changed": entry.jockey_changed,
                    "source_system": rec.source_system,
                    "source_id": entry.source_horse_id,
                    "data_status": rec.data_status.value,
                },
            )
            report.entries_upserted += 1
            if entry.finish_pos is not None or entry.result_status:
                self._upsert(
                    conn,
                    s.race_results,
                    {"race_id": race_id, "horse_id": horse_id},
                    {
                        "finish_pos": entry.finish_pos,
                        "finish_time_s": entry.finish_time_s,
                        "margin_text": entry.margin_text,
                        "status": entry.result_status or ("FINISHED" if entry.finish_pos else "SCRATCHED"),
                        "source_system": rec.source_system,
                        "source_id": entry.source_horse_id,
                        "data_status": rec.data_status.value,
                    },
                )
                report.results_upserted += 1

        if existing is not None and rec.entries:
            # Entries present before but missing from this full card -> koşmaz
            stale = conn.execute(
                select(s.race_entries.c.id, s.race_entries.c.horse_id, s.horses.c.name)
                .join(s.horses, s.horses.c.id == s.race_entries.c.horse_id)
                .where(s.race_entries.c.race_id == race_id, s.race_entries.c.scratched.is_(False))
            ).all()
            for row in stale:
                if row.horse_id not in seen:
                    conn.execute(update(s.race_entries).where(s.race_entries.c.id == row.id).values(scratched=True))
                    report.warn(f"{row.name} yeni programda yok, koşmaz olarak işaretlendi", ref)

    @staticmethod
    def _upsert(conn: Connection, table, key: dict, values: dict) -> int:
        where = and_(*(table.c[k] == v for k, v in key.items()))
        row = conn.execute(select(table.c.id).where(where)).first()
        if row is None:
            return conn.execute(insert(table).values(**key, **values)).inserted_primary_key[0]
        clean = {k: v for k, v in values.items() if v is not None}
        conn.execute(update(table).where(table.c.id == row.id).values(**clean))
        return row.id

    def _track(self, conn: Connection, rec: RaceRecord) -> int:
        code = track_code(rec.racetrack)
        row = conn.execute(select(s.racetracks.c.id).where(s.racetracks.c.code == code)).first()
        if row:
            return row.id
        return conn.execute(
            insert(s.racetracks).values(
                code=code,
                name=TRACK_NAMES.get(code, rec.racetrack.strip()),
                source_system=rec.source_system,
                data_status=DataStatus.REAL.value if code in TRACK_NAMES else rec.data_status.value,
            )
        ).inserted_primary_key[0]

    def _horse(self, conn: Connection, rec: RaceRecord, e: EntryRecord, report: ImportReport, ref: str) -> int | None:
        ns = ID_NAMESPACE.get(rec.source_system, rec.source_system)
        key = fold(e.horse_name)
        if e.source_horse_id:
            row = conn.execute(
                select(s.horse_source_ids.c.horse_id).where(
                    s.horse_source_ids.c.source_system == ns, s.horse_source_ids.c.source_horse_id == e.source_horse_id
                )
            ).first()
            if row:
                return row.horse_id
        # name match restricted to the same data world (REAL vs DEMO never mix)
        q = select(s.horses).where(s.horses.c.name_key == key)
        q = q.where((s.horses.c.data_status == DataStatus.DEMO.value) if rec.data_status == DataStatus.DEMO else (s.horses.c.data_status != DataStatus.DEMO.value))
        if e.birth_year:
            q = q.where((s.horses.c.birth_year == e.birth_year) | s.horses.c.birth_year.is_(None))
        candidates = conn.execute(q).all()
        if e.source_horse_id:
            # candidates must not already own a different id in this namespace
            free = [
                c
                for c in candidates
                if not conn.execute(
                    select(s.horse_source_ids.c.id).where(s.horse_source_ids.c.horse_id == c.id, s.horse_source_ids.c.source_system == ns)
                ).first()
            ]
            candidates = free
        horse_id: int
        if len(candidates) == 1:
            horse_id = candidates[0].id
            if not e.source_horse_id and rec.data_status != DataStatus.DEMO:
                report.warn(f"'{e.horse_name}' yalnızca isimle eşleştirildi", ref)
        else:
            if len(candidates) > 1:
                report.warn(f"'{e.horse_name}' için {len(candidates)} aday var; yeni at kaydı açıldı", ref)
            horse_id = conn.execute(
                insert(s.horses).values(
                    name=e.horse_name.strip(),
                    name_key=key,
                    birth_year=e.birth_year,
                    sex=e.sex,
                    sire=e.sire,
                    dam=e.dam,
                    source_system=rec.source_system,
                    source_id=e.source_horse_id,
                    data_status=rec.data_status.value,
                )
            ).inserted_primary_key[0]
        if e.source_horse_id:
            conn.execute(
                insert(s.horse_source_ids).values(
                    horse_id=horse_id,
                    source_system=ns,
                    source_horse_id=e.source_horse_id,
                    match_method="SOURCE_ID" if len(candidates) != 1 else "NAME",
                )
            )
        return horse_id

    def _jockey(self, conn: Connection, rec: RaceRecord, e: EntryRecord) -> int | None:
        if not e.jockey_name:
            return None
        key = fold(e.jockey_name)
        q = select(s.jockeys.c.id).where(s.jockeys.c.name_key == key, s.jockeys.c.data_status == rec.data_status.value)
        row = conn.execute(q).first()
        if row:
            return row.id
        return conn.execute(
            insert(s.jockeys).values(
                name=e.jockey_name.strip(),
                name_key=key,
                apprentice=e.jockey_apprentice,
                source_system=rec.source_system,
                source_id=e.source_jockey_id,
                data_status=rec.data_status.value,
            )
        ).inserted_primary_key[0]


def validate_race(rec: RaceRecord) -> list[str]:
    problems = []
    if not rec.racetrack:
        problems.append("Hipodrom eksik")
    if not rec.race_no or rec.race_no < 1:
        problems.append("Koşu numarası eksik")
    if rec.distance_m is not None and not (600 <= rec.distance_m <= 5000):
        problems.append(f"Mesafe geçersiz: {rec.distance_m}")
    for e in rec.entries:
        if not e.horse_name or not e.horse_name.strip():
            problems.append("İsimsiz at kaydı")
        if e.finish_time_s is not None and rec.distance_m:
            v = rec.distance_m / e.finish_time_s
            if not (8.0 <= v <= 19.5):
                problems.append(f"{e.horse_name}: derece mesafe ile uyumsuz ({e.finish_time_s:.2f} sn)")
    return problems
