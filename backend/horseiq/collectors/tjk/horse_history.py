"""Reader for TJK horse pages ("At Koşu Bilgileri") saved with the HorseIQ browser button.

tools/tjk-kit/horseiq-kaydet.js runs in the user's own browser on a page the user opened and
writes the visible table as JSON (tjk-at-<AtId>-<NAME>.json). Nothing here contacts tjk.org.

    python -m horseiq.cli import-tjk-horse ../data_inbox          # every tjk-at-*.json in the folder

Each row of the history table is one past run of this horse. It becomes a *partial* RaceRecord
(only this horse is known): the importer then adds the horse to the race without touching the
other runners (no koşmaz marking) and without overwriting race fields that are already known
(e.g. from the day's TJK CSV).

Columns (from the page, 26.10.2026): Tarih, Şehir, Msf, Pist, S, Derece, Sıklet, Takı, Jokey, St,
Gny, Grup, K. No-K. Adı, Kcins, Ant., Sahip, HP, İkramiye, S20. They are found by header text,
not by position.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ...domain import DataStatus, EntryRecord, RaceRecord, fold, parse_race_time, parse_surface

SOURCE = "TJK_HORSE"
KIND = "TJK_AT_KOSU_BILGILERI"

# folded header -> field
COLUMNS = {
    "TARIH": "date",
    "SEHIR": "city",
    "MSF": "distance",
    "MESAFE": "distance",
    "PIST": "track",
    "S": "pos",
    "SIRA": "pos",
    "DERECE": "time",
    "SIKLET": "weight",
    "KILO": "weight",
    "TAKI": "equipment",
    "JOKEY": "jockey",
    "ST": "gate",
    "GNY": "odds",
    "GRUP": "group",
    "KCINS": "class",
    "ANT.": "trainer",
    "ANTRENOR": "trainer",
    "SAHIP": "owner",
    "HP": "hp",
    "IKRAMIYE": "prize",
}
SURFACE_CODES = {"K": "Kum", "C": "Çim", "S": "Sentetik"}
DATE_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")


class HorseFileError(ValueError):
    pass


def _col_map(header: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i, h in enumerate(header):
        k = fold(h)
        field = COLUMNS.get(k)
        if field is None and "NO" in k and "ADI" in k:
            field = "race"  # "K. No-K. Adı"
        if field and field not in out:
            out[field] = i
    return out


def _date(text: str | None) -> date | None:
    m = DATE_RE.search(text or "")
    return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date() if m else None


def parse_track_cell(text: str) -> tuple[str | None, str | None]:
    """'K:Normal' -> ('Kum', 'Normal'); 'Ç:Normal | 3.3' -> ('Çim', 'Normal 3.3')."""
    t = text.replace("|", " ").strip()
    m = re.match(r"^\s*([A-Za-zÇç])\s*:\s*(.*)$", t)
    if not m:
        return parse_surface(t).value if parse_surface(t) else None, None
    surf = SURFACE_CODES.get(fold(m.group(1)))
    going = re.sub(r"\s+", " ", m.group(2)).strip() or None
    return surf, going


def parse_race_cell(text: str) -> tuple[int | None, str | None]:
    """'1' -> (1, None); '2 - ROYAL ASCOT KOŞUSU' -> (2, 'ROYAL ASCOT KOŞUSU')."""
    m = re.match(r"^\s*(\d{1,2})\s*(?:-\s*(.*))?$", text.replace("|", " "))
    if not m:
        return None, text.strip() or None
    return int(m.group(1)), (m.group(2) or "").strip() or None


def parse_obj(obj: dict[str, Any]) -> tuple[list[RaceRecord], list[str]]:
    if obj.get("kind") != KIND:
        raise HorseFileError("Dosya HorseIQ TJK at kaydı değil (kind alanı yok)")
    issues: list[str] = []
    info = obj.get("info") or {}
    name = (info.get("İsim") or obj.get("name") or "").strip()
    at_id = str(obj.get("at_id") or "").strip() or None
    if not name:
        raise HorseFileError("At ismi yok")
    birth = _date(info.get("Doğ. Trh"))
    sire = (info.get("Baba") or "").strip() or None
    dam = (info.get("Anne") or "").split("/")[0].strip() or None  # "CAPOLAVORO / MOUNTAIN CAT" -> mother
    sex = None
    age = info.get("Yaş") or ""
    sm = re.match(r"\s*\d+\s*y\s+(\S+)(?:\s+(\S+))?", age)  # "3y k  e" (CSV) or "2 y kd" (horse page)
    if sm:
        code = sm.group(2) or (sm.group(1)[-1] if len(sm.group(1)) > 1 else "")
        sex = {"E": "erkek", "D": "dişi", "A": "aygır", "K": "kısrak", "G": "iğdiş"}.get(fold(code)[:1]) if code else None
    filters = [f for f in obj.get("filters") or [] if f and not fold(f).startswith("TUM") and fold(f) != "MESAFE"]
    if filters:
        issues.append(f"{name}: sayfada filtre seçiliydi ({', '.join(filters)}); geçmiş eksik olabilir")

    cols = _col_map(obj.get("header") or [])
    missing = [c for c in ("date", "city", "distance", "track", "pos", "time", "race") if c not in cols]
    if missing:
        raise HorseFileError(f"{name}: tablo sütunları tanınamadı ({', '.join(missing)}); başlık: {obj.get('header')}")

    races: list[RaceRecord] = []
    for row in obj.get("rows") or []:
        cells = row.get("cells") or []

        def get(field: str) -> str:
            i = cols.get(field)
            return cells[i].strip() if i is not None and i < len(cells) else ""

        day = _date(get("date"))
        race_no, race_name = parse_race_cell(get("race"))
        dist = re.match(r"\d{3,4}", get("distance"))
        surface_txt, going = parse_track_cell(get("track"))
        if not day or not race_no or not dist or not get("city"):
            issues.append(f"{name}: okunamayan satır atlandı: {' ; '.join(cells[:8])}")
            continue
        pos_txt = get("pos")
        time_s = parse_race_time(get("time").replace(":", "."))
        pos = int(pos_txt) if pos_txt.isdigit() else None
        if pos and time_s:
            status = "FINISHED"
        elif pos:
            status = "FINISHED"  # placed but no time shown
        elif fold(pos_txt).startswith("K") or "KOSMAZ" in fold(" ".join(cells)):
            status = "SCRATCHED"
        else:
            status = "DNF"
        wnums = re.findall(r"\d+(?:[.,]\d+)?", get("weight"))
        weight = round(sum(float(x.replace(",", ".")) for x in wnums[:2]), 2) if wnums else None
        gm = re.match(r"(\d+)", get("gate"))
        jockey = re.sub(r"\s+AP$", "", get("jockey")).strip() or None
        rec = RaceRecord(
            race_date=day,
            racetrack=get("city"),
            race_no=race_no,
            source_system=SOURCE,
            data_status=DataStatus.REAL,
            distance_m=int(dist.group(0)),
            surface=parse_surface(surface_txt) if surface_txt else None,
            going=going,
            race_class=get("class") or None,
            conditions="; ".join(x for x in [race_name, get("group")] if x) or None,
            has_results=status in ("FINISHED", "DNF"),
            partial=True,
            entries=[
                EntryRecord(
                    horse_name=name,
                    source_horse_id=at_id,
                    gate=int(gm.group(1)) if gm else None,
                    jockey_name=jockey,
                    jockey_apprentice=bool(re.search(r"\bAP$", get("jockey"))),
                    weight_kg=weight,
                    sex=sex,
                    sire=sire,
                    dam=dam,
                    birth_year=birth.year if birth else None,
                    trainer=get("trainer") or None,
                    scratched=status == "SCRATCHED",
                    finish_pos=pos,
                    finish_time_s=time_s if pos else None,
                    result_status=status,
                )
            ],
        )
        races.append(rec)
    if not races:
        issues.append(f"{name}: tabloda koşu yok")
    return races, issues


def parse_file(path: str | Path) -> tuple[list[RaceRecord], list[str]]:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_obj(obj)


def find_files(paths: list[str | Path]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            out.extend(sorted(p.glob("tjk-at-*.json")))
        else:
            out.append(p)
    return out
