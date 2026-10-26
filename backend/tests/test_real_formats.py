"""TJK CSV + Accurace report readers.

Fixtures are synthetic (invented horses) in the exact layout of the real downloads; the real
files are not committed (data_inbox/ is git-ignored). If the real 01.10.2026 Kocaeli files are
present in data_inbox/, the end-to-end test also runs on them.
"""
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from horseiq.collectors.accurace import import_tracking, parse_tracking_json
from horseiq.collectors.accurace.pdf_report import ReportPage, build_interchange, parse_clock, parse_num
from horseiq.collectors.importer import Importer
from horseiq.collectors.tjk.csv_results import SOURCE, clean_name, parse_text
from horseiq.db import schema as s

INBOX = Path(__file__).resolve().parents[2] / "data_inbox"

CSV = "﻿" + "\r\n".join([
    "Kocaeli;(38. Yarış Günü);01/10/2026",
    "1. Kosu :   11.30;Maiden/DHÖW; 3 Yaşlı Araplar; 57.00kg; 1500m; Kum;;;;Rekor Derece :1.41.10",
    "İkramiye;;;;;Yetiştirici Primi;;;;",
    "1.)545.000 TL;2.)218.000 TL;;",
    "At No;At İsmi;Yaş;Orijin(Baba);Orijin(Anne);Kilo;Jokey Adı;Sahip Adı;Antrenör Adı;St;AGF;H;Derece;Ganyan;Fark",
    "1;DEMİR KANAT KG DB;3y k  e;BABA A;ANNE A;57;A.YILMAZ;SAHİP A;T.A;7;%10.28(3);;1:46.55;7,80;Boyun",
    "2;RÜZGAR OĞLU KG DB GKR;3y a  e;BABA B;ANNE B;57 +0.60;B.KAYA AP;SAHİP B;T.B;10 - DS;%3.58(8);17;1:46.58;12,50;5,5 Boy",
    "3;I RO K;3y a  d;BABA C;ANNE C;54 +0.20;C.EK;SAHİP C;T.C;1;%4.19(7);23;Derecesiz;14,30;",
    "4;KAYIP AT KG K (Koşmaz);3y a  d;BABA D;ANNE D;55;D.EK AP;SAHİP D;T.D;5;%0.36(11);23;Koşmaz;;",
    "GANYAN(4) :7,80 TL, İKİLİ(3/4) :107,45 TL",
    "",
    "2. Kosu :  ÖZEL KOŞU 12.00;Handikap 15 /H2; 3 Yaşlı İngilizler; kg; 2000m; Çim;;;;Rekor Derece :2.07.41",
    "At No;At İsmi;Yaş;Orijin(Baba);Orijin(Anne);Kilo;Jokey Adı;Sahip Adı;Antrenör Adı;St;AGF;H;Derece;Ganyan;Fark",
    "1;STEEL TEST K;3y d  e;KING (USA);BERT;57,5;A.YILMAZ;X;N.B;4;%16.47(2)  %11.69(3);48;2:09.89;3,85;9 Boy",
    "2;OTHER TEST;3y d  g;TILSIT (USA);ŞEKER;58 +0.30;M.KAYA;Y;V.K;3;%13.27(4);49;2:11.76;6,75;",
    "GANYAN(7) :3,85 TL",
    "",
])


def test_clean_name():
    assert clean_name("KADERİ GÜZEL KG DB") == ("KADERİ GÜZEL", False)
    assert clean_name("ARKAZGÜLÜ KG K (Koşmaz)") == ("ARKAZGÜLÜ", True)
    assert clean_name("I RO K") == ("I RO", False)
    assert clean_name("K") == ("K", False)  # never strips the whole name


def test_tjk_csv_layout():
    races = parse_text(CSV)
    assert [r.race_no for r in races] == [1, 2]
    r1, r2 = races
    assert (r1.distance_m, r1.surface.value, r1.post_time, r1.race_class) == (1500, "DIRT", "11:30", "Maiden/DHÖW")
    assert "3 Yaşlı Araplar" in r1.conditions and r1.has_results
    assert (r2.distance_m, r2.surface.value, r2.post_time) == (2000, "TURF", "12:00") and "ÖZEL KOŞU" in r2.conditions
    a, b, c, d = r1.entries
    assert (a.horse_name, a.finish_pos, a.finish_time_s, a.program_no, a.gate, a.birth_year, a.sex) == ("DEMİR KANAT", 1, 106.55, 4, 7, 2023, "erkek")
    assert (b.weight_kg, b.jockey_name, b.jockey_apprentice, b.gate, b.margin_text) == (57.6, "B.KAYA", True, 10, "5,5 Boy")
    assert b.program_no is None  # CSV has no program numbers (only the winner's, from GANYAN)
    assert (c.horse_name, c.result_status, c.finish_pos) == ("I RO", "DNF", None)
    assert (d.horse_name, d.scratched, d.result_status) == ("KAYIP AT", True, "SCRATCHED")
    assert r2.entries[0].weight_kg == 57.5 and r2.entries[1].weight_kg == 58.3


def test_tjk_csv_reimport_and_pedigree(engine):
    imp = Importer(engine)
    rep1 = imp.import_races(parse_text(CSV), SOURCE)
    rep2 = imp.import_races(parse_text(CSV), SOURCE)
    assert rep1.races_inserted == 2 and rep2.races_inserted == 0 and not rep2.errors
    assert not [i for i in rep2.issues if "isimle" in i["message"]]  # name + sire + dam agree -> quiet
    # same name, different dam -> a different horse
    other = parse_text(CSV.replace("01/10/2026", "08/10/2026").replace("ANNE A", "BAŞKA ANNE"))
    imp.import_races(other, SOURCE)
    with engine.connect() as conn:
        n = conn.execute(select(s.horses.c.id).where(s.horses.c.name == "DEMİR KANAT")).all()
    assert len(n) == 2


def test_clock_and_numbers():
    assert parse_clock("1'46''79") == 106.79
    assert parse_clock('146"°79') == 106.79  # OCR noise
    assert parse_clock("27°61") == 27.61
    assert parse_clock("848") == 8.48
    assert parse_clock("10°46") == 10.46
    assert parse_clock("1'75''00") is None  # 75 seconds is not a clock
    assert parse_num("-1,8") == -1.8 and parse_num("=") is None and parse_num("1511") == 1511


def _pages():
    from datetime import date

    meta = dict(track="Kocaeli", race_no=1, race_date=date(2026, 10, 1), distance_m=1500, surface="Kum")
    summ = ReportPage("SUMMARY", **meta)
    det = ReportPage("DETAIL", **meta, header={"segment_end_m": 1500})
    for name, prog, cum, pos, total, avg, seg, rail, delta in [
        ("DEMiR KANAT", 4, [28.22, 41.00, 106.79], [6, 6, 1], 1511, 50.9, 7.74, 12.0, None),
        ("RUZGAR OGLU", None, [30.33, 42.99, 106.89], [10, 10, 2], 1509, 50.8, 7.68, 8.8, -1.8),
    ]:
        splits = [{"distance_m": d, "time_s": t, "position": p, "raw": ""} for d, t, p in zip((400, 600, 1500), cum, pos)]
        summ.horses.append({"name": name, "splits": splits, "program_no": prog, "program_no_method": "OCR"})
        det.horses.append({"name": name, "seg_time": seg, "seg_dist": 100.0, "rail_m": rail, "seg_avg_kmh": 46.5, "end_time": cum[-1],
                           "max_kmh": None, "end_avg_kmh": avg, "total_m": total, "delta_m": delta, "fark": 2.0, "raw": {}})
    return summ, det


def test_accurace_interchange_and_import(engine):
    Importer(engine).import_races(parse_text(CSV), SOURCE)
    obj, issues = build_interchange(*_pages(), tjk_names=["DEMİR KANAT", "RÜZGAR OĞLU", "I RO", "KAYIP AT"])
    assert not [i for i in issues if "bulunamadı" in i]
    h = {x["name"]: x for x in obj["horses"]}
    assert set(h) == {"DEMİR KANAT", "RÜZGAR OĞLU"}
    secs = h["DEMİR KANAT"]["sectionals"]
    assert [(x["from_m"], x["to_m"], x["time_s"]) for x in secs] == [(0, 400, 28.22), (400, 600, 12.78), (600, 1500, 65.79)]
    assert h["DEMİR KANAT"]["extra"]["segment"] == {"to_m": 1500, "from_m": 1400.0, "time_s": 7.74, "avg_speed_kmh": 46.5, "rail_distance_m": 12.0}
    rep = import_tracking(engine, parse_tracking_json(obj))
    assert rep.results_upserted == 2 and not rep.errors
    with engine.connect() as conn:
        perf = conn.execute(select(s.horse_performances.c.total_distance_m, s.horse_performances.c.extra)).all()
        prog = conn.execute(select(s.race_entries.c.program_no).join(s.horses, s.horses.c.id == s.race_entries.c.horse_id).where(s.horses.c.name == "DEMİR KANAT")).scalar()
    assert sorted(p.total_distance_m for p in perf) == [1509, 1511]
    assert prog == 4


def test_accurace_mismatched_reports_rejected():
    summ, det = _pages()
    det.race_no = 2
    with pytest.raises(ValueError):
        build_interchange(summ, det)


REAL = {
    "csv": INBOX / "01.10.2026-Kocaeli-GunlukYarisSonuclari-TR.csv",
    "summary": INBOX / "2026-10-01-kocaeli-1-summary.pdf",
    "detail": INBOX / "2026-10-01-kocaeli-1.pdf",
}


@pytest.mark.skipif(not all(p.exists() for p in REAL.values()) or not shutil.which("tesseract"), reason="gerçek dosyalar veya tesseract yok")
def test_real_kocaeli_2026_10_01(engine):
    from horseiq.collectors.accurace.pdf_report import read_reports
    from horseiq.collectors.tjk.csv_results import parse_file

    races = parse_file(REAL["csv"])
    assert len(races) == 10 and sum(len(r.entries) for r in races) == 106
    Importer(engine).import_races(races, SOURCE)
    names = [e.horse_name for e in races[0].entries]
    obj, issues = read_reports([REAL["summary"], REAL["detail"]], names)
    assert not [i for i in issues if "bulunamadı" in i or "≠" in i or "uyumsuz" in i], issues
    h = {x["name"]: x for x in obj["horses"]}
    assert len(h) == 10
    assert h["KADERİ GÜZEL"]["program_no"] == 4 and h["KADERİ GÜZEL"]["total_distance_m"] == 1511
    assert h["PAMİR ASLANI"]["extra"]["cumulative"][-1]["time_s"] == 114.55
    assert h["HAMZA KIZI"]["sectionals"][0] == {"from_m": 0, "to_m": 400, "time_s": 27.61, "speed_mps": 14.488, "position": 1}
    rep = import_tracking(engine, parse_tracking_json(obj))
    assert rep.results_upserted == 10 and not rep.errors


# --------------------------------------------------------------------------- horse history (browser button)

def _horse_json(rows, filters=("Tüm Yıllar",)):
    header = ["Tarih", "Şehir", "Msf", "Pist", "S", "Derece", "Sıklet", "Takı", "Jokey", "St", "Gny", "Grup",
              "K. No-K. Adı", "Kcins", "Ant.", "Sahip", "HP", "İkramiye", "S20", "", ""]
    return {
        "kind": "TJK_AT_KOSU_BILGILERI", "kit_version": "1", "at_id": "900001", "name": "DEMİR KANAT",
        "info": {"İsim": "DEMİR KANAT", "Yaş": "3 y ke", "Doğ. Trh": "10.03.2023", "Baba": "BABA A", "Anne": "ANNE A / ANNE BABA"},
        "filters": list(filters), "header": header, "rows": [{"cells": c, "links": []} for c in rows],
    }


HORSE_ROWS = [
    # same race as the CSV fixture (01.10.2026 Kocaeli #1) -> must merge, not duplicate
    ["01.10.2026", "Kocaeli", "1500", "K:Normal", "1", "1.46.55", "57", "KG DB", "A.YILMAZ", "7", "7,8", "3A", "1", "Maiden/Erkek", "T.A", "S", "", "545.000", "5", "", ""],
    ["14.09.2026", "Ankara", "1400", "Ç:Normal | 3.3", "4", "1.30.10", "55 +1.5", "KG", "B.KAYA AP", "3", "5,1", "3A", "2 - ÖZEL KOŞU", "Maiden", "T.A", "S", "", "", "4", "", ""],
    ["01.08.2026", "Ankara", "1300", "K:Ağır", "", "", "57", "", "B.KAYA", "9", "", "3A", "5", "Maiden", "T.A", "S", "", "", "3", "", ""],
    ["garbage", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
]


def test_horse_history_parse():
    from horseiq.collectors.tjk.horse_history import parse_obj, parse_race_cell, parse_track_cell

    assert parse_track_cell("Ç:Normal | 3.3") == ("Çim", "Normal 3.3")
    assert parse_track_cell("K:Normal") == ("Kum", "Normal")
    assert parse_race_cell("2 - ROYAL ASCOT KOŞUSU") == (2, "ROYAL ASCOT KOŞUSU")
    races, issues = parse_obj(_horse_json(HORSE_ROWS))
    assert len(races) == 3 and any("okunamayan" in i for i in issues)
    a, b, c = races
    e = a.entries[0]
    assert (a.race_date.isoformat(), a.racetrack, a.race_no, a.distance_m, a.surface.value, a.partial) == ("2026-10-01", "Kocaeli", 1, 1500, "DIRT", True)
    assert (e.source_horse_id, e.finish_pos, e.finish_time_s, e.birth_year, e.dam, e.sex) == ("900001", 1, 106.55, 2023, "ANNE A", "erkek")
    assert (b.surface.value, b.going, b.conditions, b.entries[0].weight_kg, b.entries[0].jockey_name) == ("TURF", "Normal 3.3", "ÖZEL KOŞU; 3A", 56.5, "B.KAYA")
    assert (c.entries[0].result_status, c.entries[0].finish_pos) == ("DNF", None)
    _, issues = parse_obj(_horse_json(HORSE_ROWS[:1], filters=("2026",)))
    assert any("filtre" in i for i in issues)


def test_horse_history_merges_with_full_card(engine):
    from horseiq.collectors.tjk.horse_history import SOURCE as HSRC, parse_obj
    from horseiq.form.history import load_runs

    imp = Importer(engine)
    imp.import_races(parse_text(CSV), SOURCE)
    races, _ = parse_obj(_horse_json(HORSE_ROWS))
    rep = imp.import_races(races, HSRC)
    imp.import_races(races, HSRC)  # idempotent
    assert not rep.errors and rep.races_inserted == 2  # 01.10 race already existed
    with engine.connect() as conn:
        horses = conn.execute(select(s.horses.c.id).where(s.horses.c.name == "DEMİR KANAT")).all()
        assert len(horses) == 1  # matched by name + pedigree, now carries the TJK id
        ids = conn.execute(select(s.horse_source_ids.c.source_horse_id)).scalars().all()
        assert ids == ["900001"]
        r1 = conn.execute(select(s.races).where(s.races.c.race_no == 1, s.races.c.distance_m == 1500)).first()
        assert r1.race_class == "Maiden/DHÖW"  # full-card value kept
        scratched = conn.execute(select(s.race_entries.c.scratched).where(s.race_entries.c.race_id == r1.id)).scalars().all()
        assert sum(scratched) == 1  # only the CSV's own koşmaz horse
        assert conn.execute(select(s.race_results).where(s.race_results.c.race_id == r1.id)).all().__len__() == 4
    runs = load_runs(engine)
    hid = horses[0].id
    by_date = {r.race_date.isoformat(): r for r in runs[hid]}
    assert by_date["2026-09-14"].field_size == 0  # only this horse known, placed 4th -> size unknown
    assert by_date["2026-10-01"].field_size == 3  # koşmaz not counted
