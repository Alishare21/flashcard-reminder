"""Offline tests for the count-only Supabase storage agent."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sqlite3

import pytest

from src import cloud_storage_agent


SETTINGS = {"SUPABASE_URL": "https://fixture.supabase.co", "SUPABASE_SECRET_KEY": "fixture-secret"}


class FakeResponse(io.BytesIO):
    """Small urllib response fixture with headers and context management."""

    def __init__(self, body: bytes, content_range: str) -> None:
        super().__init__(body)
        self.headers = {"Content-Range": content_range}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def test_check_cloud_storage_returns_count_without_secret(monkeypatch) -> None:
    def fake_open(request, timeout):
        assert timeout == 20
        assert request.get_header("Apikey") == "fixture-secret"
        return FakeResponse(json.dumps([{"id": "card-id"}]).encode(), "0-0/7")

    monkeypatch.setattr(cloud_storage_agent.urllib.request, "urlopen", fake_open)
    result = cloud_storage_agent.check_cloud_storage(SETTINGS)
    assert result == {"status": "passed", "database_reachable": True, "cards": 7}
    assert "fixture-secret" not in str(result)


def test_check_cloud_storage_rejects_missing_or_insecure_settings(monkeypatch) -> None:
    monkeypatch.setattr(cloud_storage_agent.urllib.request, "urlopen", lambda *_args: pytest.fail("network used"))
    with pytest.raises(ValueError, match="missing"):
        cloud_storage_agent.check_cloud_storage({})
    with pytest.raises(ValueError, match="HTTPS"):
        cloud_storage_agent.check_cloud_storage({**SETTINGS, "SUPABASE_URL": "http://fixture.invalid"})


def test_mirror_upserts_rows_without_deleting_or_exposing_secret(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "cards.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE cards (id TEXT PRIMARY KEY, deck TEXT, type TEXT, front TEXT, back TEXT,
          source_file TEXT, source_line INTEGER, ease REAL, interval_days INTEGER, repetitions INTEGER,
          due_date TEXT, created_date TEXT, last_reviewed TEXT, suspended INTEGER, orphaned INTEGER);
        CREATE TABLE reviews (id INTEGER PRIMARY KEY, card_id TEXT, reviewed_at TEXT, grade INTEGER,
          interval_before INTEGER, interval_after INTEGER, ease_before REAL, ease_after REAL);
        CREATE TABLE reminders_sent (date TEXT PRIMARY KEY, due_total INTEGER, status TEXT);
        CREATE TABLE note_files (source_file TEXT PRIMARY KEY, content_hash TEXT);
        INSERT INTO cards VALUES ('card-1', 'deck', 'qa', 'front', 'back', 'one.md', 1, 2.5, 0, 0,
          '2026-01-01', '2026-01-01', NULL, 0, 0);
        INSERT INTO note_files VALUES ('one.md', 'hash');
        """
    )
    conn.commit()
    conn.close()
    requests = []

    def fake_open(request, timeout):
        assert timeout == 30
        requests.append(request)
        return FakeResponse(b"", "")

    monkeypatch.setattr(cloud_storage_agent.urllib.request, "urlopen", fake_open)
    result = cloud_storage_agent.mirror_sqlite_to_cloud(db, SETTINGS)
    assert result == {"status": "passed", "cards": 1, "reviews": 0, "reminders_sent": 0, "note_files": 1}
    assert [request.full_url.split("/")[-1].split("?")[0] for request in requests] == ["cards", "note_files"]
    card_payload = json.loads(requests[0].data)
    assert card_payload[0]["suspended"] is False and card_payload[0]["orphaned"] is False
    assert all(request.method == "POST" for request in requests)
    assert "fixture-secret" not in str(result)


def test_mirror_rejects_invalid_batch_before_network(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cloud_storage_agent.urllib.request, "urlopen", lambda *_args: pytest.fail("network used"))
    with pytest.raises(ValueError, match="positive"):
        cloud_storage_agent.mirror_sqlite_to_cloud(tmp_path / "missing.db", SETTINGS, batch_size=0)
