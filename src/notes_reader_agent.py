"""Read changed Markdown notes without modifying the notes directory."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class NoteFile:
    """One decoded note and the metadata required for syncing."""

    source_file: str
    deck: str
    text: str
    content_hash: str


@dataclass(frozen=True)
class ReadResult:
    """Changed notes, unchanged paths, and safe warnings."""

    notes: tuple[NoteFile, ...]
    skipped: tuple[str, ...]
    warnings: tuple[str, ...]


def read_notes(notes_dir: str | Path, known_hashes: Mapping[str, str], full: bool = False) -> ReadResult:
    """Return changed UTF-8 Markdown notes in sorted path order."""

    root = Path(notes_dir)
    notes: list[NoteFile] = []
    skipped: list[str] = []
    warnings: list[str] = []
    paths = sorted(
        (p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".md"),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    for path in paths:
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        source_file = relative.as_posix()
        try:
            data = path.read_bytes()
        except OSError:
            warnings.append(f"{source_file}: cannot read file")
            continue
        digest = sha256(data).hexdigest()
        if not full and known_hashes.get(source_file) == digest:
            skipped.append(source_file)
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            warnings.append(f"{source_file}: invalid UTF-8")
            continue
        notes.append(NoteFile(source_file, relative.with_suffix("").as_posix(), text, digest))
    return ReadResult(tuple(notes), tuple(skipped), tuple(warnings))
