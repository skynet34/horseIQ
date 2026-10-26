from datetime import date

import pytest
from fastapi.testclient import TestClient

from horseiq.collectors import demo
from horseiq.collectors.importer import Importer


@pytest.fixture
def client(engine, monkeypatch):
    Importer(engine).import_races(demo.generate(date(2026, 8, 1), date(2026, 10, 20), n_horses=60, seed=3, today_card=date(2026, 10, 26)), "DEMO")
    from horseiq.api import app as app_mod

    monkeypatch.setattr(app_mod, "get_engine", lambda: engine)
    monkeypatch.setattr(app_mod, "_cache", None)
    return TestClient(app_mod.app)


def test_flow(client):
    assert client.get("/api/meetings", params={"world": "REAL"}).json()["meetings"] == []  # no real data mixed in
    m = client.get("/api/meetings", params={"world": "DEMO", "day": "2026-10-26"}).json()
    race = m["meetings"][0]["races"][0]
    assert race["data_status"] == "DEMO" and not race["has_results"]
    detail = client.get(f"/api/races/{race['id']}").json()
    horse = detail["runners"][0]["horse_id"]
    res = client.post(f"/api/races/{race['id']}/simulate", json={"seed": 5, "intervention": {"horse_id": horse, "type": "blocked", "phase": "final_turn"}}).json()
    assert len(res["normal"]["order"]) == len(detail["runners"])
    assert res["comparison"] and res["intervention"]["events"]
    again = client.post(f"/api/races/{race['id']}/simulate", json={"seed": 5}).json()
    assert [o["time_s"] for o in again["normal"]["order"]] == [o["time_s"] for o in res["normal"]["order"]]
