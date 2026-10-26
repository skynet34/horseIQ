"""Reader for Accurace race reports downloaded with the "Raporu indir" button.

A person opens the race on accurace.net in their own browser and downloads the reports;
HorseIQ does not crawl accurace.net. Two report kinds are supported (both are a single
screenshot image inside a PDF, so they are read with OCR - Tesseract must be installed):

  * summary  (…/network/<date>/<TRACK>/<n>/summary  -> "2026-10-01-kocaeli-1-summary.pdf")
      cumulative time of every horse at 400 m, 600 m, …, finish, with its position there.
  * detail   (…/network/<date>/<TRACK>/<n>          -> "2026-10-01-kocaeli-1.pdf")
      for the selected segment (default: the last 100 m): time, distance, distance to the
      rail, average speed; and for the whole race: time, max/avg speed, ground covered
      (metres actually run), delta to the winner's ground, "Fark".

The output is HorseIQ's Accurace interchange JSON (see docs/DATA_ACCESS.md), so the OCR
result can be reviewed before it is imported with `import-accurace`.

Every number is cross-checked (monotonic splits, positions vs. times, leader times in the
header, segment time = difference of splits, average speed = distance / time, final time vs.
summary); values that fail a check are dropped and reported, never guessed.
"""
from __future__ import annotations

import csv
import difflib
import io
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ...domain import fold

OCR_SCALE = 3

# Saddle-cloth colours used on Accurace badges (RGB) -> program number. Used only when OCR
# of the badge digit fails; taken from the 01.10.2026 Kocaeli 1 report (OCR agreed on all).
BADGE_COLOURS = {
    (86, 207, 28): 1, (255, 183, 3): 2, (53, 122, 255): 3, (255, 123, 47): 4, (230, 44, 44): 5,
    (7, 114, 23): 6, (35, 77, 158): 7, (98, 214, 251): 8, (182, 207, 28): 10, (123, 33, 193): 11,
}


class OcrUnavailable(RuntimeError):
    pass


@dataclass
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    line: tuple[int, int, int]

    @property
    def cx(self) -> float:
        return self.left + self.width / 2


@dataclass
class ReportPage:
    kind: str  # SUMMARY / DETAIL
    track: str | None
    race_no: int | None
    race_date: date | None
    distance_m: int | None
    surface: str | None
    horses: list[dict] = field(default_factory=list)
    header: dict = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- image / OCR

def load_image(pdf_path: str | Path):
    from PIL import Image
    from pypdf import PdfReader

    imgs = PdfReader(str(pdf_path)).pages[0].images
    if not imgs:
        raise ValueError(f"{pdf_path}: PDF içinde görüntü yok (Accurace raporu mu?)")
    im = max((x.image for x in imgs), key=lambda i: i.width * i.height)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (245, 245, 245, 255))
        bg.alpha_composite(im)
        im = bg
    return im.convert("RGB")


def _tesseract() -> str:
    cmd = os.getenv("TESSERACT_CMD") or shutil.which("tesseract")
    if not cmd and os.name == "nt":
        guess = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        cmd = str(guess) if guess.exists() else None
    if not cmd:
        raise OcrUnavailable(
            "Tesseract bulunamadı. Windows: https://github.com/UB-Mannheim/tesseract/wiki adresinden kurun "
            "veya TESSERACT_CMD ortam değişkenine tesseract.exe yolunu yazın."
        )
    return cmd


def _run_tesseract(img, *args: str) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    r = subprocess.run([_tesseract(), "stdin", "stdout", *args], input=buf.getvalue(), capture_output=True, check=False)
    return r.stdout.decode("utf-8", errors="replace")


def ocr_words(img) -> list[Word]:
    from PIL import Image

    g = img.convert("L")
    g = g.resize((g.width * OCR_SCALE, g.height * OCR_SCALE), Image.LANCZOS)
    tsv = _run_tesseract(g, "--psm", "6", "tsv")
    words = []
    for r in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        t = (r.get("text") or "").strip()
        if not t:
            continue
        words.append(
            Word(t, int(r["left"]), int(r["top"]), int(r["width"]), int(r["height"]),
                 (int(r["block_num"]), int(r["par_num"]), int(r["line_num"])))
        )
    return words


def _lines(words: list[Word]) -> list[list[Word]]:
    by: dict[tuple, list[Word]] = {}
    for w in words:
        by.setdefault(w.line, []).append(w)
    out = [sorted(v, key=lambda w: w.left) for v in by.values()]
    out.sort(key=lambda ws: min(w.top for w in ws))
    return out


def _badges(img) -> list[tuple[int, int | None, str]]:
    """Program-number badges down the left edge: [(y_centre_in_ocr_scale, number, method)]."""
    from PIL import Image, ImageFilter

    def sat(p):
        return max(p) - min(p) > 60

    out = []
    w, h = img.size
    y = int(h * 0.2)
    x_probe = max(2, int(w * 0.023))
    while y < h:
        if sat(img.getpixel((x_probe, y))):
            y1 = y
            while y < h and sat(img.getpixel((x_probe, y))):
                y += 1
            if y - y1 > 25:
                mid = (y1 + y) // 2
                xs = [x for x in range(0, min(w, int(w * 0.13))) if sat(img.getpixel((x, mid)))]
                x1, x2 = min(xs), max(xs)
                colour = img.getpixel((x_probe, mid))
                num, method = None, ""
                crop = img.crop((x1 + 5, y1 + 5, x2 - 5, y - 5))
                for th in (190, 225, 240):
                    bw = Image.new("L", crop.size, 255)
                    px, po = crop.load(), bw.load()
                    for cx in range(crop.width):
                        for cy in range(crop.height):
                            if min(px[cx, cy]) > th:
                                po[cx, cy] = 0
                    big = Image.new("L", (crop.width + 40, crop.height + 40), 255)
                    big.paste(bw, (20, 20))
                    big = big.resize((big.width * 4, big.height * 4), Image.LANCZOS)
                    for psm in ("7", "10"):
                        txt = _run_tesseract(big, "--psm", psm, "-c", "tessedit_char_whitelist=0123456789").strip()
                        if txt.isdigit() and 1 <= int(txt) <= 24:
                            num, method = int(txt), "OCR"
                            break
                    if num:
                        break
                if num is None:
                    best = min(BADGE_COLOURS, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, colour)))
                    if sum((a - b) ** 2 for a, b in zip(best, colour)) < 300:
                        num, method = BADGE_COLOURS[best], "COLOUR"
                out.append((mid * OCR_SCALE, num, method))
        y += 1
    return out


# --------------------------------------------------------------------------- number parsing

def parse_clock(text: str) -> float | None:
    """Accurace times "1'46''79" / "27''61" / "7''74" as OCR'd ("146\"°79", "848") -> seconds.
    The last two digits are hundredths; 5 digits = m ss cc."""
    d = re.sub(r"\D", "", text)
    if len(d) == 5:
        m, sec, cs = int(d[0]), int(d[1:3]), int(d[3:])
        return None if sec >= 60 else round(m * 60 + sec + cs / 100, 2)
    if len(d) in (3, 4):
        return round(int(d[:-2]) + int(d[-2:]) / 100, 2)
    return None


def parse_num(text: str) -> float | None:
    t = text.replace(",", ".").strip()
    if t in ("-", "=", "—", "–"):
        return None
    m = re.fullmatch(r"-?\d+(?:\.\d+)?", t)
    return float(t) if m else None


def _match_name(name: str, candidates: list[str]) -> str | None:
    key = fold(name)
    folded = {fold(c): c for c in candidates}
    if key in folded:
        return folded[key]
    best = difflib.get_close_matches(key, list(folded), n=2, cutoff=0.75)
    if len(best) == 1 or (len(best) == 2 and difflib.SequenceMatcher(None, key, best[0]).ratio() - difflib.SequenceMatcher(None, key, best[1]).ratio() > 0.1):
        return folded[best[0]]
    return None


# --------------------------------------------------------------------------- page parsing

TITLE = re.compile(r"^(.*?)\s*/.*Ko[sş]u\s*(\d{1,2})\b", re.IGNORECASE)
DATE_LINE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s*/\s*(\d{3,4})\s*Metre\s*(\w+)", re.IGNORECASE)
DIST_HEAD = re.compile(r"^(\d{3,4})m\.?$", re.IGNORECASE)


def _meta(lines: list[list[Word]], page: ReportPage) -> None:
    for ws in lines[:8]:
        txt = " ".join(w.text for w in ws)
        m = TITLE.search(txt)
        if m and page.race_no is None:
            page.track, page.race_no = m.group(1).strip(), int(m.group(2))
        d = DATE_LINE.search(txt)
        if d and page.race_date is None:
            page.race_date = date(int(d.group(3)), int(d.group(2)), int(d.group(1)))
            page.distance_m, page.surface = int(d.group(4)), d.group(5)


def _name_and_rest(ws: list[Word], name_left: float, first_col_left: float) -> tuple[str, list[Word]]:
    name = [w for w in ws if name_left <= w.left < first_col_left - 10]
    rest = [w for w in ws if w.left >= first_col_left - 10]
    return " ".join(w.text for w in name), rest


def _attach_badges(page: ReportPage, rows: list[tuple[float, dict]], badges) -> None:
    for y, horse in rows:
        near = [b for b in badges if abs(b[0] - y) < 60 * OCR_SCALE / 3 * 1.5]
        if near:
            b = min(near, key=lambda b: abs(b[0] - y))
            horse["program_no"], horse["program_no_method"] = b[1], b[2]


def parse_summary(img, words: list[Word] | None = None) -> ReportPage:
    words = words if words is not None else ocr_words(img)
    lines = _lines(words)
    page = ReportPage("SUMMARY", None, None, None, None, None)
    _meta(lines, page)
    head_i = next((i for i, ws in enumerate(lines) if sum(bool(DIST_HEAD.match(w.text)) for w in ws) >= 3), None)
    if head_i is None:
        page.issues.append("Ara mesafe başlığı (400m. 600m. ...) bulunamadı")
        return page
    cols = [(int(DIST_HEAD.match(w.text).group(1)), w.cx, w.left) for w in lines[head_i] if DIST_HEAD.match(w.text)]
    centers = [c[1] for c in cols]
    first_left = min(c[2] for c in cols) - 0.35 * (centers[1] - centers[0])
    name_left = img.width * OCR_SCALE * 0.08

    def col_of(w: Word) -> int:
        return min(range(len(centers)), key=lambda i: abs(centers[i] - w.cx))

    # leader times line right under the header
    if head_i + 1 < len(lines):
        lead = {}
        for w in lines[head_i + 1]:
            if w.left >= first_left:
                lead.setdefault(col_of(w), []).append(w.text)
        page.header["leader_times"] = {cols[i][0]: parse_clock("".join(t)) for i, t in lead.items()}

    rows = []
    for ws in lines[head_i + 2:]:
        name, rest = _name_and_rest(ws, name_left, first_left)
        if not name or not re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2}", name) or len(rest) < len(cols):
            continue
        cells: dict[int, list[str]] = {}
        for w in rest:
            cells.setdefault(col_of(w), []).append(w.text)
        splits = []
        for i, (dist, _, _) in enumerate(cols):
            txt = "".join(cells.get(i, []))
            tpart, _, rpart = txt.partition("[")
            rank = re.match(r"\s*(\d{1,2})", rpart)
            splits.append({"distance_m": dist, "time_s": parse_clock(tpart), "position": int(rank.group(1)) if rank else None, "raw": txt})
        horse = {"name": name.strip(), "splits": splits}
        rows.append((min(w.top for w in ws), horse))
        page.horses.append(horse)
    _attach_badges(page, rows, _badges(img))
    _validate_summary(page)
    return page


def _validate_summary(page: ReportPage) -> None:
    n = len(page.horses)
    for h in page.horses:
        prev = 0.0
        for sp in h["splits"]:
            t = sp["time_s"]
            if t is None:
                page.issues.append(f"{h['name']} {sp['distance_m']} m: süre okunamadı ('{sp['raw']}')")
                continue
            if t <= prev or sp["distance_m"] / t > 20 or sp["distance_m"] / t < 8:
                page.issues.append(f"{h['name']} {sp['distance_m']} m: süre tutarsız ({t}), atıldı")
                sp["time_s"] = None
                continue
            prev = t
            if sp["position"] is not None and not (1 <= sp["position"] <= n):
                sp["position"] = None
    if not page.horses:
        return
    last = len(page.horses[0]["splits"]) - 1
    for k, dist in enumerate(sp["distance_m"] for sp in page.horses[0]["splits"]):
        if k == last:
            continue  # at the finish Accurace shows the official placing, which may differ from its own timing
        col = [(h["splits"][k]["time_s"], h["splits"][k]["position"], h) for h in page.horses]
        known = [c for c in col if c[0] is not None]
        # positions must follow the times (ties allowed)
        for a in known:
            for b in known:
                if a[1] and b[1] and a[1] < b[1] and a[0] > b[0] + 0.005:
                    page.issues.append(f"{dist} m: {a[2]['name']} sıra {a[1]} ama süresi {b[2]['name']}'den yavaş; sıralar süreden yeniden hesaplandı")
                    break
        ordered = sorted(known, key=lambda c: c[0])
        for c in col:
            if c[0] is not None:
                c[2]["splits"][k]["position"] = 1 + sum(1 for o in ordered if o[0] < c[0] - 0.005)
        lead = page.header.get("leader_times", {}).get(dist)
        if lead and ordered and abs(ordered[0][0] - lead) > 0.015:
            page.issues.append(f"{dist} m: başlıktaki lider süresi {lead} ≠ en iyi süre {ordered[0][0]}")


DETAIL_KEYS = ["seg_time", "seg_dist", "rail_m", "seg_avg_kmh", "end_time", "max_kmh", "end_avg_kmh", "total_m", "delta_m", "fark"]


def parse_detail(img, words: list[Word] | None = None) -> ReportPage:
    words = words if words is not None else ocr_words(img)
    lines = _lines(words)
    page = ReportPage("DETAIL", None, None, None, None, None)
    _meta(lines, page)
    for ws in lines[:12]:
        txt = " ".join(w.text for w in ws)
        m = re.search(r"\b(\d{3,4})\s*metre\b", txt, re.IGNORECASE)
        if m and not DATE_LINE.search(txt):
            page.header["segment_end_m"] = int(m.group(1))
            break
    head_i = next((i for i, ws in enumerate(lines) if any(fold(w.text).startswith("DELTA") for w in ws) and any(fold(w.text) == "FARK" for w in ws)), None)
    if head_i is None:
        page.issues.append("Detay tablo başlığı (… Delta(m) Fark) bulunamadı")
        return page
    hw = lines[head_i]

    def lefts(pred) -> list[int]:
        return [w.left for w in hw if pred(fold(w.text))]

    sure = lefts(lambda t: re.fullmatch(r"S.RE", t) is not None)
    mesafe = lefts(lambda t: t == "MESAFE")
    hiz = lefts(lambda t: t == "HIZ")
    uzak = lefts(lambda t: "UZAK" in t)
    delta = lefts(lambda t: t.startswith("DELTA"))
    fark = lefts(lambda t: t == "FARK")
    if len(sure) < 2 or len(mesafe) < 2 or len(hiz) < 3 or not uzak or not delta or not fark:
        page.issues.append("Detay tablo sütunları tanınamadı")
        return page
    col_left = [sure[0], mesafe[0], uzak[0], hiz[0], sure[1], hiz[1], hiz[2], mesafe[1], delta[0], fark[0]]
    first_left = col_left[0]
    name_left = img.width * OCR_SCALE * 0.08

    def col_of(w: Word) -> int:
        return min(range(len(col_left)), key=lambda i: abs(col_left[i] - w.left))

    rows = []
    for ws in lines[head_i + 1:]:
        name, rest = _name_and_rest(ws, name_left, first_left)
        if not name or not re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]{2}", name) or len(rest) < 6:
            continue
        cells: dict[int, list[str]] = {}
        for w in rest:
            cells.setdefault(col_of(w), []).append(w.text)
        raw = {k: "".join(cells.get(i, [])) for i, k in enumerate(DETAIL_KEYS)}
        horse = {
            "name": name.strip(),
            "seg_time": parse_clock(raw["seg_time"]),
            "end_time": parse_clock(raw["end_time"]),
            **{k: parse_num(raw[k]) for k in ("seg_dist", "rail_m", "seg_avg_kmh", "max_kmh", "end_avg_kmh", "total_m", "delta_m", "fark")},
            "raw": raw,
        }
        if horse["seg_time"] is None and horse["end_time"] is None:
            continue  # footer / disclaimer text
        rows.append((min(w.top for w in ws), horse))
        page.horses.append(horse)
    _attach_badges(page, rows, _badges(img))
    _validate_detail(page)
    return page


def _validate_detail(page: ReportPage) -> None:
    for h in page.horses:
        if h["seg_time"] and h["seg_dist"]:
            if h["seg_avg_kmh"] and abs(h["seg_dist"] / h["seg_time"] * 3.6 - h["seg_avg_kmh"]) > 0.6:
                page.issues.append(f"{h['name']}: bölüm süresi/hızı uyumsuz ({h['raw']['seg_time']} / {h['seg_avg_kmh']}), bölüm atıldı")
                h["seg_time"] = None
        if h["end_time"] and h["total_m"] and h["end_avg_kmh"]:
            if abs(h["total_m"] / h["end_time"] * 3.6 - h["end_avg_kmh"]) > 0.4:
                page.issues.append(f"{h['name']}: toplam mesafe/süre/ortalama hız uyumsuz ({h['total_m']} m, {h['end_time']} sn, {h['end_avg_kmh']} km/s)")
                h["total_m"] = None
        if h["max_kmh"] is not None and h["max_kmh"] <= 0:
            h["max_kmh"] = None  # Accurace shows 0,0 when it has no max speed
    winner = next((h for h in page.horses if h["delta_m"] is None and h["total_m"]), None)
    if winner:
        for h in page.horses:
            if h["delta_m"] is not None and h["total_m"] and abs(h["total_m"] - winner["total_m"] - h["delta_m"]) > 1.5:
                page.issues.append(f"{h['name']}: delta {h['delta_m']} m, mesafe farkıyla uyumsuz")


# --------------------------------------------------------------------------- combine

def build_interchange(summary: ReportPage | None, detail: ReportPage | None, tjk_names: list[str] | None = None) -> tuple[dict[str, Any], list[str]]:
    """Merge the two pages into HorseIQ's Accurace interchange JSON."""
    pages = [p for p in (summary, detail) if p]
    if not pages:
        raise ValueError("En az bir rapor gerekli")
    issues = [f"[{p.kind}] {i}" for p in pages for i in p.issues]
    ref = pages[0]
    for p in pages[1:]:
        if (p.race_date, p.race_no) != (ref.race_date, ref.race_no) or fold(p.track or "") != fold(ref.track or ""):
            raise ValueError(f"Raporlar farklı koşulara ait: {ref.race_date} {ref.track} {ref.race_no} / {p.race_date} {p.track} {p.race_no}")
    if not (ref.race_date and ref.track and ref.race_no):
        raise ValueError("Rapor başlığından tarih/hipodrom/koşu no okunamadı")

    names = [h["name"] for p in pages for h in p.horses]
    canon = {}
    for n in names:
        target = _match_name(n, tjk_names) if tjk_names else None
        canon[n] = target or n
        if tjk_names and target is None:
            issues.append(f"'{n}' TJK listesinde bulunamadı")

    horses: dict[str, dict] = {}
    for p in pages:
        for h in p.horses:
            key = fold(canon[h["name"]])
            rec = horses.setdefault(key, {"name": canon[h["name"]], "ocr_name": h["name"], "program_no": None, "sectionals": [], "extra": {}})
            if h.get("program_no") and not rec["program_no"]:
                rec["program_no"] = h["program_no"]
                rec["extra"]["program_no_method"] = h.get("program_no_method")
            if p.kind == "SUMMARY":
                prev_d, prev_t = 0, 0.0
                cum = []
                for sp in h["splits"]:
                    cum.append({"distance_m": sp["distance_m"], "time_s": sp["time_s"], "position": sp["position"]})
                    if sp["time_s"] is None:
                        prev_d = None
                        continue
                    if prev_d is not None:
                        rec["sectionals"].append(
                            {"from_m": prev_d, "to_m": sp["distance_m"], "time_s": round(sp["time_s"] - prev_t, 2),
                             "speed_mps": round((sp["distance_m"] - prev_d) / (sp["time_s"] - prev_t), 3), "position": sp["position"]}
                        )
                    prev_d, prev_t = sp["distance_m"], sp["time_s"]
                rec["extra"]["cumulative"] = cum
                rec["extra"]["accurace_finish_s"] = h["splits"][-1]["time_s"]
            else:
                rec["total_distance_m"] = h["total_m"]
                rec["avg_speed_mps"] = round(h["end_avg_kmh"] / 3.6, 3) if h["end_avg_kmh"] else None
                rec["max_speed_mps"] = round(h["max_kmh"] / 3.6, 3) if h["max_kmh"] else None
                seg_end = p.header.get("segment_end_m")
                rec["extra"]["segment"] = {
                    "to_m": seg_end, "from_m": (seg_end - h["seg_dist"]) if seg_end and h["seg_dist"] else None,
                    "time_s": h["seg_time"], "avg_speed_kmh": h["seg_avg_kmh"], "rail_distance_m": h["rail_m"],
                }
                rec["extra"]["delta_m"] = h["delta_m"]
                rec["extra"]["fark"] = h["fark"]
                rec["extra"]["detail_finish_s"] = h["end_time"]

    # cross-check the two pages
    for rec in horses.values():
        a, b = rec["extra"].get("accurace_finish_s"), rec["extra"].get("detail_finish_s")
        if a and b and abs(a - b) > 0.015:
            issues.append(f"{rec['name']}: özet bitiriş {a} ≠ detay bitiriş {b}")
        seg = rec["extra"].get("segment") or {}
        cum = {c["distance_m"]: c["time_s"] for c in rec["extra"].get("cumulative", [])}
        if seg.get("time_s") and seg.get("from_m") in cum and seg.get("to_m") in cum and cum[seg["from_m"]] and cum[seg["to_m"]]:
            diff = cum[seg["to_m"]] - cum[seg["from_m"]]
            if abs(diff - seg["time_s"]) > 0.015:
                issues.append(f"{rec['name']}: bölüm süresi {seg['time_s']} ≠ ara derece farkı {diff:.2f}")
    progs = [r["program_no"] for r in horses.values() if r["program_no"]]
    if len(progs) != len(set(progs)):
        issues.append("Program numaraları tekrar ediyor; numaralar kullanılmadı")
        for r in horses.values():
            r["program_no"] = None

    return {
        "date": ref.race_date.isoformat(),
        "track": ref.track,
        "race_no": ref.race_no,
        "distance_m": ref.distance_m,
        "source": "ACCURACE_PDF",
        "horses": list(horses.values()),
    }, issues


def read_pages(paths: list[str | Path]) -> tuple[ReportPage | None, ReportPage | None]:
    """OCR each PDF and tell summary from detail by its content (not by file name)."""
    summary = detail = None
    for p in paths:
        img = load_image(p)
        words = ocr_words(img)
        if any(fold(w.text) == "FARK" for w in words):
            detail = parse_detail(img, words)
        else:
            summary = parse_summary(img, words)
    return summary, detail


def read_reports(paths: list[str | Path], tjk_names: list[str] | None = None) -> tuple[dict[str, Any], list[str]]:
    summary, detail = read_pages(paths)
    return build_interchange(summary, detail, tjk_names)
