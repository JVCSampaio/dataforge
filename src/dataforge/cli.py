"""Command-line entry points.

Usage:
    python -m dataforge db-init
    python -m dataforge ingest --source all|github|csv
    python -m dataforge quality
    python -m dataforge metrics [--top N]
    python -m dataforge serve [--host H] [--port P]
"""

from __future__ import annotations

import argparse
import json
import logging

from .analytics import (
    language_share,
    monthly_event_activity,
    top_event_types,
    top_repos_by_language,
)
from .config import load_settings
from .db.migrate import init_db
from .db.session import make_session
from .ingest import run_ingest
from .quality import run_all


def _print(obj) -> None:
    print(json.dumps(obj, default=str, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="dataforge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("db-init", help="create tables")

    p_ingest = sub.add_parser("ingest", help="run ingestion")
    p_ingest.add_argument("--source", choices=["all", "github", "csv"], default="all")

    sub.add_parser("quality", help="run data quality checks")

    p_metrics = sub.add_parser("metrics", help="print analytics")
    p_metrics.add_argument("--top", type=int, default=10)

    p_serve = sub.add_parser("serve", help="run the FastAPI app")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    settings = load_settings()
    db_url = settings.database_url

    if args.cmd == "db-init":
        init_db(db_url)
        print("tables created")
        return 0

    if args.cmd == "ingest":
        session = make_session(db_url)
        try:
            results = run_ingest(session, settings, args.source)
            print(json.dumps(results, default=str))
        finally:
            session.close()
        return 0

    if args.cmd == "quality":
        session = make_session(db_url)
        try:
            _print([r.to_dict() for r in run_all(session)])
        finally:
            session.close()
        return 0

    if args.cmd == "metrics":
        session = make_session(db_url)
        try:
            _print({"top_repos": top_repos_by_language(session, args.top)})
            _print({"language_share": language_share(session)})
            _print({"monthly_events": monthly_event_activity(session)})
            _print({"event_types": top_event_types(session)})
        finally:
            session.close()
        return 0

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("dataforge.api:app", host=args.host, port=args.port, reload=False)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
