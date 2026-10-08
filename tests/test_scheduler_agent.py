"""SchedulerAgent exact transition and due-selection tests."""

from pathlib import Path

import pytest

from src.config_agent import SchedulingSettings
from src.notes_reader_agent import read_notes
from src.card_generator_agent import sync_cards
from src.scheduler_agent import CardState, get_due_cards, next_state
from src.storage import connect_db


def test_every_fixture_transition(examples: dict) -> None:
    settings = SchedulingSettings(max_interval_days=365)
    for case in examples["scheduler_agent"]:
        result = next_state(CardState(**case["before"]), case["grade"], case["review_date"], settings)
        assert vars(result) == case["after"]


def test_invalid_grade_and_again_preserves_ease() -> None:
    settings = SchedulingSettings()
    state = CardState(2.36, 20, 4)
    assert next_state(state, 1, "2026-01-01", settings).ease == 2.36
    with pytest.raises(ValueError, match="grade"):
        next_state(state, 5, "2026-01-01", settings)


def test_due_order_caps_and_exclusions(tmp_path: Path, examples: dict) -> None:
    root = tmp_path / "notes"
    for name, text in examples["card_generator_agent"]["notes"].items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    db = tmp_path / "cards.db"
    sync_cards(read_notes(root, {}).notes, db, "2026-01-01")
    with connect_db(db) as conn:
        conn.execute("INSERT INTO reviews (card_id, reviewed_at, grade, interval_before, interval_after, ease_before, ease_after) VALUES (?, ?, 3, 0, 1, 2.5, 2.5)", ("93f9a30d68d4", "2025-12-30"))
        conn.execute("UPDATE cards SET due_date = '2025-12-31' WHERE id = ?", ("93f9a30d68d4",))
        conn.execute("UPDATE cards SET suspended = 1 WHERE id = ?", ("0e0ef9f5c3e7",))
        conn.execute("UPDATE cards SET orphaned = 1 WHERE id = ?", ("233cc1acf0c9",))
    summary = get_due_cards(db, "2026-01-01", SchedulingSettings(new_cards_per_day=2, max_reviews_per_day=1))
    assert summary.review_count == 1 and summary.new_count == 2
    assert summary.cards[0].id == "93f9a30d68d4"
    assert summary.oldest_overdue_days == 1
    assert all(card.id not in {"0e0ef9f5c3e7", "233cc1acf0c9"} for card in summary.cards)
