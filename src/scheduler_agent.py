"""Pure SM-2 transitions and deterministic due-card selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math
from pathlib import Path

from src.config_agent import SchedulingSettings, Settings
from src.storage import connect_db


@dataclass(frozen=True)
class CardState:
    """The scheduling fields before or after one review."""

    ease: float
    interval_days: int
    repetitions: int
    due_date: str = ""


@dataclass(frozen=True)
class DueCard:
    """A due card selected for review or a reminder."""

    id: str
    deck: str
    type: str
    front: str
    back: str
    due_date: str
    created_date: str
    is_new: bool


@dataclass(frozen=True)
class DueSummary:
    """Ordered due cards and the daily-cap context."""

    cards: tuple[DueCard, ...]
    new_count: int
    review_count: int
    capped_review_count: int
    oldest_overdue_days: int

    @property
    def total(self) -> int:
        """Count cards selected for today."""

        return self.new_count + self.review_count

    @property
    def by_deck(self) -> tuple[tuple[str, int], ...]:
        """Return deck counts, largest first and then alphabetically."""

        counts: dict[str, int] = {}
        for card in self.cards:
            counts[card.deck] = counts.get(card.deck, 0) + 1
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _limits(settings: Settings | SchedulingSettings) -> SchedulingSettings:
    return settings.scheduling if isinstance(settings, Settings) else settings


def next_state(
    state: CardState,
    grade: int,
    review_date: str,
    settings: Settings | SchedulingSettings,
) -> CardState:
    """Calculate the exact next SM-2 state without database or clock access."""

    quality = {1: 1, 2: 3, 3: 4, 4: 5}.get(grade)
    if quality is None:
        raise ValueError("grade must be 1, 2, 3, or 4")
    limits = _limits(settings)
    if quality < 3:
        repetitions = 0
        interval_days = 1
        ease = state.ease
    else:
        repetitions = state.repetitions + 1
        if repetitions == 1:
            interval_days = 1
        elif repetitions == 2:
            interval_days = 6
        else:
            interval_days = math.floor(state.interval_days * state.ease + 0.5)
        ease = max(1.3, round(state.ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02), 2))
    interval_days = min(interval_days, limits.max_interval_days)
    due_date = (date.fromisoformat(review_date) + timedelta(days=interval_days)).isoformat()
    return CardState(ease, interval_days, repetitions, due_date)


def get_due_cards(
    db_path: str | Path,
    today: str,
    settings: Settings | SchedulingSettings,
    deck: str | None = None,
) -> DueSummary:
    """Select due reviews first, then new cards, honoring remaining daily caps."""

    limits = _limits(settings)
    deck_clause = " AND c.deck = ?" if deck is not None else ""
    params: tuple[str, ...] = (today, deck) if deck is not None else (today,)
    with connect_db(db_path) as conn:
        first_reviewed_today = conn.execute(
            """SELECT COUNT(*) FROM reviews r
            WHERE r.reviewed_at = ? AND NOT EXISTS
            (SELECT 1 FROM reviews previous WHERE previous.card_id = r.card_id AND previous.id < r.id)""",
            (today,),
        ).fetchone()[0]
        repeat_reviews_today = conn.execute(
            """SELECT COUNT(*) FROM reviews r
            WHERE r.reviewed_at = ? AND EXISTS
            (SELECT 1 FROM reviews previous WHERE previous.card_id = r.card_id AND previous.id < r.id)""",
            (today,),
        ).fetchone()[0]
        review_rows = conn.execute(
            f"""SELECT c.* FROM cards c
            WHERE c.suspended = 0 AND c.orphaned = 0 AND c.due_date <= ?{deck_clause}
            AND EXISTS (SELECT 1 FROM reviews r WHERE r.card_id = c.id)
            ORDER BY c.due_date, c.created_date, c.id""",
            params,
        ).fetchall()
        new_rows = conn.execute(
            f"""SELECT c.* FROM cards c
            WHERE c.suspended = 0 AND c.orphaned = 0{deck_clause}
            AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.card_id = c.id)
            ORDER BY c.created_date, c.deck, c.id""",
            (deck,) if deck is not None else (),
        ).fetchall()
    review_quota = max(0, limits.max_reviews_per_day - repeat_reviews_today)
    new_quota = max(0, limits.new_cards_per_day - first_reviewed_today)
    chosen_review = review_rows[:review_quota]
    chosen_new = new_rows[:new_quota]
    cards = tuple(
        DueCard(row["id"], row["deck"], row["type"], row["front"], row["back"], row["due_date"], row["created_date"], is_new)
        for is_new, rows in ((False, chosen_review), (True, chosen_new))
        for row in rows
    )
    overdue = [date.fromisoformat(today) - date.fromisoformat(row["due_date"]) for row in review_rows if row["due_date"] < today]
    oldest_overdue_days = max((days.days for days in overdue), default=0)
    return DueSummary(cards, len(chosen_new), len(chosen_review), len(review_rows) - len(chosen_review), oldest_overdue_days)
