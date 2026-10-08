"""Validate access to the private Supabase flashcard database."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from dotenv import dotenv_values


REQUIRED_SETTINGS = ("SUPABASE_URL", "SUPABASE_SECRET_KEY")
TABLE_KEYS = {
    "cards": "id",
    "reviews": "id",
    "reminders_sent": "date",
    "note_files": "source_file",
}


def load_cloud_settings(env_path: str | Path) -> dict[str, str]:
    """Load only the Supabase settings from an ignored dotenv file."""

    values = dotenv_values(env_path)
    return {name: str(values.get(name) or "") for name in REQUIRED_SETTINGS}


def _connection(settings: Mapping[str, str]) -> tuple[str, str]:
    """Validate and return the private API base URL and server key."""

    if not all(settings.get(name) for name in REQUIRED_SETTINGS):
        raise ValueError("Supabase URL or secret key is missing")
    base_url = settings["SUPABASE_URL"].rstrip("/")
    if not base_url.startswith("https://"):
        raise ValueError("Supabase URL must use HTTPS")
    return base_url, settings["SUPABASE_SECRET_KEY"]


def _headers(key: str, *, prefer: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def check_cloud_storage(settings: Mapping[str, str]) -> dict[str, bool | int | str]:
    """Return a count-only Supabase health result without exposing card data."""

    base_url, key = _connection(settings)
    query = urllib.parse.urlencode({"select": "id", "limit": 1})
    request = urllib.request.Request(
        f"{base_url}/rest/v1/cards?{query}",
        headers={**_headers(key, prefer="count=exact"), "Range": "0-0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        json.load(response)
        content_range = response.headers.get("Content-Range", "")
    total_text = content_range.rsplit("/", 1)[-1] if "/" in content_range else "0"
    total = int(total_text) if total_text.isdigit() else 0
    return {"status": "passed", "database_reachable": True, "cards": total}


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    """Return JSON-safe rows from one local table without changing SQLite."""

    rows = [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY {TABLE_KEYS[table]}")]
    if table == "cards":
        for row in rows:
            row["suspended"] = bool(row["suspended"])
            row["orphaned"] = bool(row["orphaned"])
    return rows


def mirror_sqlite_to_cloud(
    db_path: str | Path,
    settings: Mapping[str, str],
    *,
    batch_size: int = 250,
) -> dict[str, int | str]:
    """Upsert local flashcard state to Supabase without deleting cloud history."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    base_url, key = _connection(settings)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        payloads = {table: _rows(conn, table) for table in TABLE_KEYS}
    finally:
        conn.close()

    counts: dict[str, int | str] = {"status": "passed"}
    for table, conflict_key in TABLE_KEYS.items():
        rows = payloads[table]
        counts[table] = len(rows)
        for offset in range(0, len(rows), batch_size):
            body = json.dumps(rows[offset : offset + batch_size], separators=(",", ":")).encode("utf-8")
            query = urllib.parse.urlencode({"on_conflict": conflict_key})
            request = urllib.request.Request(
                f"{base_url}/rest/v1/{table}?{query}",
                data=body,
                method="POST",
                headers={
                    **_headers(key, prefer="resolution=merge-duplicates,return=minimal"),
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=30):
                pass
    return counts


def main() -> int:
    """Load ignored local settings and print a secret-free health result."""

    env_path = Path(__file__).resolve().parents[1] / ".env"
    settings = load_cloud_settings(env_path)
    settings.update({name: os.environ[name] for name in REQUIRED_SETTINGS if os.environ.get(name)})
    try:
        result = check_cloud_storage(settings)
    except urllib.error.HTTPError as error:
        result = {"status": "failed", "http_status": error.code}
    except (urllib.error.URLError, json.JSONDecodeError, ValueError):
        result = {"status": "failed", "reason": "Supabase storage unavailable"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
