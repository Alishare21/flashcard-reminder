"""Load and validate local flashcard settings and SMTP credentials."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import dotenv_values
import yaml


class ConfigError(ValueError):
    """A user-facing configuration error."""


@dataclass(frozen=True)
class ParsingSettings:
    """Limits for deterministic Markdown card parsing."""

    max_front_chars: int = 300
    max_back_chars: int = 1000
    heading_mode: bool = False


@dataclass(frozen=True)
class SchedulingSettings:
    """Daily caps and maximum SM-2 interval."""

    new_cards_per_day: int = 20
    max_reviews_per_day: int = 100
    max_interval_days: int = 365


@dataclass(frozen=True)
class ReminderSettings:
    """Non-secret SMTP and message options."""

    smtp_host: str = ""
    smtp_port: int = 587
    from_email: str = ""
    to_email: str = ""
    send_when_empty: bool = False
    show_card_preview: bool = False


@dataclass(frozen=True)
class Settings:
    """Validated settings shared by all agents."""

    notes_dir: Path
    db_path: Path
    timezone: str
    parsing: ParsingSettings
    scheduling: SchedulingSettings
    reminder: ReminderSettings
    smtp_user: str = field(default="", repr=False)
    smtp_password: str = field(default="", repr=False)


def _section(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be a mapping")
    return value


def _positive(section: dict[str, object], key: str, default: int, *, allow_zero: bool = False) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if allow_zero else 1):
        raise ConfigError(f"{key} must be {'non-negative' if allow_zero else 'positive'} integer")
    return value


def _boolean(section: dict[str, object], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be true or false")
    return value


def _string(section: dict[str, object], key: str, default: str = "") -> str:
    value = section.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be text")
    return value.strip()


def load_config(path: str | Path, command: str, send: bool = False) -> Settings:
    """Return validated settings, requiring SMTP secrets only for a real send."""

    config_path = Path(path).resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read config: {config_path}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")

    base = config_path.parent
    notes_name = _string(raw, "notes_dir", "notes")
    db_name = _string(raw, "database_path", "data/cards.db")
    if not notes_name or not db_name:
        raise ConfigError("notes_dir and database_path are required")
    notes_dir = (base / notes_name).resolve()
    db_path = (base / db_name).resolve()
    if not notes_dir.is_dir():
        raise ConfigError(f"notes folder is missing: {notes_dir}")

    timezone = _string(raw, "timezone", "Asia/Kolkata")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"unknown timezone: {timezone}") from exc

    parse_raw = _section(raw, "parsing")
    schedule_raw = _section(raw, "scheduling")
    reminder_raw = _section(raw, "reminder")
    parsing = ParsingSettings(
        max_front_chars=_positive(parse_raw, "max_front_chars", 300),
        max_back_chars=_positive(parse_raw, "max_back_chars", 1000),
        heading_mode=_boolean(parse_raw, "heading_mode", False),
    )
    scheduling = SchedulingSettings(
        new_cards_per_day=_positive(schedule_raw, "new_cards_per_day", 20, allow_zero=True),
        max_reviews_per_day=_positive(schedule_raw, "max_reviews_per_day", 100, allow_zero=True),
        max_interval_days=_positive(schedule_raw, "max_interval_days", 365),
    )
    smtp_port = _positive(reminder_raw, "smtp_port", 587)
    if smtp_port > 65535:
        raise ConfigError("smtp_port must be at most 65535")
    secrets = dotenv_values(base / ".env")
    smtp_user = (secrets.get("SMTP_USER") or "").strip()
    smtp_password = secrets.get("SMTP_PASSWORD") or ""
    reminder_from = _string(reminder_raw, "from_email") or (
        secrets.get("REMINDER_FROM_EMAIL") or smtp_user
    ).strip()
    reminder_to = _string(reminder_raw, "to_email") or (
        secrets.get("REMINDER_TO_EMAIL") or smtp_user
    ).strip()
    reminder = ReminderSettings(
        smtp_host=_string(reminder_raw, "smtp_host"),
        smtp_port=smtp_port,
        from_email=reminder_from,
        to_email=reminder_to,
        send_when_empty=_boolean(reminder_raw, "send_when_empty", False),
        show_card_preview=_boolean(reminder_raw, "show_card_preview", False),
    )
    if command == "remind" and send:
        if not smtp_user or not smtp_password:
            raise ConfigError("SMTP_USER and SMTP_PASSWORD are required in .env for remind --send")
        if not reminder.smtp_host or not reminder.from_email or not reminder.to_email:
            raise ConfigError("smtp_host, from_email, and to_email are required for remind --send")
    return Settings(notes_dir, db_path, timezone, parsing, scheduling, reminder, smtp_user, smtp_password)
