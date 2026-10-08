"""Offline tests for the Supabase-backed ReminderAgent."""

from __future__ import annotations

from src import cloud_reminder_agent
from src.scheduler_agent import DueCard, DueSummary


def _settings(**overrides) -> cloud_reminder_agent.CloudReminderSettings:
    values = {
        "supabase_url": "https://fixture.supabase.co",
        "supabase_secret_key": "fixture-secret",
        "smtp_host": "smtp.example.test",
        "smtp_user": "user",
        "smtp_password": "password",
        "from_email": "from@example.test",
        "to_email": "to@example.test",
    }
    values.update(overrides)
    return cloud_reminder_agent.CloudReminderSettings(**values)


def test_select_due_matches_daily_new_and_review_quotas() -> None:
    cards = [
        {"id": "review-a", "deck": "a", "type": "qa", "front": "A", "due_date": "2025-12-30", "created_date": "2025-01-01", "suspended": False, "orphaned": False},
        {"id": "review-b", "deck": "b", "type": "qa", "front": "B", "due_date": "2026-01-01", "created_date": "2025-01-02", "suspended": False, "orphaned": False},
        {"id": "new-a", "deck": "a", "type": "term", "front": "N1", "due_date": "2026-01-01", "created_date": "2025-01-03", "suspended": False, "orphaned": False},
        {"id": "new-b", "deck": "b", "type": "term", "front": "N2", "due_date": "2026-01-01", "created_date": "2025-01-04", "suspended": False, "orphaned": False},
        {"id": "done", "deck": "b", "type": "qa", "front": "D", "due_date": "2026-01-02", "created_date": "2025-01-05", "suspended": False, "orphaned": False},
    ]
    reviews = [
        {"id": 1, "card_id": "review-a", "reviewed_at": "2025-12-01"},
        {"id": 2, "card_id": "review-b", "reviewed_at": "2025-12-01"},
        {"id": 3, "card_id": "done", "reviewed_at": "2026-01-01"},
        {"id": 4, "card_id": "review-a", "reviewed_at": "2026-01-01"},
    ]
    due = cloud_reminder_agent._select_due(
        cards,
        reviews,
        "2026-01-01",
        _settings(new_cards_per_day=2, max_reviews_per_day=2),
    )
    assert [card.id for card in due.cards] == ["review-a", "new-a"]
    assert (due.review_count, due.new_count, due.capped_review_count, due.oldest_overdue_days) == (1, 1, 1, 2)


def test_send_once_records_only_after_smtp_success(monkeypatch) -> None:
    due = DueSummary(
        (DueCard("a", "deck", "qa", "secret front", "", "2026-01-01", "2026-01-01", True),),
        new_count=1,
        review_count=0,
        capped_review_count=0,
        oldest_overdue_days=0,
    )
    sent = []
    recorded = []
    monkeypatch.setattr(cloud_reminder_agent, "get_cloud_due", lambda *_args: due)
    monkeypatch.setattr(cloud_reminder_agent, "_get_rows", lambda *_args: recorded.copy())
    monkeypatch.setattr(cloud_reminder_agent, "_post_row", lambda _settings, _table, row: recorded.append(row))

    class FakeSMTP:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

        def starttls(self) -> None:
            sent.append("tls")

        def login(self, user: str, password: str) -> None:
            assert (user, password) == ("user", "password")

        def send_message(self, message) -> None:
            assert "secret front" not in message.as_string()
            sent.append(message)

    settings = _settings()
    assert cloud_reminder_agent.send_cloud_reminder(settings, "2026-01-01", smtp_factory=FakeSMTP)["status"] == "sent"
    assert cloud_reminder_agent.send_cloud_reminder(settings, "2026-01-01", smtp_factory=FakeSMTP)["status"] == "already_sent_today"
    assert len(sent) == 2
    assert recorded == [{"date": "2026-01-01", "due_total": 1, "status": "sent"}]


def test_empty_due_skips_without_smtp(monkeypatch) -> None:
    due = DueSummary((), 0, 0, 0, 0)
    monkeypatch.setattr(cloud_reminder_agent, "get_cloud_due", lambda *_args: due)
    monkeypatch.setattr(cloud_reminder_agent, "_get_rows", lambda *_args: [])
    result = cloud_reminder_agent.send_cloud_reminder(
        _settings(smtp_user="", smtp_password=""),
        "2026-01-01",
        smtp_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("SMTP called")),
    )
    assert result == {"status": "skipped_none_due", "due_total": 0, "new": 0, "review": 0, "email_sent": False}
