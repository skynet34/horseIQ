"""TJK data-service adapter (authKey-gated).

TJK serves program/results JSON to licensed clients via an `X-Auth` key
(field names verified against github.com/bilaleren/tjk-api, MIT). HorseIQ has NO key yet,
so `TjkApiClient` refuses to run without TJK_AUTH_KEY. We never guess or borrow a key.

The adapter accepts both the raw service payload ({"success", "data": {"yarislar": [...]}})
and the camelCase output of the tjk-api npm package, so data exported by a licensed user
with that package can also be imported from a file.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Iterable

import httpx

from ...domain import DataStatus, EntryRecord, RaceRecord, parse_race_time, parse_surface

SOURCE = "TJK_API"


class TjkAccessError(RuntimeError):
    pass


class TjkApiClient:
    def __init__(self, auth_key: str | None, base_url: str, min_interval_s: float = 2.0, timeout_s: float = 20.0):
        if not auth_key:
            raise TjkAccessError(
                "TJK_AUTH_KEY tanımlı değil. TJK veri servisi yalnızca TJK'nın verdiği anahtarla kullanılabilir; "
                "tjk.org robots.txt otomatik erişime izin vermiyor. docs/DATA_ACCESS.md dosyasına bakın."
            )
        self._client = httpx.Client(base_url=base_url.rstrip("/"), headers={"X-Auth": auth_key}, timeout=timeout_s)
        self._min_interval = min_interval_s
        self._last = 0.0

    def _get(self, service: str, day: date | None = None, hippodrome: str | None = None) -> dict:
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)  # polite rate limit even with a licence
        params: dict[str, Any] = {}
        if day:
            params["date"] = day.strftime("%d/%m/%Y")
        if hippodrome:
            params["hipodromkey"] = hippodrome
        resp = self._client.get(f"/{service}", params=params)
        self._last = time.monotonic()
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict) or not payload.get("success"):
            raise TjkAccessError(f"TJK servis hatası: {payload!r:.300}")
        return payload

    def program(self, day: date) -> list[RaceRecord]:
        return parse_payload(self._get("program", day), with_results=False)

    def results(self, day: date) -> list[RaceRecord]:
        return parse_payload(self._get("sonuclar", day), with_results=True)


def parse_payload(payload: Any, with_results: bool) -> list[RaceRecord]:
    """Raw TJK payload, raw `yarislar` list, or tjk-api npm (camelCase) list -> RaceRecords."""
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        meetings = data.get("yarislar", data) if isinstance(data, dict) else data
    else:
        meetings = payload
    if not isinstance(meetings, list):
        raise ValueError("TJK verisinde 'yarislar' listesi bulunamadı")
    out: list[RaceRecord] = []
    for m in meetings:
        out.extend(_meeting(m, with_results))
    return out


def _g(d: dict, *keys: str, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _date(text: str) -> date:
    text = text.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Tarih okunamadı: {text}")


def _meeting(m: dict, with_results: bool) -> Iterable[RaceRecord]:
    if _g(m, "YURTDISI", "abroad", default=False):
        return []  # foreign meetings are out of scope
    track = _g(m, "YER", "location", "HIPODROM", "hippodrome", default="")
    day = _date(str(_g(m, "TARIH", "date")))
    runway = _g(m, "pist", "runway", default={}) or {}
    races = []
    for run in _g(m, "kosular", "runs", default=[]) or []:
        pist_name = _g(run, "PIST")
        distance = _g(run, "MESAFE")
        if pist_name is None and isinstance(run.get("runway"), dict):
            pist_name, distance = run["runway"].get("name"), run["runway"].get("distance")
        surface = parse_surface(str(pist_name or ""))
        going = None
        if isinstance(runway, dict):
            key = {"TURF": ("cim", "grass"), "DIRT": ("kum", "sand"), "SYNTHETIC": ("sentetik", "synthetic")}.get(
                surface.value if surface else "", ()
            )
            for k in key:
                if isinstance(runway.get(k), dict):
                    going = _g(runway[k], "DURUM", "status")
        has_results = with_results and any(_g(h, "SONUC", "resultRank") for h in _g(run, "atlar", "horses", default=[]) or [])
        rec = RaceRecord(
            race_date=day,
            racetrack=str(track),
            race_no=int(_g(run, "NO", "no")),
            source_system=SOURCE,
            data_status=DataStatus.REAL,
            distance_m=int(distance) if distance else None,
            surface=surface,
            going=going,
            post_time=_g(run, "SAAT", "startTime"),
            race_class=_g(run, "GRUP", "groupName"),
            conditions=_g(run, "CINSDETAY", "condition"),
            source_race_id=str(_g(m, "KEY", "key", default="")) + f"/{_g(run, 'NO', 'no')}",
            has_results=bool(has_results),
        )
        for h in _g(run, "atlar", "horses", default=[]) or []:
            rec.entries.append(_horse(h, has_results))
        races.append(rec)
    return races


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def _horse(h: dict, has_results: bool) -> EntryRecord:
    jockey = h.get("jockey") if isinstance(h.get("jockey"), dict) else {}
    scratched = bool(_g(h, "KOSMAZ", "outOfRace", default=False))
    rank = _g(h, "SONUC", "resultRank")
    pos = int(rank) if rank not in (None, "") and str(rank).isdigit() else None
    status = None
    if has_results:
        status = "SCRATCHED" if scratched else ("FINISHED" if pos else "DNF")
    father = h.get("father") if isinstance(h.get("father"), dict) else {}
    mother = h.get("mother") if isinstance(h.get("mother"), dict) else {}
    return EntryRecord(
        horse_name=str(_g(h, "AD", "name")),
        program_no=int(_g(h, "NO", "no")) if _g(h, "NO", "no") else None,
        source_horse_id=str(_g(h, "KEY", "key")) if _g(h, "KEY", "key") else None,
        gate=int(_num(_g(h, "START", "position")) or 0) or None,
        jockey_name=_g(h, "JOKEYADI") or jockey.get("name"),
        jockey_apprentice=bool(_g(h, "APRANTI") or jockey.get("apprentice")),
        weight_kg=_num(_g(h, "KILO", "weight")),
        age_text=_g(h, "YAS", "age"),
        sire=_g(h, "BABA") or father.get("name"),
        dam=_g(h, "ANNE") or mother.get("name"),
        scratched=scratched,
        finish_pos=pos,
        finish_time_s=parse_race_time(_g(h, "DERECE", "timing")) if pos else None,
        margin_text=_g(h, "FARK", "difference"),
        result_status=status,
    )
