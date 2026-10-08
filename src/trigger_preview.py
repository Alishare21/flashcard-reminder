"""Run the real flashcard agents against synthetic fixtures for Trigger.dev preview."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.card_generator_agent import parse_note, sync_cards
from src.config_agent import SchedulingSettings
from src.notes_reader_agent import read_notes
from src.reminder_agent import build_message
from src.scheduler_agent import CardState, get_due_cards, next_state
from src.storage import init_db


def preview(fixture: dict[str, object]) -> dict[str, object]:
    """Return counts and checks only; never include card text or secrets."""

    card_fixture = fixture["card_generator_agent"]
    assert isinstance(card_fixture, dict)
    notes = card_fixture["notes"]
    assert isinstance(notes, dict)
    with TemporaryDirectory(prefix="flashcard-preview-", dir=Path.cwd()) as temp:
        root = Path(temp)
        notes_dir = root / "notes"
        notes_dir.mkdir()
        for name, body in notes.items():
            assert isinstance(name, str) and isinstance(body, str)
            target = notes_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        db_path = root / "cards.db"
        init_db(db_path)
        read = read_notes(notes_dir, {}, full=True)
        report = sync_cards(read.notes, db_path, "2026-01-01")
        if report.added != len(card_fixture["expected_cards"]):
            raise AssertionError("card count mismatch")
        if len(report.warnings) != len(card_fixture["warnings"]):
            raise AssertionError("warning count mismatch")
        parsed = sum(len(parse_note(note.text, note.deck).cards) for note in read.notes)
        if parsed != report.added:
            raise AssertionError("parse/sync mismatch")
        transitions = fixture["scheduler_agent"]
        assert isinstance(transitions, list)
        for example in transitions:
            before = example["before"]
            after = example["after"]
            actual = next_state(
                CardState(before["ease"], before["interval_days"], before["repetitions"]),
                example["grade"],
                example["review_date"],
                SchedulingSettings(),
            )
            if (actual.ease, actual.interval_days, actual.repetitions, actual.due_date) != (
                after["ease"], after["interval_days"], after["repetitions"], after["due_date"]
            ):
                raise AssertionError("SM-2 transition mismatch")
        due = get_due_cards(db_path, date(2026, 1, 1).isoformat(), SchedulingSettings())
        message = build_message(due, "2026-01-01")
        return {
            "status": "passed",
            "cards_added": report.added,
            "warnings": len(report.warnings),
            "scheduler_transitions_checked": len(transitions),
            "cards_due": due.total,
            "reminder_subject": message.subject,
            "email_sent": False,
        }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("fixture argument required")
    print(json.dumps(preview(json.loads(sys.argv[1]))))
