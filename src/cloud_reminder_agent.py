"""Build and send the daily reminder from the private Supabase mirror."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
import json
import os
from pathlib import Path
import smtplib
import sys
from typing import Any, Callable, Mapping
import urllib.parse
import urllib.request

from dotenv import dotenv_values

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cloud_storage_agent import _connection, _headers
from src.reminder_agent import build_message
from src.scheduler_agent import DueCard, DueSummary


@dataclass(frozen=True)
class CloudReminderSettings:
    """Cloud scheduling and SMTP settings loaded from secret environment variables."""

    supabase_url: str
    supabase_secret_key: str
    new_cards_per_day: int = 20
    max_reviews_per_day: int = 100
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = ""
    to_email: str = ""
    send_when_empty: bool = False
    show_card_preview: bool = False

    @property
    def cloud(self) -> dict[str, str]:
        """Return the narrow mapping accepted by the shared Supabase helper."""

        return {"SUPABASE_URL": self.supabase_url, "SUPABASE_SECRET_KEY": self.supabase_secret_key}


def _get_rows(settings: CloudReminderSettings, table: str, query: Mapping[str, str]) -> list[dict[str, Any]]:
    """Read every matching Supabase row in bounded pages."""

    base_url, key = _connection(settings.cloud)
    rows: list[dict[str, Any]] = []
    page_size = 1000
    while True:
        start = len(rows)
        request = urllib.request.Request(
            f"{base_url}/rest/v1/{table}?{urllib.parse.urlencode(query)}",
            headers={**_headers(key), "Range": f"{start}-{start + page_size - 1}"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            page = json.load(response)
        if not isinstance(page, list):
            raise ValueError("Supabase returned an invalid row set")
        rows.extend(page)
        if len(page) < page_size:
            return rows


def _post_row(settings: CloudReminderSettings, table: str, row: Mapping[str, Any]) -> None:
    """Insert one backend-only row after an external action succeeds."""

    base_url, key = _connection(settings.cloud)
    request = urllib.request.Request(
        f"{base_url}/rest/v1/{table}",
        data=json.dumps(row, separators=(",", ":")).encode("utf-8"),
        method="POST",
        headers={**_headers(key, prefer="return=minimal"), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30):
        pass


def _select_due(
    cards: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    today: str,
    settings: CloudReminderSettings,
) -> DueSummary:
    """Apply the same deterministic daily caps as the local SchedulerAgent."""

    reviews = sorted(reviews, key=lambda row: int(row["id"]))
    first_review_id: dict[str, int] = {}
    for row in reviews:
        first_review_id.setdefault(str(row["card_id"]), int(row["id"]))
    reviewed_ids = set(first_review_id)
    first_reviewed_today = sum(
        1
        for row in reviews
        if row["reviewed_at"] == today and first_review_id[str(row["card_id"])] == int(row["id"])
    )
    repeat_reviews_today = sum(
        1
        for row in reviews
        if row["reviewed_at"] == today and first_review_id[str(row["card_id"])] != int(row["id"])
    )
    eligible = [row for row in cards if not row.get("suspended") and not row.get("orphaned")]
    review_rows = sorted(
        (row for row in eligible if row["id"] in reviewed_ids and row["due_date"] <= today),
        key=lambda row: (row["due_date"], row["created_date"], row["id"]),
    )
    new_rows = sorted(
        (row for row in eligible if row["id"] not in reviewed_ids),
        key=lambda row: (row["created_date"], row["deck"], row["id"]),
    )
    review_quota = max(0, settings.max_reviews_per_day - repeat_reviews_today)
    new_quota = max(0, settings.new_cards_per_day - first_reviewed_today)
    chosen_review = review_rows[:review_quota]
    chosen_new = new_rows[:new_quota]
    due_cards = tuple(
        DueCard(
            str(row["id"]),
            str(row["deck"]),
            str(row.get("type") or "qa"),
            str(row.get("front") or ""),
            "",
            str(row["due_date"]),
            str(row["created_date"]),
            is_new,
        )
        for is_new, selected in ((False, chosen_review), (True, chosen_new))
        for row in selected
    )
    overdue_days = [
        (date.fromisoformat(today) - date.fromisoformat(str(row["due_date"]))).days
        for row in review_rows
        if row["due_date"] < today
    ]
    return DueSummary(
        due_cards,
        len(chosen_new),
        len(chosen_review),
        len(review_rows) - len(chosen_review),
        max(overdue_days, default=0),
    )


def get_cloud_due(settings: CloudReminderSettings, today: str) -> DueSummary:
    """Read private cloud state and return today's ordered due-card summary."""

    cards = _get_rows(
        settings,
        "cards",
        {
            "select": "id,deck,type,front,due_date,created_date,suspended,orphaned",
            "suspended": "eq.false",
            "orphaned": "eq.false",
        },
    )
    reviews = _get_rows(settings, "reviews", {"select": "id,card_id,reviewed_at", "order": "id.asc"})
    return _select_due(cards, reviews, today, settings)


def send_cloud_reminder(
    settings: CloudReminderSettings,
    today: str,
    *,
    send: bool = True,
    smtp_factory: Callable[..., Any] = smtplib.SMTP,
) -> dict[str, Any]:
    """Send at most once for a date and return a card-text-free result."""

    due = get_cloud_due(settings, today)
    message = build_message(due, today, settings.show_card_preview)
    if not send:
        return {
            "status": "dry_run_printed",
            "due_total": due.total,
            "new": due.new_count,
            "review": due.review_count,
            "email_sent": False,
        }
    already = _get_rows(settings, "reminders_sent", {"select": "date", "date": f"eq.{today}", "limit": "1"})
    if already:
        return {
            "status": "already_sent_today",
            "due_total": due.total,
            "new": due.new_count,
            "review": due.review_count,
            "email_sent": False,
        }
    if due.total == 0 and due.capped_review_count == 0 and not settings.send_when_empty:
        return {
            "status": "skipped_none_due",
            "due_total": 0,
            "new": 0,
            "review": 0,
            "email_sent": False,
        }
    if not all((settings.smtp_host, settings.smtp_user, settings.smtp_password, settings.from_email, settings.to_email)):
        return {
            "status": "failed",
            "reason": "SMTP settings are incomplete",
            "due_total": due.total,
            "new": due.new_count,
            "review": due.review_count,
            "email_sent": False,
        }
    email = EmailMessage()
    email["Subject"] = message.subject
    email["From"] = settings.from_email
    email["To"] = settings.to_email
    email.set_content(message.body)
    try:
        with smtp_factory(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(email)
    except Exception:
        return {
            "status": "failed",
            "reason": "SMTP send failed",
            "due_total": due.total,
            "new": due.new_count,
            "review": due.review_count,
            "email_sent": False,
        }
    _post_row(settings, "reminders_sent", {"date": today, "due_total": due.total, "status": "sent"})
    return {
        "status": "sent",
        "due_total": due.total,
        "new": due.new_count,
        "review": due.review_count,
        "email_sent": True,
    }


def _bool(value: str | None, default: bool = False) -> bool:
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def _load_settings() -> CloudReminderSettings:
    """Load local dotenv values with Trigger.dev environment overrides."""

    env_path = Path(__file__).resolve().parents[1] / ".env"
    values = {key: str(value or "") for key, value in dotenv_values(env_path).items()}
    values.update(os.environ)
    return CloudReminderSettings(
        values.get("SUPABASE_URL", ""),
        values.get("SUPABASE_SECRET_KEY", ""),
        int(values.get("NEW_CARDS_PER_DAY", "20")),
        int(values.get("MAX_REVIEWS_PER_DAY", "100")),
        values.get("SMTP_HOST", "smtp.gmail.com"),
        int(values.get("SMTP_PORT", "587")),
        values.get("SMTP_USER", ""),
        values.get("SMTP_PASSWORD", ""),
        values.get("REMINDER_FROM_EMAIL", "") or values.get("SMTP_USER", ""),
        values.get("REMINDER_TO_EMAIL", "") or values.get("SMTP_USER", ""),
        _bool(values.get("SEND_WHEN_EMPTY")),
        _bool(values.get("SHOW_CARD_PREVIEW")),
    )


def main(argv: list[str] | None = None) -> int:
    """Run one Trigger.dev invocation using an explicit testable date."""

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(json.dumps({"status": "failed", "reason": "today is required"}))
        return 1
    try:
        date.fromisoformat(args[0])
        result = send_cloud_reminder(_load_settings(), args[0], send="--send" in args)
    except (OSError, ValueError, json.JSONDecodeError):
        result = {"status": "failed", "reason": "cloud reminder unavailable", "email_sent": False}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] not in {"failed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
