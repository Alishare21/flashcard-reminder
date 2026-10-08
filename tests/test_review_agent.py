"""ReviewAgent save-on-every-card and graceful-quit tests."""

from pathlib import Path

from src.card_generator_agent import sync_cards
from src.config_agent import SchedulingSettings
from src.notes_reader_agent import read_notes
from src.review_agent import run_session
from src.storage import connect_db


class FakeIO:
    def __init__(self, answers: list[str | BaseException]) -> None:
        self.answers = iter(answers)
        self.messages: list[str] = []

    def ask(self, prompt: str) -> str:
        self.messages.append(prompt)
        answer = next(self.answers)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def say(self, message: str) -> None:
        self.messages.append(message)


def _db(tmp_path: Path, examples: dict) -> Path:
    root = tmp_path / "notes"
    for name, text in examples["card_generator_agent"]["notes"].items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    db = tmp_path / "cards.db"
    sync_cards(read_notes(root, {}).notes, db, "2026-01-01")
    return db


def test_good_again_then_q_saves_exactly_two(tmp_path: Path, examples: dict) -> None:
    db = _db(tmp_path, examples)
    io = FakeIO(["", "3", "", "1", "q"])
    summary = run_session(db, "2026-01-01", SchedulingSettings(), io=io)
    assert summary.reviewed == 2
    assert summary.grade_counts == (1, 0, 1, 0)
    assert summary.quit_early
    with connect_db(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 2
        rows = conn.execute("SELECT grade, interval_after FROM reviews ORDER BY id").fetchall()
        assert [tuple(row) for row in rows] == [(3, 1), (1, 1)]


def test_ctrl_c_after_one_review_keeps_progress(tmp_path: Path, examples: dict) -> None:
    db = _db(tmp_path, examples)
    io = FakeIO(["", "invalid", "4", KeyboardInterrupt()])
    summary = run_session(db, "2026-01-01", SchedulingSettings(), io=io)
    assert summary.reviewed == 1 and summary.quit_early
    assert any("Enter 1, 2, 3, 4" in message for message in io.messages)
    with connect_db(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1
