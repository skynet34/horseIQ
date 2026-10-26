"""HorseIQ command line.  Run from backend/:  python -m horseiq.cli <command> ...

  status                                 counts per table and data status
  seed-demo [--from 2024-10-01]          synthetic DEMO world (never mixed with REAL)
  import-tjk-json FILE [--results]       TJK service payload / tjk-api npm export (REAL)
  import-tjk-html FILE --date --track    TJK page saved manually from a browser (REAL)
  fetch-tjk --date D | --backfill-from D --to D   (needs TJK_AUTH_KEY; newest day first)
  import-accurace FILE                   Accurace interchange JSON (REAL tracking)
  backtest --world REAL|DEMO --from D --to D [--mode days|races] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import func, select

from .collectors import demo
from .collectors.accurace import import_tracking, parse_tracking_json
from .collectors.importer import Importer
from .collectors.tjk import TjkAccessError, TjkApiClient, parse_file, parse_payload
from .config import get_settings
from .db import get_engine
from .db import schema as s
from .form.history import FormSettings


def _d(text: str) -> date:
    return date.fromisoformat(text)


def _print_report(rep) -> None:
    print(rep.summary())
    for issue in rep.issues[:30]:
        print(f"  [{issue['level']}] {issue['ref']}: {issue['message']}")
    if len(rep.issues) > 30:
        print(f"  ... {len(rep.issues) - 30} kayıt daha (import_logs tablosunda)")


def cmd_status(_args) -> None:
    eng = get_engine()
    with eng.connect() as conn:
        for t in (s.races, s.race_entries, s.race_results, s.horses, s.jockeys, s.sectional_times, s.horse_tracking_points):
            if "data_status" in t.c:
                rows = conn.execute(select(t.c.data_status, func.count()).group_by(t.c.data_status)).all()
                print(f"{t.name:24s}", ", ".join(f"{st}={n}" for st, n in rows) or "0")
            else:
                print(f"{t.name:24s}", conn.execute(select(func.count()).select_from(t)).scalar())
        rng = conn.execute(select(func.min(s.races.c.race_date), func.max(s.races.c.race_date)).where(s.races.c.data_status != "DEMO")).first()
        print("REAL koşu tarih aralığı:", rng[0], "→", rng[1])


def cmd_seed_demo(args) -> None:
    races = demo.generate(_d(args.date_from), _d(args.to), n_horses=args.horses, today_card=_d(args.today) if args.today else None)
    _print_report(Importer(get_engine()).import_races(races, demo.SOURCE, "demo-generator"))


def cmd_import_tjk_json(args) -> None:
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    races = parse_payload(payload, with_results=args.results)
    _print_report(Importer(get_engine()).import_races(races, "TJK_JSON", Path(args.file).name))


def cmd_import_tjk_html(args) -> None:
    races = parse_file(args.file, _d(args.date) if args.date else None, args.track)
    _print_report(Importer(get_engine()).import_races(races, "TJK_HTML", Path(args.file).name))


def cmd_fetch_tjk(args) -> None:
    cfg = get_settings()
    try:
        client = TjkApiClient(cfg.tjk_auth_key, cfg.tjk_api_base_url)
    except TjkAccessError as e:
        sys.exit(str(e))
    imp = Importer(get_engine())
    if args.date:
        days = [_d(args.date)]
    else:  # newest first, walking backwards (archive goal: 3 years)
        end, start = _d(args.to), _d(args.backfill_from)
        days = [end - timedelta(days=i) for i in range((end - start).days + 1)]
    for day in days:
        try:
            _print_report(imp.import_races(client.program(day), "TJK_API", f"program {day}"))
            if day < date.today():
                _print_report(imp.import_races(client.results(day), "TJK_API", f"sonuclar {day}"))
        except Exception as e:  # keep walking; report the day
            print(f"{day}: HATA {e}")


def cmd_import_accurace(args) -> None:
    recs = parse_tracking_json(json.loads(Path(args.file).read_text(encoding="utf-8")))
    _print_report(import_tracking(get_engine(), recs, Path(args.file).name))


def cmd_backtest(args) -> None:
    from .backtest.runner import run_backtest

    settings = FormSettings(mode=args.mode, days=args.days, races=args.races)
    rep = run_backtest(
        get_engine(), _d(args.date_from), _d(args.to), settings, world=args.world, mc_n=args.mc, max_races=args.max,
        progress=lambda i, n: print(f"\r{i}/{n}", end="", file=sys.stderr),
    )
    print(file=sys.stderr)
    summary = rep.summary()
    print(json.dumps(summary["overall"] if "overall" in summary else summary, indent=2, ensure_ascii=False))
    if args.json:
        Path(args.json).write_text(json.dumps({"world": args.world, "settings": rep.settings, "summary": summary}, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print("Rapor:", args.json)


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # Windows consoles default to cp1254
    p = argparse.ArgumentParser(prog="horseiq")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)

    x = sub.add_parser("seed-demo")
    x.add_argument("--from", dest="date_from", default="2024-10-01")
    x.add_argument("--to", default=(date.today() - timedelta(days=1)).isoformat())
    x.add_argument("--today", default=date.today().isoformat(), help="DEMO program (no results) for this day")
    x.add_argument("--horses", type=int, default=180)
    x.set_defaults(fn=cmd_seed_demo)

    x = sub.add_parser("import-tjk-json")
    x.add_argument("file")
    x.add_argument("--results", action="store_true", help="payload is a results (sonuçlar) payload")
    x.set_defaults(fn=cmd_import_tjk_json)

    x = sub.add_parser("import-tjk-html")
    x.add_argument("file")
    x.add_argument("--date")
    x.add_argument("--track")
    x.set_defaults(fn=cmd_import_tjk_html)

    x = sub.add_parser("fetch-tjk")
    g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--date")
    g.add_argument("--backfill-from")
    x.add_argument("--to", default=date.today().isoformat())
    x.set_defaults(fn=cmd_fetch_tjk)

    x = sub.add_parser("import-accurace")
    x.add_argument("file")
    x.set_defaults(fn=cmd_import_accurace)

    x = sub.add_parser("backtest")
    x.add_argument("--world", choices=["REAL", "DEMO"], default="REAL")
    x.add_argument("--from", dest="date_from", required=True)
    x.add_argument("--to", required=True)
    x.add_argument("--mode", choices=["days", "races"], default="days")
    x.add_argument("--days", type=int, default=400)
    x.add_argument("--races", type=int, default=3)
    x.add_argument("--mc", type=int, default=20)
    x.add_argument("--max", type=int)
    x.add_argument("--json")
    x.set_defaults(fn=cmd_backtest)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
