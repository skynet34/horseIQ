from datetime import date

from sqlalchemy import func, select

from horseiq.collectors.importer import Importer
from horseiq.collectors.tjk import parse_html, parse_payload
from horseiq.db import schema as s
from horseiq.domain import DataStatus, EntryRecord, RaceRecord, Surface, fold, parse_race_time, parse_surface


def test_parsers_basic():
    assert parse_race_time("1.24.36") == 84.36
    assert parse_race_time("1:24.36") == 84.36
    assert parse_race_time("58.70") == 58.7
    assert parse_race_time("") is None
    assert fold("Şanlıurfa") == "SANLIURFA"
    assert parse_surface("Çim") == Surface.TURF and parse_surface("Kum") == Surface.DIRT


def _race(status=DataStatus.REAL, entries=None, source="TJK_API", no=1):
    return RaceRecord(
        race_date=date(2025, 6, 25), racetrack="İstanbul", race_no=no, source_system=source, data_status=status,
        distance_m=1400, surface=Surface.TURF, has_results=True,
        entries=entries or [
            EntryRecord("AT A", 1, source_horse_id="100", finish_pos=1, finish_time_s=84.36, result_status="FINISHED"),
            EntryRecord("AT B", 2, source_horse_id="200", finish_pos=2, finish_time_s=84.52, result_status="FINISHED"),
        ],
    )


def test_import_is_idempotent(engine):
    imp = Importer(engine)
    r1 = imp.import_races([_race()], "TJK_API")
    r2 = imp.import_races([_race()], "TJK_API")
    assert r1.races_inserted == 1 and r2.races_inserted == 0
    with engine.connect() as c:
        assert c.execute(select(func.count()).select_from(s.races)).scalar() == 1
        assert c.execute(select(func.count()).select_from(s.race_results)).scalar() == 2
        assert c.execute(select(func.count()).select_from(s.horses)).scalar() == 2


def test_source_id_beats_name(engine):
    imp = Importer(engine)
    imp.import_races([_race()], "TJK_API")
    # same name, different TJK id -> different horse (names can repeat)
    other = _race(entries=[EntryRecord("AT A", 1, source_horse_id="999", finish_pos=1, finish_time_s=80.0, result_status="FINISHED")], no=2)
    imp.import_races([other], "TJK_API")
    with engine.connect() as c:
        assert c.execute(select(func.count()).select_from(s.horses).where(s.horses.c.name_key == "AT A")).scalar() == 2


def test_missing_entry_marked_scratched(engine):
    imp = Importer(engine)
    imp.import_races([_race()], "TJK_API")
    rep = imp.import_races([_race(entries=[EntryRecord("AT A", 1, source_horse_id="100")])], "TJK_API")
    assert any("koşmaz" in i["message"] for i in rep.issues)
    with engine.connect() as c:
        assert c.execute(select(func.count()).select_from(s.race_entries).where(s.race_entries.c.scratched.is_(True))).scalar() == 1


def test_demo_never_merges_into_real(engine):
    imp = Importer(engine)
    imp.import_races([_race()], "TJK_API")
    rep = imp.import_races([_race(status=DataStatus.DEMO, source="DEMO")], "DEMO")
    assert rep.errors and "karıştırılamaz" in rep.errors[0]["message"]


def test_invalid_time_reported(engine):
    bad = _race(entries=[EntryRecord("AT X", 1, finish_pos=1, finish_time_s=20.0, result_status="FINISHED")])
    rep = Importer(engine).import_races([bad], "TJK_API")
    assert rep.errors and rep.races_inserted == 0


def test_tjk_raw_payload():
    payload = {
        "success": True,
        "data": {"yarislar": [{
            "KEY": "ISTANBUL", "YER": "İstanbul", "TARIH": "25/06/2025", "YURTDISI": False,
            "pist": {"cim": {"DURUM": "Normal", "AGIRLIK": 3}, "kum": {"DURUM": "Islak", "AGIRLIK": 2}},
            "kosular": [{"NO": "1", "SAAT": "13:30", "PIST": "Çim", "MESAFE": "1400", "GRUP": "Şartlı 1", "CINSDETAY": "3 Yaşlı",
                          "atlar": [
                              {"KEY": "11", "NO": "1", "AD": "AT A", "START": "3", "SONUC": "1", "DERECE": "1.24.36", "KILO": "57", "JOKEYADI": "J A"},
                              {"KEY": "12", "NO": "2", "AD": "AT B", "START": "1", "SONUC": "2", "DERECE": "1.24.52", "FARK": "1", "KILO": "55,5", "JOKEYADI": "J B"},
                              {"KEY": "13", "NO": "3", "AD": "AT C", "KOSMAZ": True},
                          ]}],
        }, {"KEY": "X", "YER": "Chantilly", "TARIH": "25/06/2025", "YURTDISI": True, "kosular": []}]},
    }
    races = parse_payload(payload, with_results=True)
    assert len(races) == 1  # foreign meeting skipped
    r = races[0]
    assert r.surface == Surface.TURF and r.going == "Normal" and r.distance_m == 1400 and r.has_results
    a, b, c = r.entries
    assert a.finish_time_s == 84.36 and a.gate == 3 and b.weight_kg == 55.5 and b.margin_text == "1"
    assert c.scratched and c.result_status == "SCRATCHED"


HTML = """
<html><body>
<ul class="gunluk-tabs"><li class="active"><a id="İstanbul" data-sehir-id="1">İstanbul (12. Y.G.)</a></li></ul>
<input name="QueryParameter_Tarih" value="25/06/2025">
<div class="race-details"><h3>1. Koşu 13:30</h3><p>Şartlı 1, 3 Yaşlı İngilizler, 1400 Çim</p></div>
<table>
<tr><th>S</th><th>At No</th><th>At İsmi</th><th>Yaş</th><th>Orijin(Baba - Anne)</th><th>Sıklet</th><th>Jokey</th><th>Derece</th><th>Fark</th><th>St</th></tr>
<tr><td>1</td><td>4</td><td><a href="/TR/YarisSever/Query/ConnectedPage/AtKosuBilgileri?QueryParameter_AtId=55501">KARAYEL (1)</a></td><td>3y d a</td><td>BABA - ANNE</td><td>57</td><td><a href="?JokeyId=9">J. DOE</a></td><td>1.24.36</td><td></td><td>2</td></tr>
<tr><td>2</td><td>1</td><td><a href="?QueryParameter_AtId=55502">POYRAZ</a></td><td>3y k a</td><td>X - Y</td><td>55,5</td><td>A. B</td><td>1.24.52</td><td>1</td><td>5</td></tr>
</table></body></html>
"""


def test_tjk_saved_page():
    races = parse_html(HTML)
    assert len(races) == 1
    r = races[0]
    assert r.race_date == date(2025, 6, 25) and r.racetrack == "İstanbul" and r.race_no == 1
    assert r.distance_m == 1400 and r.surface == Surface.TURF and r.post_time == "13:30"
    a, b = r.entries
    assert a.horse_name == "KARAYEL" and a.source_horse_id == "55501" and a.finish_time_s == 84.36 and a.gate == 2
    assert a.sire == "BABA" and b.weight_kg == 55.5 and b.margin_text == "1"
