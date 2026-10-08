"""Parse deterministic Markdown cards and sync them without losing progress."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
import re

from src.notes_reader_agent import NoteFile
from src.storage import connect_db, init_db


_CLOZE = re.compile(r"\{\{c(\d+)::([^{}]*)\}\}")


@dataclass(frozen=True)
class CardDraft:
    """A parsed card before it is stored in SQLite."""

    id: str
    deck: str
    type: str
    front: str
    back: str
    source_line: int


@dataclass(frozen=True)
class ParseResult:
    """Accepted cards and warnings from one note."""

    cards: tuple[CardDraft, ...]
    warnings: tuple[str, ...]
    skipped: int


@dataclass(frozen=True)
class SyncReport:
    """Counts and safe warnings from one sync run."""

    added: int
    updated: int
    unchanged: int
    orphaned: int
    skipped: int
    warnings: tuple[str, ...]


def card_id(deck: str, kind: str, front: str) -> str:
    """Make the stable 12-character card identity."""

    normalized = " ".join(front.lower().split())
    return sha1(f"{deck}|{kind}|{normalized}".encode("utf-8")).hexdigest()[:12]


def _card_line(line: str) -> str:
    text = line.lstrip()
    if text.startswith("- "):
        text = text[2:].lstrip()
    return text


def parse_note(
    text: str,
    deck: str,
    source_file: str = "<note>",
    max_front_chars: int = 300,
    max_back_chars: int = 1000,
    heading_mode: bool = False,
) -> ParseResult:
    """Parse Q/A, term, and cloze syntax outside Markdown code fences."""

    lines = text.splitlines()
    cards: list[CardDraft] = []
    warnings: list[str] = []
    seen: set[str] = set()
    skipped = 0

    def add(kind: str, front: str, back: str, line_no: int) -> None:
        nonlocal skipped
        front = front.strip()
        back = back.strip()
        reason = ""
        if not front or not back:
            reason = "empty card side"
        elif len(front) > max_front_chars:
            reason = "front too long"
        elif len(back) > max_back_chars:
            reason = "back too long"
        identity = card_id(deck, kind, front)
        if not reason and identity in seen:
            reason = "duplicate card"
        if reason:
            warnings.append(f"{source_file}:{line_no}: {reason}")
            skipped += 1
            return
        seen.add(identity)
        cards.append(CardDraft(identity, deck, kind, front, back, line_no))

    i = 0
    fenced = False
    while i < len(lines):
        raw = lines[i]
        stripped = raw.lstrip()
        if stripped.startswith("```"):
            fenced = not fenced
            i += 1
            continue
        if fenced:
            i += 1
            continue
        line = _card_line(raw)
        if line.startswith("Q:"):
            start = i + 1
            question = [line[2:].strip()]
            j = i + 1
            while j < len(lines):
                candidate = _card_line(lines[j])
                if not candidate or candidate.startswith("Q:"):
                    break
                if candidate.startswith("A:"):
                    break
                question.append(candidate.strip())
                j += 1
            if j >= len(lines) or not _card_line(lines[j]).startswith("A:"):
                warnings.append(f"{source_file}:{start}: missing answer")
                skipped += 1
                i = j
                continue
            answer = [_card_line(lines[j])[2:].strip()]
            j += 1
            answer_fence = False
            while j < len(lines):
                current = lines[j]
                current_stripped = current.lstrip()
                if not answer_fence and not current_stripped:
                    break
                if current_stripped.startswith("```"):
                    answer_fence = not answer_fence
                answer.append(current.rstrip())
                j += 1
            add("qa", "\n".join(question), "\n".join(answer), start)
            i = j
            continue
        if " :: " in line:
            front, back = line.split(" :: ", 1)
            if front.strip() and back.strip():
                add("term", front, back, i + 1)
            i += 1
            continue
        clozes = list(_CLOZE.finditer(line))
        if clozes:
            for number in dict.fromkeys(match.group(1) for match in clozes):
                front = _CLOZE.sub(lambda m: "[...]" if m.group(1) == number else m.group(2), line)
                back = _CLOZE.sub(lambda m: f"**{m.group(2)}**" if m.group(1) == number else m.group(2), line)
                add("cloze", front, back, i + 1)
            i += 1
            continue
        if heading_mode and line.startswith("## "):
            heading = line[3:].strip()
            j = i + 1
            bullets: list[str] = []
            while j < len(lines) and _card_line(lines[j]):
                bullet = lines[j].lstrip()
                if not bullet.startswith("- "):
                    break
                bullets.append(bullet[2:].strip())
                j += 1
            if bullets:
                add("qa", heading, "\n".join(bullets), i + 1)
                i = j
                continue
        i += 1
    return ParseResult(tuple(cards), tuple(warnings), skipped)


def sync_cards(
    notes: tuple[NoteFile, ...] | list[NoteFile],
    db_path: str | Path,
    today: str,
    max_front_chars: int = 300,
    max_back_chars: int = 1000,
    heading_mode: bool = False,
) -> SyncReport:
    """Store parsed cards, preserving schedules and orphaning missing reread cards."""

    init_db(db_path)
    added = updated = unchanged = orphaned = skipped = 0
    warnings: list[str] = []
    seen_across_files: set[str] = set()
    with connect_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        for note in sorted(notes, key=lambda n: n.source_file):
            parsed = parse_note(
                note.text, note.deck, note.source_file, max_front_chars, max_back_chars, heading_mode
            )
            warnings.extend(parsed.warnings)
            skipped += parsed.skipped
            present_ids: set[str] = set()
            for card in parsed.cards:
                if card.id in seen_across_files:
                    warnings.append(f"{note.source_file}:{card.source_line}: duplicate card")
                    skipped += 1
                    continue
                seen_across_files.add(card.id)
                row = conn.execute("SELECT source_file, back, orphaned FROM cards WHERE id = ?", (card.id,)).fetchone()
                if row is not None and row["source_file"] != note.source_file:
                    warnings.append(f"{note.source_file}:{card.source_line}: duplicate card")
                    skipped += 1
                    continue
                present_ids.add(card.id)
                if row is None:
                    conn.execute(
                        """INSERT INTO cards
                        (id, deck, type, front, back, source_file, source_line, due_date, created_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (card.id, card.deck, card.type, card.front, card.back, note.source_file, card.source_line, today, today),
                    )
                    added += 1
                elif row["back"] != card.back or row["orphaned"]:
                    conn.execute("UPDATE cards SET back = ?, orphaned = 0 WHERE id = ?", (card.back, card.id))
                    updated += 1
                else:
                    unchanged += 1
            old_rows = conn.execute("SELECT id FROM cards WHERE source_file = ? AND orphaned = 0", (note.source_file,))
            for row in old_rows:
                if row["id"] not in present_ids:
                    conn.execute("UPDATE cards SET orphaned = 1 WHERE id = ?", (row["id"],))
                    orphaned += 1
            old_hash = conn.execute("SELECT content_hash FROM note_files WHERE source_file = ?", (note.source_file,)).fetchone()
            if old_hash is None:
                conn.execute("INSERT INTO note_files (source_file, content_hash) VALUES (?, ?)", (note.source_file, note.content_hash))
            elif old_hash["content_hash"] != note.content_hash:
                conn.execute("UPDATE note_files SET content_hash = ? WHERE source_file = ?", (note.content_hash, note.source_file))
    return SyncReport(added, updated, unchanged, orphaned, skipped, tuple(warnings))
