"""NotesReaderAgent contract tests."""

from pathlib import Path

from src.notes_reader_agent import read_notes


def test_reads_sorted_decks_and_skips_hidden(tmp_path: Path, examples: dict) -> None:
    notes = tmp_path / "notes"
    (notes / "python").mkdir(parents=True)
    (notes / ".hidden").mkdir()
    (notes / "ai.md").write_text(examples["card_generator_agent"]["notes"]["ai.md"], encoding="utf-8")
    (notes / "python" / "basics.md").write_text(
        examples["card_generator_agent"]["notes"]["python/basics.md"], encoding="utf-8"
    )
    (notes / ".hidden" / "secret.md").write_text("term :: hidden", encoding="utf-8")
    result = read_notes(notes, {})
    assert [note.deck for note in result.notes] == ["ai", "python/basics"]
    assert [note.source_file for note in result.notes] == ["ai.md", "python/basics.md"]


def test_unchanged_skipped_and_full_does_not_modify_notes(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    notes.mkdir()
    path = notes / "one.md"
    path.write_text("term :: definition", encoding="utf-8")
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    first = read_notes(notes, {})
    known = {first.notes[0].source_file: first.notes[0].content_hash}
    assert read_notes(notes, known).skipped == ("one.md",)
    assert len(read_notes(notes, known, full=True).notes) == 1
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_invalid_utf8_is_warning(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "bad.md").write_bytes(b"\xff")
    result = read_notes(notes, {})
    assert result.notes == ()
    assert result.warnings == ("bad.md: invalid UTF-8",)
