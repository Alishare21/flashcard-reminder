"""ConfigAgent contract tests."""

from pathlib import Path

import pytest

from src.config_agent import ConfigError, load_config


def _config(tmp_path: Path, notes: bool = True) -> Path:
    if notes:
        (tmp_path / "notes").mkdir()
    path = tmp_path / "config.yaml"
    path.write_text("notes_dir: notes\ntimezone: Asia/Kolkata\n", encoding="utf-8")
    return path


def test_loads_defaults_from_example(tmp_path: Path, examples: dict) -> None:
    path = _config(tmp_path)
    settings = load_config(path, "sync")
    expected = examples["config_agent"]["valid"]
    assert settings.timezone == expected["timezone"]
    assert settings.parsing.max_front_chars == expected["max_front_chars"]
    assert settings.scheduling.max_interval_days == expected["max_interval_days"]
    assert settings.notes_dir == tmp_path / "notes"


def test_missing_notes_is_clear(tmp_path: Path, examples: dict) -> None:
    path = _config(tmp_path, notes=False)
    with pytest.raises(ConfigError, match=examples["config_agent"]["missing_notes_error"]):
        load_config(path, "sync")


def test_smtp_secrets_only_required_for_send(tmp_path: Path) -> None:
    path = _config(tmp_path)
    assert load_config(path, "remind", send=False).smtp_user == ""
    with pytest.raises(ConfigError, match="SMTP_USER"):
        load_config(path, "remind", send=True)


def test_smtp_user_defaults_sender_and_recipient(tmp_path: Path) -> None:
    path = _config(tmp_path)
    path.write_text(
        "notes_dir: notes\nreminder:\n  smtp_host: smtp.gmail.com\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "SMTP_USER=owner@example.test\nSMTP_PASSWORD=app-password\n",
        encoding="utf-8",
    )

    settings = load_config(path, "remind", send=True)

    assert settings.reminder.from_email == "owner@example.test"
    assert settings.reminder.to_email == "owner@example.test"


def test_bad_number_and_timezone(tmp_path: Path) -> None:
    path = _config(tmp_path)
    path.write_text("notes_dir: notes\ntimezone: Not/AZone\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown timezone"):
        load_config(path, "sync")
    path.write_text("notes_dir: notes\nscheduling:\n  max_interval_days: -1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="max_interval_days"):
        load_config(path, "sync")
