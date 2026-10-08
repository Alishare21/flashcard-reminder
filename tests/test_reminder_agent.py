"""ReminderAgent message, dry-run, and SMTP idempotency tests."""

from pathlib import Path

from src.card_generator_agent import sync_cards
from src.config_agent import ParsingSettings, ReminderSettings, SchedulingSettings, Settings
from src.notes_reader_agent import read_notes
from src.reminder_agent import build_message, send_reminder
from src.scheduler_agent import DueCard, DueSummary
from src.storage import connect_db


def _settings(tmp_path: Path, db: Path, preview: bool = False) -> Settings:
    return Settings(
        tmp_path / "notes",
        db,
        "Asia/Kolkata",
        ParsingSettings(),
        SchedulingSettings(),
        ReminderSettings("smtp.example.test", 587, "from@example.test", "to@example.test", False, preview),
        "user",
        "password",
    )


def _db(tmp_path: Path, examples: dict) -> Path:
    root = tmp_path / "notes"
    for name, text in examples["card_generator_agent"]["notes"].items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    db = tmp_path / "cards.db"
    sync_cards(read_notes(root, {}).notes, db, "2026-01-01")
    return db


def test_message_matches_fixture_without_card_text(examples: dict) -> None:
    cards = (
        DueCard("a", "python/basics", "qa", "secret front a", "secret back a", "2025-12-31", "2026-01-01", False),
        DueCard("b", "python/basics", "term", "secret front b", "secret back b", "2026-01-01", "2026-01-01", True),
        DueCard("c", "ai", "qa", "secret front c", "secret back c", "2026-01-01", "2026-01-01", True),
    )
    due = DueSummary(cards, new_count=2, review_count=1, capped_review_count=0, oldest_overdue_days=1)
    expected = examples["reminder_agent"]
    message = build_message(due, expected["today"])
    assert message.subject == expected["subject"]
    assert message.body == expected["body"]
    assert "secret" not in message.subject + message.body
    preview = build_message(due, expected["today"], show_card_preview=True)
    assert preview.body.count("secret front") == 3
    assert "secret back" not in preview.body


def test_dry_run_prints_and_writes_nothing(tmp_path: Path, examples: dict, monkeypatch) -> None:
    db = _db(tmp_path, examples)
    monkeypatch.setattr("src.reminder_agent.smtplib.SMTP", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("SMTP called")))
    printed: list[str] = []
    result = send_reminder(db, "2026-01-01", _settings(tmp_path, db), output=printed.append)
    assert result.status == "dry_run_printed"
    assert printed[0] == result.subject and printed[1] == result.body
    with connect_db(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reminders_sent").fetchone()[0] == 0


def test_send_twice_sends_once(tmp_path: Path, examples: dict, monkeypatch) -> None:
    db = _db(tmp_path, examples)
    sent: list[object] = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

        def starttls(self) -> None:
            sent.append("tls")

        def login(self, user: str, password: str) -> None:
            assert (user, password) == ("user", "password")

        def send_message(self, message) -> None:
            sent.append(message)

    monkeypatch.setattr("src.reminder_agent.smtplib.SMTP", FakeSMTP)
    settings = _settings(tmp_path, db)
    assert send_reminder(db, "2026-01-01", settings, send=True).status == "sent"
    assert send_reminder(db, "2026-01-01", settings, send=True).status == "already_sent_today"
    assert len(sent) == 2
    with connect_db(db) as conn:
        assert conn.execute("SELECT due_total FROM reminders_sent WHERE date = '2026-01-01'").fetchone()[0] == 7


def test_failed_send_is_not_recorded(tmp_path: Path, examples: dict, monkeypatch) -> None:
    db = _db(tmp_path, examples)

    class FailingSMTP:
        def __init__(self, *args, **kwargs) -> None:
            raise OSError("network down")

    monkeypatch.setattr("src.reminder_agent.smtplib.SMTP", FailingSMTP)
    result = send_reminder(db, "2026-01-01", _settings(tmp_path, db), send=True)
    assert result.status == "failed"
    with connect_db(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reminders_sent").fetchone()[0] == 0
