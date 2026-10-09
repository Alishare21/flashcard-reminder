"""WebReviewAgent session and transactional review tests."""

from pathlib import Path
from http.server import ThreadingHTTPServer
import json
import threading
from urllib.request import urlopen

import pytest

from src.card_generator_agent import sync_cards
from src.config_agent import SchedulingSettings
from src.notes_reader_agent import read_notes
from src.storage import connect_db
from src.web_review_agent import WEB_ROOT, _handler_class, build_session_payload, submit_review


def _db(tmp_path: Path, examples: dict) -> Path:
    notes = tmp_path / "notes"
    for name, text in examples["card_generator_agent"]["notes"].items():
        path = notes / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    db = tmp_path / "cards.db"
    sync_cards(read_notes(notes, {}).notes, db, "2026-01-01")
    return db


def test_session_payload_contains_due_cards_and_safe_counts(tmp_path: Path, examples: dict) -> None:
    db = _db(tmp_path, examples)
    payload = build_session_payload(db, "2026-01-01", SchedulingSettings())

    assert payload["total"] == 7
    assert payload["today"] == "2026-01-01"
    assert payload["new_count"] == 7
    assert payload["review_count"] == 0
    assert payload["decks"] == [{"name": "python/basics", "count": 5}, {"name": "ai", "count": 2}]
    assert set(payload["cards"][0]) == {"id", "deck", "type", "front", "back", "due_date", "is_new"}


def test_submit_review_saves_once_and_refreshes_session(tmp_path: Path, examples: dict) -> None:
    db = _db(tmp_path, examples)
    first = build_session_payload(db, "2026-01-01", SchedulingSettings())["cards"][0]

    refreshed = submit_review(db, "2026-01-01", SchedulingSettings(), first["id"], 3)

    assert refreshed["total"] == 6
    with connect_db(db) as conn:
        card = conn.execute("SELECT interval_days, due_date FROM cards WHERE id = ?", (first["id"],)).fetchone()
        reviews = conn.execute("SELECT grade FROM reviews WHERE card_id = ?", (first["id"],)).fetchall()
    assert tuple(card) == (1, "2026-01-02")
    assert [row["grade"] for row in reviews] == [3]

    with pytest.raises(ValueError, match="no longer due"):
        submit_review(db, "2026-01-01", SchedulingSettings(), first["id"], 3)
    with connect_db(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reviews WHERE card_id = ?", (first["id"],)).fetchone()[0] == 1


def test_submit_review_rejects_invalid_grade_without_writing(tmp_path: Path, examples: dict) -> None:
    db = _db(tmp_path, examples)
    first = build_session_payload(db, "2026-01-01", SchedulingSettings())["cards"][0]

    with pytest.raises(ValueError, match="grade must be"):
        submit_review(db, "2026-01-01", SchedulingSettings(), first["id"], 5)
    with connect_db(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0


def test_visual_interface_has_flip_controls_and_no_external_assets() -> None:
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "Make it stick." in html
    assert all(label in html for label in ("Again", "Hard", "Good", "Easy"))
    assert 'src="app.js"' in html and 'href="styles.css"' in html
    assert "http://" not in html and "https://" not in html
    assert 'addEventListener("keydown"' in script
    assert 'fetch("/api/review"' in script
    assert "document.createTextNode" in script and "document.createElement(\"strong\")" in script
    assert "Question & answer" in script and "Term & definition" in script and "COMPLETE THE SENTENCE" in script
    assert 'window.location.protocol === "file:"' in script
    assert "python src/main.py web" in script
    assert 'window.location.assign(localServerUrl)' in script
    assert 'window.location.hostname.endsWith("github.io")' in script
    assert "recall-public-demo-v1" in script
    assert (WEB_ROOT / "demo-cards.json").exists()


def test_local_server_serves_interface_assets_and_due_session(tmp_path: Path, examples: dict) -> None:
    db = _db(tmp_path, examples)
    handler = _handler_class(db, "2026-01-01", SchedulingSettings(), None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(f"{base}/health") as response:
            assert response.status == 200
        with urlopen(base) as response:
            assert response.status == 200
            assert b"Recall" in response.read()
        with urlopen(f"{base}/styles.css") as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "text/css"
        with urlopen(f"{base}/app.js") as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "text/javascript"
        with urlopen(f"{base}/api/session") as response:
            session = json.load(response)
        assert session["total"] == 7
        assert session["today"] == "2026-01-01"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
