"""Regression tests for transactional SQLite connection lifecycle."""

import sqlite3

import pytest

from src.storage import connect_db, init_db


def test_connection_is_closed_after_block(tmp_path):
    db_path = tmp_path / "cards.db"
    init_db(db_path)

    with connect_db(db_path) as conn:
        conn.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_connection_rolls_back_failed_review_write(tmp_path):
    db_path = tmp_path / "cards.db"
    init_db(db_path)

    with pytest.raises(RuntimeError):
        with connect_db(db_path) as conn:
            conn.execute("INSERT INTO reminders_sent(date, due_total, status) VALUES (?, ?, ?)", ("2026-01-01", 3, "sent"))
            raise RuntimeError("simulated failure")

    with connect_db(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM reminders_sent").fetchone()[0]
    assert count == 0
