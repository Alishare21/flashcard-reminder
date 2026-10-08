"""CLI end-to-end and error-code tests."""

from pathlib import Path

from src.main import main
from src.storage import connect_db


def _project(tmp_path: Path, examples: dict) -> Path:
    notes = tmp_path / "notes"
    for name, text in examples["card_generator_agent"]["notes"].items():
        path = notes / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        "notes_dir: notes\ndatabase_path: data/cards.db\ntimezone: Asia/Kolkata\n",
        encoding="utf-8",
    )
    return config


def test_sync_review_remind_dry_run_and_log(tmp_path: Path, examples: dict, monkeypatch, capsys) -> None:
    config = _project(tmp_path, examples)
    assert main(["--config", str(config), "sync"], today="2026-01-01") == 0
    assert main(["--config", str(config), "sync"], today="2026-01-01") == 0
    answers = iter(["", "3"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert main(["--config", str(config), "review", "--limit", "1"], today="2026-01-01") == 0
    assert main(["--config", str(config), "remind"], today="2026-01-01") == 0
    output = capsys.readouterr()
    assert "sync: added=7" in output.out
    assert "files_unchanged=2" in output.out
    assert "review: reviewed=1" in output.out
    assert "Flashcards due today: 6 cards (6 new, 0 review)" in output.out
    with connect_db(tmp_path / "data" / "cards.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM reminders_sent").fetchone()[0] == 0
    log = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "What is Python?" not in log
    assert "SMTP" not in log
    assert "sync: added=7" in log


def test_invalid_config_and_stats(tmp_path: Path, examples: dict, capsys) -> None:
    missing = tmp_path / "missing.yaml"
    assert main(["--config", str(missing), "sync"], today="2026-01-01") == 1
    config = _project(tmp_path, examples)
    assert main(["--config", str(config), "sync"], today="2026-01-01") == 0
    assert main(["--config", str(config), "stats"], today="2026-01-01") == 0
    assert "stats: decks=ai:2,python/basics:5" in capsys.readouterr().out


def test_web_command_starts_local_review_app(tmp_path: Path, examples: dict, monkeypatch, capsys) -> None:
    config = _project(tmp_path, examples)
    calls: list[tuple] = []
    monkeypatch.setattr("src.main.run_web_app", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert main(["--config", str(config), "web", "--port", "9123", "--no-open"], today="2026-01-01") == 0

    assert calls and calls[0][1]["port"] == 9123
    assert calls[0][1]["open_browser"] is False
    assert "web: url=http://127.0.0.1:9123" in capsys.readouterr().out
