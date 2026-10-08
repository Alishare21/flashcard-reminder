"""CardGeneratorAgent parsing and persistence tests."""

from pathlib import Path

from src.card_generator_agent import parse_note, sync_cards
from src.notes_reader_agent import read_notes
from src.storage import connect_db, get_known_hashes


def _sample_notes(tmp_path: Path, examples: dict) -> Path:
    root = tmp_path / "notes"
    for name, text in examples["card_generator_agent"]["notes"].items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_sample_notes_match_seven_cards_and_one_warning(examples: dict) -> None:
    sample = examples["card_generator_agent"]
    cards = []
    warnings = []
    for name, text in sample["notes"].items():
        result = parse_note(text, Path(name).with_suffix("").as_posix(), name)
        cards.extend(result.cards)
        warnings.extend(result.warnings)
    assert len(cards) == 7
    assert warnings == sample["warnings"]
    assert [vars(card) for card in cards] == [
        {**expected, "source_line": expected["source_line"]} for expected in sample["expected_cards"]
    ]


def test_fence_and_limits_and_duplicate_warning() -> None:
    text = """```python
Q: hidden
A: not a card
```
Q: code answer
A:
```python
term :: inside answer
```

term :: definition
term :: changed definition
Q: missing

"""
    result = parse_note(text, "deck", "deck.md")
    assert len(result.cards) == 2
    assert "term :: inside answer" in result.cards[0].back
    assert any("duplicate card" in warning for warning in result.warnings)
    assert any("missing answer" in warning for warning in result.warnings)
    limited = parse_note("long front :: short", "deck", "deck.md", max_front_chars=5)
    assert limited.cards == ()
    assert "front too long" in limited.warnings[0]


def test_sync_idempotence_edit_and_orphan(tmp_path: Path, examples: dict) -> None:
    root = _sample_notes(tmp_path, examples)
    db = tmp_path / "data" / "cards.db"
    first_notes = read_notes(root, {}).notes
    first = sync_cards(first_notes, db, "2026-01-01")
    assert first.added == 7 and first.skipped == 1
    before = db.read_bytes()
    unchanged_notes = read_notes(root, get_known_hashes(db)).notes
    assert unchanged_notes == ()
    assert sync_cards(unchanged_notes, db, "2026-01-01").added == 0
    assert db.read_bytes() == before

    with connect_db(db) as conn:
        conn.execute("UPDATE cards SET ease = 2.6, interval_days = 15, repetitions = 3 WHERE id = ?", ("93f9a30d68d4",))
    path = root / "python" / "basics.md"
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace("A programming language.", "A general-purpose language."), encoding="utf-8")
    edit_notes = read_notes(root, get_known_hashes(db)).notes
    edit = sync_cards(edit_notes, db, "2026-01-02")
    assert edit.updated == 1
    with connect_db(db) as conn:
        row = conn.execute("SELECT back, ease, interval_days, repetitions FROM cards WHERE id = ?", ("93f9a30d68d4",)).fetchone()
        assert tuple(row) == ("A general-purpose language.", 2.6, 15, 3)

    path.write_text(path.read_text(encoding="utf-8").replace("immutable :: unable to change after creation\n\n", ""), encoding="utf-8")
    orphan = sync_cards(read_notes(root, get_known_hashes(db)).notes, db, "2026-01-03")
    assert orphan.orphaned == 1
    with connect_db(db) as conn:
        assert conn.execute("SELECT orphaned FROM cards WHERE id = ?", ("378c26610f53",)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 7
