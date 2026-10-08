# Flashcard Reminder System

This folder contains the local Python command-line flashcard app. Use the `flashcard-maintainer` skill in `.agents/skills/` for changes, audits, and operation of this project.

- Treat `notes/` as user-owned and read-only. Never edit, move, or delete note files.
- Preserve `data/cards.db` review history. Removed note content becomes orphaned cards; never delete cards automatically.
- Keep SMTP credentials in `.env` and never print or log them. `remind` is a dry-run unless `--send` is explicit.
- `example_data.json` was created from the pasted specification because the original fixture was absent; exact transitions in that file are the local contract.
- Run focused tests while editing; use `python -m pytest -q --basetemp .pytest_tmp` for the full suite. The basetemp path keeps temporary files within this workspace.
- The daily local runner is `scripts/run_daily.ps1`; `scripts/install_daily_task.ps1` registers it for 8:00 AM. Google Calendar is for a human reminder, not for running Python.
