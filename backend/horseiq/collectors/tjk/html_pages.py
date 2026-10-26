"""Parser for TJK result / program pages saved manually from a browser.

tjk.org's robots.txt disallows automated access (including AI agents), so HorseIQ does not
crawl it. A person may open "Günlük Yarış Sonuçları" / "Günlük Yarış Programı" in their own
browser, save the page (Ctrl+S, "Web sayfası, tamamı" or "yalnızca HTML") and import it:

    python -m horseiq.cli import-tjk-html kayit.html --date 2025-06-25 --track İstanbul

Tables are recognised by their header row (At İsmi, Jokey, Derece ...), not by CSS classes,
so cosmetic markup changes do not break the parser. NOTE: column names were taken from the
public result tables as documented by TJK users; verify against a real saved page before a
large import (the importer reports every row it cannot read).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from ...domain import DataStatus, EntryRecord, RaceRecord, fold, parse_race_time, parse_surface

SOURCE = "TJK_HTML"

# folded header text -> field
HEADER_MAP = {
    "S": "pos",
    "SIRA": "pos",
    "NO": "no",
    "AT NO": "no",
    "AT ISMI": "name",
    "AT ADI": "name",
    "YAS": "age",
    "ORIJIN(BABA - ANNE)": "origin",
    "ORIJIN": "origin",
    "SIKLET": "weight",
    "KILO": "weight",
    "JOKEY": "jockey",
    "JOKEY ADI": "jockey",
    "ANTRENOR": "trainer",
    "ANTRENORU": "trainer",
    "DERECE": "time",
    "FARK": "margin",
    "ST": "gate",
    "START": "gate",
    "G. CIK": "late_start",
}

RACE_HEADER = re.compile(r"(\d{1,2})\s*\.\s*Ko[sş]u", re.IGNORECASE)
DIST_SURF = re.compile(r"(\d{3,4})\s*(?:m\s*)?(Çim|Cim|Kum|Sentetik)", re.IGNORECASE)
POST_TIME = re.compile(r"\b(\d{1,2}[:.]\d{2})\b")
HORSE_ID = re.compile(r"(?:AtId|QueryParameter_AtId)=(\d+)", re.IGNORECASE)
JOCKEY_ID = re.compile(r"(?:JokeyId|QueryParameter_JokeyId)=(\d+)", re.IGNORECASE)
TR_DATE = re.compile(r"(\d{2})[./](\d{2})[./](\d{4})")


class ParseError(ValueError):
    pass


def parse_file(path: str | Path, race_date: date | None = None, track: str | None = None) -> list[RaceRecord]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "windows-1254", "iso-8859-9"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        text = raw.decode("utf-8", errors="replace")
    return parse_html(text, race_date, track)


def parse_html(html: str, race_date: date | None = None, track: str | None = None) -> list[RaceRecord]:
    soup = BeautifulSoup(html, "html.parser")
    race_date = race_date or _guess_date(soup)
    track = track or _guess_track(soup)
    if race_date is None or not track:
        raise ParseError("Sayfadan tarih/hipodrom okunamadı; --date ve --track verin.")

    races: list[RaceRecord] = []
    for table in soup.find_all("table"):
        cols = _header(table)
        if cols is None:
            continue
        header_text = _race_header_text(table)
        m = RACE_HEADER.search(header_text)
        if not m:
            continue
        ds = DIST_SURF.search(header_text)
        pt = POST_TIME.search(header_text)
        rec = RaceRecord(
            race_date=race_date,
            racetrack=track,
            race_no=int(m.group(1)),
            source_system=SOURCE,
            data_status=DataStatus.REAL,
            distance_m=int(ds.group(1)) if ds else None,
            surface=parse_surface(ds.group(2)) if ds else None,
            post_time=pt.group(1).replace(".", ":") if pt else None,
            conditions=re.sub(r"\s+", " ", header_text)[:500],
        )
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < len(cols) * 0.6:
                continue
            entry = _row(cells, cols)
            if entry:
                rec.entries.append(entry)
        rec.has_results = any(e.finish_pos for e in rec.entries)
        if rec.entries:
            races.append(rec)
    if not races:
        raise ParseError("Sayfada koşu tablosu bulunamadı (sonuç tabloları sayfa yüklendikten sonra mı kaydedildi?)")
    return races


def _header(table: Tag) -> list[str | None] | None:
    first = table.find("tr")
    if first is None:
        return None
    cells = first.find_all(["th", "td"])
    cols = [HEADER_MAP.get(fold(c.get_text(" ", strip=True))) for c in cells]
    return cols if "name" in cols and ("jockey" in cols or "time" in cols) else None


def _race_header_text(table: Tag) -> str:
    """Text describing the race: caption, or the nearest preceding heading-like block."""
    cap = table.find("caption")
    if cap and RACE_HEADER.search(cap.get_text(" ", strip=True)):
        return cap.get_text(" ", strip=True)
    for prev in table.find_all_previous(limit=40):
        if prev.name in ("table",):
            break
        txt = prev.get_text(" ", strip=True) if isinstance(prev, Tag) else ""
        if txt and RACE_HEADER.search(txt) and len(txt) < 800:
            # distance / surface often sit in a sibling of the "N. Koşu" heading: use the enclosing block
            parent = prev.parent
            ptxt = parent.get_text(" ", strip=True) if parent is not None and parent.name not in ("body", "html", "[document]") else ""
            return ptxt if ptxt and len(ptxt) < 800 and not parent.find("table") else txt
    return ""


def _row(cells: list[Tag], cols: list[str | None]) -> EntryRecord | None:
    val: dict[str, Tag] = {}
    for c, field in zip(cells, cols):
        if field and field not in val:
            val[field] = c
    name_cell = val.get("name")
    if name_cell is None:
        return None
    name = re.sub(r"\s*\(.*?\)\s*", " ", name_cell.get_text(" ", strip=True)).strip()
    if not name:
        return None
    t = {k: v.get_text(" ", strip=True) for k, v in val.items()}
    link = name_cell.find("a", href=True)
    hid = HORSE_ID.search(link["href"]) if link else None
    jlink = val["jockey"].find("a", href=True) if "jockey" in val else None
    jid = JOCKEY_ID.search(jlink["href"]) if jlink else None
    pos_txt = t.get("pos", "")
    pos = int(pos_txt) if pos_txt.isdigit() else None
    scratched = "KOSMAZ" in fold(name_cell.get_text(" ", strip=True)) or fold(pos_txt) in ("K", "KOSMADI")
    status = None
    if pos:
        status = "FINISHED"
    elif scratched:
        status = "SCRATCHED"
    elif "time" in t and pos_txt:
        status = "DNF"
    origin = t.get("origin", "")
    sire, dam = (origin.split(" - ", 1) + [None])[:2] if " - " in origin else (None, None)
    weight = re.match(r"(\d+(?:[.,]\d+)?)", t.get("weight", ""))
    gate = t.get("gate", "")
    return EntryRecord(
        horse_name=re.sub(r"\s+", " ", name),
        program_no=int(t["no"]) if t.get("no", "").isdigit() else None,
        source_horse_id=hid.group(1) if hid else None,
        gate=int(gate) if gate.isdigit() else None,
        jockey_name=t.get("jockey") or None,
        source_jockey_id=jid.group(1) if jid else None,
        weight_kg=float(weight.group(1).replace(",", ".")) if weight else None,
        age_text=t.get("age") or None,
        sire=sire,
        dam=dam,
        trainer=t.get("trainer") or None,
        scratched=scratched,
        finish_pos=pos,
        finish_time_s=parse_race_time(t.get("time")) if pos else None,
        margin_text=t.get("margin") or None,
        result_status=status,
    )


def _guess_date(soup: BeautifulSoup) -> date | None:
    for el in soup.find_all(["input", "a"]):
        for attr in ("value", "href"):
            v = el.get(attr) or ""
            if "Tarih" in v or el.get("name", "").endswith("Tarih"):
                m = TR_DATE.search(v.replace("%2F", "/"))
                if m:
                    return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date()
    m = TR_DATE.search(soup.get_text(" ", strip=True)[:3000])
    return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date() if m else None


def _guess_track(soup: BeautifulSoup) -> str | None:
    active = soup.select_one(".gunluk-tabs .active a, .gunluk-tabs a.active, li.active a[data-sehir-id]")
    if active:
        return active.get("id") or active.get_text(" ", strip=True).split("(")[0].strip()
    return None
