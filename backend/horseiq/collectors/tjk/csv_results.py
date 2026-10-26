"""Parser for TJK "CSV Sonuçlar" files (Günlük Yarış Sonuçları -> CSV Sonuçlar).

The file is downloaded by a person from their own browser (TJK offers it as a public
export on the results page); HorseIQ does not crawl tjk.org. Import:

    python -m horseiq.cli import-tjk-csv "01.10.2026-Kocaeli-GunlukYarisSonuclari-TR.csv"

File layout (UTF-8 with BOM, ';' separated, CRLF), verified on 01.10.2026 Kocaeli:

    Kocaeli;(38. Yarış Günü);01/10/2026
    1. Kosu :   11.30;Maiden/DHÖW; 3 Yaşlı Araplar; 57.00kg; 1500m; Kum;;;;Rekor Derece :1.41.10
    İkramiye;...                      (prize lines, ignored)
    At No;At İsmi;Yaş;Orijin(Baba);Orijin(Anne);Kilo;Jokey Adı;Sahip Adı;Antrenör Adı;St;AGF;H;Derece;Ganyan;Fark
    1;KADERİ GÜZEL KG DB;3y k  e;SONALP;SÜBEYHİKIZI;57;B.AKÇAY;...;7;%10.28(3);;1:46.55;7,80;Boyun
    ...
    GANYAN(4) :7,80 TL, ...           (dividends; the number in GANYAN(..) is the winner's program no)

Notes on the columns:
  * "At No" is the finishing order (scratched horses are listed last), NOT the program number.
    The CSV does not contain program numbers or TJK horse ids. The winner's program number is
    recovered from the GANYAN line; other program numbers stay empty (Accurace matching then
    falls back to horse name).
  * Equipment codes are appended to the name (KG, DB, SK, K, GKR, ...) and are stripped.
  * Kilo "57 +0.60": the second number is fazla kilo (overweight); weight_kg = 57.60.
  * St "11 - DS": gate 11, DS = dış start.
  * Yaş "3y k  e": age 3, colour k, sex e. Birth year = race year - age (TJK ages by calendar year).
  * Derece "Koşmaz" = scratched, "Derecesiz" = ran but no official time (stored as DNF).
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from pathlib import Path

from ...domain import DataStatus, EntryRecord, RaceRecord, fold, parse_race_time, parse_surface

SOURCE = "TJK_CSV"

# Equipment / status codes TJK appends to horse names (folded). Stripped from the end of a name.
EQUIPMENT_CODES = {
    "KG", "K", "DB", "SK", "SKG", "GKR", "SGKR", "OG", "BB", "YP", "KK", "TK", "GK", "SB", "BT", "AP", "DS",
}

RACE_LINE = re.compile(r"^\s*(\d{1,2})\s*\.\s*Ko[sş]u\s*:\s*(.*)$", re.IGNORECASE)
TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})\s*$")
DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
WINNER_RE = re.compile(r"^GANYAN\((\d+)\)")
SEX = {"E": "erkek", "D": "dişi", "A": "aygır", "K": "kısrak", "G": "iğdiş"}


class CsvParseError(ValueError):
    pass


def parse_file(path: str | Path) -> list[RaceRecord]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "windows-1254", "iso-8859-9"):
        try:
            return parse_text(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    raise CsvParseError("Dosya kodlaması okunamadı")  # pragma: no cover


def parse_text(text: str) -> list[RaceRecord]:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))
    if not rows or len(rows[0]) < 3:
        raise CsvParseError("İlk satır 'Hipodrom;(N. Yarış Günü);gg/aa/yyyy' biçiminde değil")
    track = rows[0][0].strip()
    m = DATE_RE.search(";".join(rows[0]))
    if not track or not m:
        raise CsvParseError("Hipodrom veya tarih okunamadı")
    race_date = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date()

    races: list[RaceRecord] = []
    cur: RaceRecord | None = None
    cols: dict[str, int] | None = None
    for row in rows[1:]:
        if not row or not any(c.strip() for c in row):
            continue
        first = row[0].strip()
        rm = RACE_LINE.match(first)
        if rm:
            cur = _race_header(int(rm.group(1)), rm.group(2), row[1:], race_date, track)
            races.append(cur)
            cols = None
            continue
        if cur is None:
            continue
        if fold(first) == "AT NO":
            cols = {fold(c.strip()): i for i, c in enumerate(row)}
            continue
        wm = WINNER_RE.match(first)
        if wm:
            winners = [e for e in cur.entries if e.finish_pos == 1]
            if len(winners) == 1:
                winners[0].program_no = int(wm.group(1))
            continue
        if cols and first.isdigit():
            cur.entries.append(_entry(row, cols, race_date))
    for r in races:
        r.has_results = any(e.finish_pos for e in r.entries)
    races = [r for r in races if r.entries]
    if not races:
        raise CsvParseError("Dosyada koşu bulunamadı")
    return races


def _race_header(no: int, head: str, rest: list[str], race_date: date, track: str) -> RaceRecord:
    parts = [p.strip() for p in rest if p.strip()]
    tm = TIME_RE.search(head)
    title = TIME_RE.sub("", head).strip()
    distance = next((int(p[:-1]) for p in parts if re.fullmatch(r"\d{3,4}m", p)), None)
    surface = next((parse_surface(p) for p in parts if parse_surface(p)), None)
    race_class = parts[0] if parts else None
    group = parts[1] if len(parts) > 1 else ""
    record = next((p.split(":", 1)[1].strip() for p in parts if fold(p).startswith("REKOR")), None)
    cond = "; ".join(x for x in [title, race_class, group, f"rekor {record}" if record else ""] if x)
    return RaceRecord(
        race_date=race_date,
        racetrack=track,
        race_no=no,
        source_system=SOURCE,
        data_status=DataStatus.REAL,
        distance_m=distance,
        surface=surface,
        post_time=f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else None,
        race_class=race_class,
        conditions=cond[:500],
    )


def clean_name(raw: str) -> tuple[str, bool]:
    """'KADERİ GÜZEL KG DB' -> ('KADERİ GÜZEL', False); 'ARKAZGÜLÜ KG K (Koşmaz)' -> ('ARKAZGÜLÜ', True)."""
    scratched = "KOSMAZ" in fold(raw)
    name = re.sub(r"\(.*?\)", " ", raw)
    toks = name.split()
    while len(toks) > 1 and fold(toks[-1]) in EQUIPMENT_CODES:
        toks.pop()
    return " ".join(toks), scratched


def _entry(row: list[str], cols: dict[str, int], race_date: date) -> EntryRecord:
    def get(*keys: str) -> str:
        for k in keys:
            i = cols.get(k)
            if i is not None and i < len(row):
                return row[i].strip()
        return ""

    order = int(get("AT NO"))
    name, scratched = clean_name(get("AT ISMI"))
    jockey = get("JOKEY ADI")
    apprentice = bool(re.search(r"\bAP$", jockey))
    jockey = re.sub(r"\s+AP$", "", jockey).strip()
    weight = None
    wnums = re.findall(r"\d+(?:[.,]\d+)?", get("KILO"))
    if wnums:
        weight = sum(float(x.replace(",", ".")) for x in wnums[:2])
    gate_txt = get("ST")
    gm = re.match(r"(\d+)", gate_txt)
    age_txt = re.sub(r"\s+", " ", get("YAS"))
    am = re.match(r"(\d+)y\s+(\S+)\s+(\S+)", age_txt)
    derece = get("DERECE")
    time_s = parse_race_time(derece.replace(":", "."))
    if scratched or fold(derece) == "KOSMAZ":
        status, pos, time_s = "SCRATCHED", None, None
        scratched = True
    elif time_s is None:
        status, pos = "DNF", None  # "Derecesiz"
    else:
        status, pos = "FINISHED", order
    return EntryRecord(
        horse_name=name,
        gate=int(gm.group(1)) if gm else None,
        jockey_name=jockey or None,
        jockey_apprentice=apprentice,
        weight_kg=round(weight, 2) if weight else None,
        age_text=age_txt or None,
        sex=SEX.get(fold(am.group(3))) if am else None,
        sire=get("ORIJIN(BABA)") or None,
        dam=get("ORIJIN(ANNE)") or None,
        birth_year=race_date.year - int(am.group(1)) if am else None,
        trainer=get("ANTRENOR ADI") or None,
        scratched=scratched,
        finish_pos=pos,
        finish_time_s=time_s,
        margin_text=get("FARK") or None,
        result_status=status,
    )
