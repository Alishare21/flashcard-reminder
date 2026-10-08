"""Build and optionally send one daily count-only email reminder."""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
import smtplib
from typing import Callable

from src.config_agent import Settings
from src.scheduler_agent import DueSummary, get_due_cards
from src.storage import connect_db


@dataclass(frozen=True)
class ReminderMessage:
    """Plain-text reminder content."""

    subject: str
    body: str


@dataclass(frozen=True)
class ReminderResult:
    """Reminder content and send status."""

    subject: str
    body: str
    status: str
    due_total: int


def build_message(due_summary: DueSummary, today: str, show_card_preview: bool = False) -> ReminderMessage:
    """Build the count-only daily message, with optional three-card preview."""

    subject = (
        f"Flashcards due today: {due_summary.total} cards "
        f"({due_summary.new_count} new, {due_summary.review_count} review)"
    )
    lines = [f"Date: {today}", "Due by deck:"]
    if due_summary.by_deck:
        lines.extend(f"- {deck}: {count}" for deck, count in due_summary.by_deck)
    else:
        lines.append("- none: 0")
    days = due_summary.oldest_overdue_days
    lines.append(f"Oldest overdue: {days} {'day' if days == 1 else 'days'}")
    if due_summary.capped_review_count:
        lines.append(f"Review cap reached: {due_summary.capped_review_count} additional review cards deferred today")
    lines.append("Start reviewing: python src/main.py review")
    if show_card_preview:
        lines.append("Card preview:")
        lines.extend(f"- {card.front}" for card in due_summary.cards[:3])
    return ReminderMessage(subject, "\n".join(lines))


def send_reminder(
    db_path: str | Path,
    today: str,
    settings: Settings,
    send: bool = False,
    output: Callable[[str], None] = print,
) -> ReminderResult:
    """Print a dry run or send once using TLS; record only successful sends."""

    due = get_due_cards(db_path, today, settings)
    message = build_message(due, today, settings.reminder.show_card_preview)
    if not send:
        if due.total == 0 and due.capped_review_count == 0 and not settings.reminder.send_when_empty:
            return ReminderResult(message.subject, message.body, "skipped_none_due", due.total)
        output(message.subject)
        output(message.body)
        return ReminderResult(message.subject, message.body, "dry_run_printed", due.total)

    with connect_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        already = conn.execute("SELECT 1 FROM reminders_sent WHERE date = ?", (today,)).fetchone()
        if already:
            conn.rollback()
            return ReminderResult(message.subject, message.body, "already_sent_today", due.total)
        if due.total == 0 and due.capped_review_count == 0 and not settings.reminder.send_when_empty:
            conn.rollback()
            return ReminderResult(message.subject, message.body, "skipped_none_due", due.total)
        email = EmailMessage()
        email["Subject"] = message.subject
        email["From"] = settings.reminder.from_email
        email["To"] = settings.reminder.to_email
        email.set_content(message.body)
        try:
            with smtplib.SMTP(settings.reminder.smtp_host, settings.reminder.smtp_port, timeout=20) as smtp:
                smtp.starttls()
                smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(email)
        except Exception:
            conn.rollback()
            return ReminderResult(message.subject, message.body, "failed", due.total)
        conn.execute(
            "INSERT INTO reminders_sent (date, due_total, status) VALUES (?, ?, 'sent')",
            (today, due.total),
        )
        return ReminderResult(message.subject, message.body, "sent", due.total)
