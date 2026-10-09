# Flashcard Reminder System

A local-first flashcard application that converts Markdown notes into visual study cards, schedules reviews with the deterministic SM-2 spaced-repetition algorithm, supports browser and terminal review sessions, and sends daily email reminders. Review history stays in SQLite and is mirrored to a private Supabase database so Trigger.dev can run the reminder every day without Codex or the local computer.

**Live public reminder dashboard:** [Open Recall Reminders](https://alishare21.github.io/flashcard-reminder/)

The public page displays reminder status in a flashcard, shows “You're all caught up” when appropriate, and lets each visitor choose a reminder name, time, and daily, weekday, or weekly repeat rule. It previews the next three occurrences in the visitor's timezone. Separate buttons open a prefilled Google Calendar event and the visitor's Calendar for sign-in and checking saved events. The page does not read events back from Google. Settings stay in the visitor's browser. Personal notes, flashcard text, review history, email settings, calendar data, and cloud credentials remain private. The full flashcard reviewer continues to run locally.

## What the project does

1. Recursively reads Markdown files from `notes/` without modifying them.
2. Generates question-and-answer, term-definition, and cloze flashcards.
3. Stores cards, schedules, reviews, and reminder history in SQLite.
4. Selects new and due cards using daily limits and exact SM-2 scheduling.
5. Runs a polished local browser review with flip cards, progress, keyboard shortcuts, and Again, Hard, Good, and Easy grades.
6. Builds count-only reminders and sends them through Gmail SMTP when `--send` is explicit.
7. Mirrors local state to Supabase and runs a production reminder through Trigger.dev at 8:00 AM India time.

## Architecture

```text
notes/*.md
    |
    v
NotesReaderAgent -> CardGeneratorAgent -> SQLite data/cards.db
                                              |
                              +---------------+---------------+
                              |                               |
                              v                               v
            WebReviewAgent / ReviewAgent <-> SchedulerAgent      ReminderAgent
                              |                               |
                              +----------> Supabase <---------+
                                               |
                                               v
                                  Trigger.dev daily reminder
```

`src/main.py` provides the `sync`, `web`, `review`, `remind`, and `stats` commands. Each agent has one main responsibility and a replaceable, testable input/output contract.

## Technology stack

| Area | Technology | Purpose |
|---|---|---|
| Language | Python 3.10+ | CLI, parsing, scheduling, reviews, SMTP, and storage |
| Visual interface | HTML, CSS, and vanilla JavaScript | Local flip cards, responsive layout, progress, and keyboard controls |
| Local web server | Python `http.server` | Private loopback API and static interface with no extra dependency |
| Local database | SQLite | Durable cards, review history, and reminder records |
| Configuration | PyYAML and python-dotenv | Non-secret settings in YAML and secrets in `.env` |
| Testing | pytest | Deterministic unit and end-to-end tests |
| Cloud database | Supabase PostgreSQL and REST API | Private cloud mirror for scheduled reminders |
| Automation | Trigger.dev with TypeScript | Production daily task at 8:00 AM India time |
| Email | Gmail SMTP with STARTTLS | Daily cards-due messages |
| Local automation | Windows Task Scheduler / PowerShell | Local fallback that runs without Codex |
| Source control | Git and GitHub | Public portfolio repository for review and version history |
| Public deployment | GitHub Pages and GitHub Actions | Live responsive reminder dashboard with browser-only settings |
| Calendar handoff | Google Calendar event template | Custom daily, weekday, or weekly reminder without calendar credentials |

No AI model is used to generate cards. Parsing and scheduling are local and deterministic.

## Supported note formats

Place UTF-8 Markdown files anywhere under `notes/`. A nested path becomes the deck name; for example, `notes/python/basics.md` becomes `python/basics`.

### Question and answer

```markdown
Q: What does a Python list store?
A: An ordered, mutable collection of values.
```

### Term and definition

```markdown
gradient descent :: an optimization method that minimizes a loss function
```

### Cloze deletion

```markdown
The activation function in a hidden layer can be {{c1::ReLU}}.
```

For cloze notes, each distinct `c1`, `c2`, and later number produces one card. Lines inside fenced code blocks are never treated as card starts.

## Installation

```powershell
git clone https://github.com/Alishare21/flashcard-reminder.git
cd flashcard-reminder
python -m pip install -r requirements.txt
npm install
Copy-Item .env.example .env
```

Edit `config.yaml` for timezone, limits, and non-secret reminder options. Store credentials only in `.env`:

```env
SMTP_USER=your-address@gmail.com
SMTP_PASSWORD=your-google-app-password
REMINDER_FROM_EMAIL=your-address@gmail.com
REMINDER_TO_EMAIL=your-address@gmail.com
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SECRET_KEY=your-private-server-key
```

Never commit `.env`, local notes, database files, logs, or OAuth credentials. The public repository `.gitignore` excludes them. The private review mode still runs only on your computer because it displays personal card text and updates your real review history. The public page displays reminder status only and never exposes card questions or answers.

## Daily commands

```powershell
# Read changed notes and synchronize cards
python src/main.py sync

# Re-read every Markdown file
python src/main.py sync --full

# Review due cards
python src/main.py review

# Open the visual flashcard app (recommended)
python src/main.py web

# Review a specific deck or limit the session
python src/main.py review --deck python/basics --limit 10

# Preview the email without sending
python src/main.py remind

# Send the email when cards are due
python src/main.py remind --send

# Show deck and review statistics
python src/main.py stats
```

During a review, press Enter to reveal the answer, then choose `1` Again, `2` Hard, `3` Good, or `4` Easy. Press `q` to quit. Every completed answer is committed immediately.

## Visual flashcards

Run `python src/main.py web` to open the private review interface at `http://127.0.0.1:8765`. Click a card or press Space to flip it, then choose Again, Hard, Good, or Easy with the buttons or number keys `1`–`4`. Progress, due counts, new-card counts, and deck filtering update after every answer. The server accepts connections only from this computer, uses the same SQLite history and SM-2 scheduler as the terminal, and mirrors each saved answer to Supabase when cloud settings are configured. Stop it with `Ctrl+C` in PowerShell.

Every visible card comes directly from a Markdown file under `notes/`; the app does not invent FAQ content. Q/A cards show Question and Answer, term cards show Term and Definition, and cloze cards show Complete the sentence and Full sentence.

## Scheduling behavior

Cards start with ease `2.5`, interval `0`, and are due immediately. The SM-2 mapping is:

| Button | Grade | SM-2 quality |
|---|---:|---:|
| Again | 1 | 1 |
| Hard | 2 | 3 |
| Good | 3 | 4 |
| Easy | 4 | 5 |

Again resets repetitions and schedules one day later without changing ease. Successful intervals begin at 1 day, then 6 days, then use the stored interval multiplied by the previous ease. Intervals use `floor(value + 0.5)`, ease is rounded to two decimals, and the configured maximum interval is enforced.

Suspended and orphaned cards are excluded. Reviews are ordered by oldest overdue date, due today, and then new-card creation date. Deleting note content never deletes a card or its history; the card is marked orphaned.

## Email reminders

The subject reports total, new, and review counts. The body reports counts by deck, the oldest overdue age, and the review command. Card text is excluded unless `show_card_preview` is enabled. Dry-run is the default, successful sends are recorded once per date, and failed sends are not recorded.

For Gmail, enable 2-Step Verification and create a Google App Password. Use `smtp.gmail.com`, port `587`, and STARTTLS. The SMTP username also acts as the default sender and recipient when the optional email fields are blank.

## Automation

### Trigger.dev production schedule

`trigger/flashcard-daily.ts` runs at `0 8 * * *` using Trigger.dev's `Asia/Calcutta` timezone alias, a zero-minute schedule window, concurrency limit one, and no automatic retry. It reads only the private Supabase mirror and returns counts and status without card text or secrets.

Deploy after setting the required local environment variables:

```powershell
.\node_modules\.bin\trigger.cmd deploy --env-file .env
```

### Windows fallback

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_daily_task.ps1
```

This registers `Flashcard Daily Reminder` for 8:00 AM. The fallback is currently disabled because the Trigger.dev schedule, cloud state, SMTP authentication, live email, and duplicate-send protection have all been verified.

## Cloud storage

Apply `supabase/schema.sql` in the Supabase SQL editor. It creates `cards`, `reviews`, `reminders_sent`, and `note_files`, enables Row Level Security, blocks browser roles, and grants access only to the server role used by the backend.

Local commands mirror complete SQLite state with upserts after successful local work. Cloud synchronization never deletes rows. A later successful command safely reconciles a prior network failure.

Run the count-only cloud health check with:

```powershell
python src/cloud_storage_agent.py
```

## Testing

```powershell
python -m pytest -q --basetemp .pytest_tmp
npm run typecheck
```

The suite covers configuration validation, Markdown parsing, card identity, idempotent synchronization, orphan handling, every fixture SM-2 transition, due-card selection, interrupted reviews, reminder safety, Supabase mirroring, and Trigger.dev reminder output. Tests use fixed dates and mocked SMTP; they never contact a real email server.

## Project layout

```text
.agents/skills/flashcard-maintainer/  Codex maintenance skill
calendar/                            optional human reminder event
notes/                               private user-owned Markdown notes
scripts/                             local automation and setup helpers
src/                                 Python agents, local web server, and CLI
web/                                 visual flashcard HTML, CSS, and JavaScript
supabase/schema.sql                  private cloud schema
tests/                               pytest suite
trigger/                             Trigger.dev tasks
config.yaml                          non-secret application settings
example_data.json                    deterministic parser and SM-2 fixtures
trigger.config.ts                    Trigger.dev build and secret sync configuration
```

## Current status

- Visual flashcards, core CLI, reminder, statistics, Supabase mirror, maintainer skill, and local automation are implemented.
- Trigger.dev Production is deployed, a live 3-card email was delivered, and a follow-up cloud run returned `already_sent_today` without sending a duplicate.
- The complete automated suite passes.
- The Windows Task Scheduler fallback is disabled so Trigger.dev is the only daily 8:00 AM runner.

## Security and data guarantees

- `notes/` is read-only to the application.
- Cards and review history are never automatically deleted.
- Secrets remain in ignored `.env` files and secret Trigger.dev variables.
- Logs contain counts and card IDs, never credentials or card text.
- Email and Trigger.dev output contain counts only unless previews are explicitly enabled.
- Cloud tables are protected from anonymous and authenticated browser access.
