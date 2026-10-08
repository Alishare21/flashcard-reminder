"""Command-line entry point for syncing, reviewing, reminding, and statistics."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import logging
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.card_generator_agent import sync_cards
from src.cloud_storage_agent import load_cloud_settings, mirror_sqlite_to_cloud
from src.config_agent import ConfigError, Settings, load_config
from src.notes_reader_agent import read_notes
from src.reminder_agent import send_reminder
from src.review_agent import run_session
from src.storage import connect_db, get_known_hashes, init_db
from src.web_review_agent import run_web_app


def _mirror_cloud_if_configured(db_path: Path, env_path: Path) -> str:
    """Best-effort mirror after a successful local write; never expose secrets."""

    cloud = load_cloud_settings(env_path)
    if not any(cloud.values()):
        return "disabled"
    if not all(cloud.values()):
        return "misconfigured"
    try:
        report = mirror_sqlite_to_cloud(db_path, cloud)
    except (OSError, ValueError, sqlite3.Error):
        return "failed"
    return f"passed(cards={report['cards']},reviews={report['reviews']})"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local flashcard reminder system")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="Sync Markdown notes into SQLite")
    sync.add_argument("--full", action="store_true", help="Re-read unchanged files")
    review = commands.add_parser("review", help="Review due cards in the terminal")
    review.add_argument("--deck")
    review.add_argument("--limit", type=int)
    web = commands.add_parser("web", help="Review due cards in a local browser")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    remind = commands.add_parser("remind", help="Print or send the daily due message")
    remind.add_argument("--send", action="store_true", help="Send email instead of dry-run")
    commands.add_parser("stats", help="Show deck and review counts")
    return parser


def _logger(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("flashcard-reminder")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    return logger


def _stats(db_path: Path, today: str) -> str:
    start = (date.fromisoformat(today) - timedelta(days=29)).isoformat()
    end = (date.fromisoformat(today) + timedelta(days=6)).isoformat()
    with connect_db(db_path) as conn:
        decks = conn.execute(
            "SELECT deck, COUNT(*) AS total FROM cards WHERE orphaned = 0 GROUP BY deck ORDER BY deck"
        ).fetchall()
        reviewed = conn.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN grade IN (3, 4) THEN 1 ELSE 0 END) AS good_easy FROM reviews WHERE reviewed_at BETWEEN ? AND ?",
            (start, today),
        ).fetchone()
        due = conn.execute(
            """SELECT due_date, COUNT(*) AS total FROM cards
            WHERE suspended = 0 AND orphaned = 0 AND due_date BETWEEN ? AND ?
            GROUP BY due_date ORDER BY due_date""",
            (today, end),
        ).fetchall()
    deck_text = ",".join(f"{row['deck']}:{row['total']}" for row in decks) or "none"
    total = reviewed["total"]
    share = 0 if total == 0 else round(100 * (reviewed["good_easy"] or 0) / total, 1)
    due_map = {row["due_date"]: row["total"] for row in due}
    due_text = ",".join(
        f"{(date.fromisoformat(today) + timedelta(days=offset)).isoformat()}:{due_map.get((date.fromisoformat(today) + timedelta(days=offset)).isoformat(), 0)}"
        for offset in range(7)
    )
    return f"stats: decks={deck_text} reviews_30d={total} good_easy_pct={share} due_next7={due_text}"


def main(argv: list[str] | None = None, today: str | None = None) -> int:
    """Run one command and return 0, 1 for configuration errors, or 2 for send failure."""

    args = _parser().parse_args(argv)
    try:
        settings: Settings = load_config(args.config, args.command, getattr(args, "send", False))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1
    if args.command == "review" and args.limit is not None and args.limit < 1:
        print("config error: --limit must be positive", file=sys.stderr)
        return 1
    log = _logger(Path(args.config).resolve().parent / "logs" / "app.log")
    today = today or datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
    try:
        init_db(settings.db_path)
        if args.command == "web":
            if not 0 <= args.port <= 65535:
                raise ValueError("--port must be between 0 and 65535")
            summary = f"web: url=http://127.0.0.1:{args.port}"
            print(summary)
            log.info(summary)
            env_path = Path(args.config).resolve().parent / ".env"
            run_web_app(
                settings.db_path,
                today,
                settings,
                port=args.port,
                open_browser=not args.no_open,
                after_review=lambda: _mirror_cloud_if_configured(settings.db_path, env_path),
            )
            return 0
        if args.command == "sync":
            read = read_notes(settings.notes_dir, get_known_hashes(settings.db_path), full=args.full)
            report = sync_cards(
                read.notes,
                settings.db_path,
                today,
                settings.parsing.max_front_chars,
                settings.parsing.max_back_chars,
                settings.parsing.heading_mode,
            )
            for warning in (*read.warnings, *report.warnings):
                print(f"warning: {warning}", file=sys.stderr)
            summary = (
                f"sync: added={report.added} updated={report.updated} unchanged={report.unchanged} "
                f"orphaned={report.orphaned} skipped={report.skipped + len(read.warnings)} "
                f"files_unchanged={len(read.skipped)}"
            )
            summary += f" cloud={_mirror_cloud_if_configured(settings.db_path, Path(args.config).resolve().parent / '.env')}"
        elif args.command == "review":
            result = run_session(settings.db_path, today, settings, args.deck, args.limit)
            summary = (
                f"review: reviewed={result.reviewed} again={result.grade_counts[0]} hard={result.grade_counts[1]} "
                f"good={result.grade_counts[2]} easy={result.grade_counts[3]} still_due={result.still_due}"
            )
            summary += f" cloud={_mirror_cloud_if_configured(settings.db_path, Path(args.config).resolve().parent / '.env')}"
        elif args.command == "remind":
            result = send_reminder(settings.db_path, today, settings, send=args.send)
            summary = f"remind: status={result.status} due={result.due_total}"
            summary += f" cloud={_mirror_cloud_if_configured(settings.db_path, Path(args.config).resolve().parent / '.env')}"
        else:
            summary = _stats(settings.db_path, today)
        print(summary)
        if args.command == "stats":
            with connect_db(settings.db_path) as conn:
                deck_count = conn.execute("SELECT COUNT(DISTINCT deck) FROM cards WHERE orphaned = 0").fetchone()[0]
            log.info("stats: deck_count=%d", deck_count)
        else:
            log.info(summary)
        return 2 if args.command == "remind" and result.status == "failed" else 0
    except (OSError, sqlite3.Error, ValueError) as exc:
        summary = f"{args.command}: failed={type(exc).__name__}"
        print(summary, file=sys.stderr)
        log.info(summary)
        return 1
    finally:
        for handler in list(log.handlers):
            log.removeHandler(handler)
            handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
