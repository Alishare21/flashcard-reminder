"""Run a terminal review session and commit each answer independently."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.config_agent import SchedulingSettings, Settings
from src.scheduler_agent import CardState, get_due_cards, next_state
from src.storage import connect_db


class ReviewIO(Protocol):
    """Replaceable terminal input and output contract."""

    def ask(self, prompt: str) -> str:
        """Read one answer from the user."""

    def say(self, message: str) -> None:
        """Display one message to the user."""


class TerminalIO:
    """Default interactive terminal adapter."""

    def ask(self, prompt: str) -> str:
        """Read from standard input."""

        return input(prompt)

    def say(self, message: str) -> None:
        """Write to standard output."""

        print(message)


default_io = TerminalIO()


@dataclass(frozen=True)
class SessionSummary:
    """Review counts safe to print and log."""

    reviewed: int
    grade_counts: tuple[int, int, int, int]
    still_due: int
    quit_early: bool


def save_review(db_path: str | Path, card_id: str, grade: int, today: str, settings: Settings | SchedulingSettings) -> None:
    """Atomically update one card and append its review history row."""

    with connect_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT ease, interval_days, repetitions FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            raise ValueError(f"card not found: {card_id}")
        before = CardState(row["ease"], row["interval_days"], row["repetitions"])
        after = next_state(before, grade, today, settings)
        conn.execute(
            """UPDATE cards SET ease = ?, interval_days = ?, repetitions = ?, due_date = ?, last_reviewed = ? WHERE id = ?""",
            (after.ease, after.interval_days, after.repetitions, after.due_date, today, card_id),
        )
        conn.execute(
            """INSERT INTO reviews
            (card_id, reviewed_at, grade, interval_before, interval_after, ease_before, ease_after)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (card_id, today, grade, before.interval_days, after.interval_days, before.ease, after.ease),
        )


# Kept for compatibility with callers from earlier project versions.
_save_review = save_review


def run_session(
    db_path: str | Path,
    today: str,
    settings: Settings | SchedulingSettings,
    deck: str | None = None,
    limit: int | None = None,
    io: ReviewIO = default_io,
) -> SessionSummary:
    """Review due cards in order and retain progress on quit or Ctrl+C."""

    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    due = get_due_cards(db_path, today, settings, deck)
    cards = due.cards[:limit] if limit is not None else due.cards
    grades = [0, 0, 0, 0]
    quit_early = False
    for card in cards:
        try:
            io.say(f"\n[{card.deck}] {card.front}")
            reveal = io.ask("Press Enter to show answer (q to quit): ").strip().lower()
            if reveal == "q":
                quit_early = True
                break
            io.say(card.back)
            while True:
                answer = io.ask("1 Again, 2 Hard, 3 Good, 4 Easy (q to quit): ").strip().lower()
                if answer == "q":
                    quit_early = True
                    break
                if answer in {"1", "2", "3", "4"}:
                    grade = int(answer)
                    save_review(db_path, card.id, grade, today, settings)
                    grades[grade - 1] += 1
                    break
                io.say("Enter 1, 2, 3, 4, or q.")
            if quit_early:
                break
        except (KeyboardInterrupt, EOFError):
            quit_early = True
            io.say("\nReview stopped.")
            break
    remaining = get_due_cards(db_path, today, settings, deck).total
    return SessionSummary(sum(grades), tuple(grades), remaining, quit_early)
