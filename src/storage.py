"""SQLite schema and small shared database helpers."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator


@contextmanager
def connect_db(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Open a transactional connection and close it after the caller's block."""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(db_path: str | Path) -> None:
    """Create the database and tables without deleting existing data."""

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect_db(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id TEXT PRIMARY KEY,
                deck TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('qa', 'term', 'cloze')),
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                source_file TEXT NOT NULL,
                source_line INTEGER NOT NULL,
                ease REAL NOT NULL DEFAULT 2.5,
                interval_days INTEGER NOT NULL DEFAULT 0,
                repetitions INTEGER NOT NULL DEFAULT 0,
                due_date TEXT NOT NULL,
                created_date TEXT NOT NULL,
                last_reviewed TEXT,
                suspended INTEGER NOT NULL DEFAULT 0 CHECK (suspended IN (0, 1)),
                orphaned INTEGER NOT NULL DEFAULT 0 CHECK (orphaned IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT NOT NULL REFERENCES cards(id),
                reviewed_at TEXT NOT NULL,
                grade INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 4),
                interval_before INTEGER NOT NULL,
                interval_after INTEGER NOT NULL,
                ease_before REAL NOT NULL,
                ease_after REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reminders_sent (
                date TEXT PRIMARY KEY,
                due_total INTEGER NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS note_files (
                source_file TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(due_date);
            CREATE INDEX IF NOT EXISTS idx_reviews_card ON reviews(card_id);
            CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(reviewed_at);
            """
        )


def get_known_hashes(db_path: str | Path) -> dict[str, str]:
    """Return the last successfully synced hash for each note file."""

    with connect_db(db_path) as conn:
        return {row["source_file"]: row["content_hash"] for row in conn.execute("SELECT source_file, content_hash FROM note_files")}
