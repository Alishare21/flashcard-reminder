---
name: flashcard-maintainer
description: Maintain and verify this project's Python flashcard app, visual and terminal review flows, schedule, reminders, local automation, and Trigger.dev tasks. Use for changes or audits in the Flash cards workspace.
---

# Flashcard maintainer

Work from the project root. Read `AGENTS.md`, the affected module, and its tests before changing behavior. `example_data.json` is the local fixture for parser output and exact SM-2 transitions; it was reconstructed from the user's specification.

## Invariants

- Never write to `notes/` or delete cards, reviews, or reminder history from `data/cards.db`. Sync updates changed backs while preserving schedules, and marks absent cards orphaned only for files reread during that sync. Repeated syncs are idempotent.
- Card IDs use the SHA-1 prefix of deck, type, and normalized front. Parse only the supported Q/A, `term :: definition`, and numbered cloze forms. Ignore starts inside code fences; skip invalid or oversized cards with warnings.
- SM-2 uses the stored interval and ease before review, rounds intervals with `floor(x + 0.5)`, rounds ease to two decimals, and leaves ease unchanged on Again. Commit a card update and review row together.
- Due selection excludes suspended and orphaned cards, respects daily limits, and orders overdue, due today, then new cards. Save after each reviewed card, including when a session later quits or is interrupted.
- `remind` is dry-run unless `--send` is explicit. Successful sends are recorded once per date. Keep SMTP secrets in `.env`; never print or log secrets or card text. Preview at most three fronts only when `show_card_preview` is enabled.
- Pass a fixed `today` into tested functions. The CLI computes it using the timezone in `config.yaml`.
- The `web` command binds only to `127.0.0.1` and uses the same due selection and transactional review save as the terminal session. Keep browser assets dependency-free, card text local, keyboard accessible, and usable on desktop and mobile. Do not add card text to HTTP request logs.

## Automation and verification

The current daily runner is the Trigger.dev Production task `flashcard-daily` at 8:00 AM India time. The Windows Task Scheduler fallback `Flashcard Daily Reminder` is installed but disabled after the cloud schedule, state, SMTP authentication, live email, and duplicate protection were verified. Google Calendar remains a human reminder only.

`trigger/flashcard-preview.ts` is a manual test using synthetic `example_data.json`, through `src/trigger_preview.py`. It must send no email and expose counts only. The 2026-10-08 Production run passed with 7 sample cards, 1 warning, 7 scheduler transitions, and `email_sent=false`. The preview verifies fixtures only; daily cloud operation uses the Supabase mirror through `trigger/flashcard-daily.ts`.

Google Drive migration was abandoned on 2026-10-08. Its old probe and OAuth helpers are historical and must not be reactivated unless the user explicitly returns to Drive.

Supabase project `flashcard-reminder` is the private cloud mirror. `supabase/schema.sql` creates the four tables, enables RLS, revokes browser roles, and grants the server role only the required table operations. Store `SUPABASE_URL` and `SUPABASE_SECRET_KEY` only in ignored `.env` and secret Trigger.dev environment variables. Never expose the key in logs, screenshots, source, task output, or chat. `python src/cloud_storage_agent.py` is a count-only health check. Local `sync`, `review`, and `remind` commands upsert all SQLite state after the local transaction; the mirror never deletes cloud rows, so a later successful command reconciles a prior network failure.

`src/cloud_reminder_agent.py` reads the Supabase mirror, applies the same new/review caps as the local scheduler, sends through TLS only when explicitly invoked with `--send`, and records a reminder only after SMTP succeeds. `trigger/flashcard-daily.ts` declares the Production-only `0 8 * * *` India-time schedule using Trigger.dev's supported `Asia/Calcutta` alias, with concurrency one and no retry. It returns counts and status only. The user explicitly authorized sending the Supabase URL and server secret to Trigger.dev on 2026-10-08.

Trigger.dev Production version `20261008.5` was deployed on 2026-10-08 with a zero-minute cron window and the authorized Gmail SMTP credentials stored as secret environment variables. Manual Production run `run_06ghnb54jjgafvc9loahkkjje1` verified the empty state. A STARTTLS login-only check authenticated successfully against Gmail. After three cards were synced, a real email was sent and mirrored to Supabase; Trigger Production run `run_06ghnit67jstr6392f2ld1mqe1` then returned `already_sent_today` with `due_total=3` and `email_sent=false`, verifying duplicate-send protection. The Windows task was disabled after every migration gate passed, so Trigger.dev is the only daily 8:00 AM runner.

Before switching off the Windows task, verify in order: local full tests, TypeScript typecheck, live count-only Supabase check, local cloud reminder with zero cards, Trigger Production deployment, manual Trigger run, one real due-card email, once-per-day behavior, and a second local mirror that leaves cloud counts stable. Keep card text out of Trigger outputs and logs.

Run focused tests for changed code and `python -m pytest -q --basetemp .pytest_tmp` before reporting. If Trigger files change, also run `npm run typecheck` and the Development preview; verify its run output in Trigger.dev. Update `README.md` when setup or automation changes.
