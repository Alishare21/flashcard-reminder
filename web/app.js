"use strict";

const el = (id) => document.getElementById(id);
const localServerUrl = "http://127.0.0.1:8765/";
const demoMode = window.location.hostname.endsWith("github.io") || new URLSearchParams(window.location.search).has("demo");
const reminderStorageKey = "recall-reminders-v3";
const previousReminderStorageKey = "recall-reminder-config-v2";
const legacyReminderTimeKey = "recall-reminder-time-v1";
const allowedFrequencies = new Set(["daily", "weekdays", "weekly"]);
const state = {
  cards: [], reviewed: 0, initialTotal: 0, flipped: false, busy: false,
  deck: "", today: "",
};
const typeLabels = {
  qa: { front: "QUESTION", back: "ANSWER", kind: "Question & answer" },
  term: { front: "TERM", back: "DEFINITION", kind: "Term & definition" },
  cloze: { front: "COMPLETE THE SENTENCE", back: "FULL SENTENCE", kind: "Cloze" },
};

const loading = el("loading-state");
const stage = el("review-stage");
const complete = el("complete-state");
const errorState = el("error-state");
const flashcard = el("flashcard");
const gradeButtons = [...document.querySelectorAll(".grade")];
const deckSelect = el("deck-select");
const reminderPanel = el("reminder-panel");
const reminderName = el("reminder-name");
const reminderTime = el("reminder-time");
const reminderFrequency = el("reminder-frequency");
const saveReminderButton = el("save-reminder");
const publicReminderState = el("public-reminder-state");
const upcomingPanel = el("upcoming-panel");
const upcomingList = el("upcoming-list");
let reminderWeekday = new Date().getDay();
let reminders = [];
let editingReminderId = null;

function localDate() {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addDays(dateText, days) {
  const date = new Date(`${dateText}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function nextReminderDate(timeText, frequency, anchorWeekday, from = new Date()) {
  const [hours, minutes] = timeText.split(":").map(Number);
  const next = new Date(from);
  next.setHours(hours, minutes, 0, 0);
  if (frequency === "weekly") {
    const daysUntilAnchor = (anchorWeekday - from.getDay() + 7) % 7;
    next.setDate(next.getDate() + daysUntilAnchor);
    if (next <= from) next.setDate(next.getDate() + 7);
    return next;
  }
  if (next <= from) next.setDate(next.getDate() + 1);
  if (frequency === "weekdays") {
    while (next.getDay() === 0 || next.getDay() === 6) next.setDate(next.getDate() + 1);
  }
  return next;
}

function frequencyLabel(frequency) {
  return { daily: "Every day", weekdays: "Weekdays", weekly: "Every week" }[frequency] || "Every day";
}

function recurrenceRule(frequency) {
  if (frequency === "weekdays") return "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR";
  if (frequency === "weekly") return "RRULE:FREQ=WEEKLY";
  return "RRULE:FREQ=DAILY";
}

function validTime(value) {
  if (typeof value !== "string" || !/^\d{2}:\d{2}$/.test(value)) return false;
  const [hours, minutes] = value.split(":").map(Number);
  return hours <= 23 && minutes <= 59;
}

function normalizeReminder(value) {
  if (!value || typeof value !== "object" || !validTime(value.time)) return null;
  const name = typeof value.name === "string" ? value.name.trim().slice(0, 80) : "";
  return {
    id: typeof value.id === "string" && value.id ? value.id : crypto.randomUUID(),
    name: name || "Flashcard review",
    time: value.time,
    frequency: allowedFrequencies.has(value.frequency) ? value.frequency : "daily",
    weekday: Number.isInteger(value.weekday) && value.weekday >= 0 && value.weekday <= 6
      ? value.weekday : new Date().getDay(),
  };
}

function loadReminders() {
  try {
    const current = localStorage.getItem(reminderStorageKey);
    if (current !== null) {
      const parsed = JSON.parse(current);
      return Array.isArray(parsed) ? parsed.map(normalizeReminder).filter(Boolean) : [];
    }
  } catch (_error) { return []; }
  let previous = null;
  try { previous = JSON.parse(localStorage.getItem(previousReminderStorageKey)); } catch (_error) { /* ignore invalid legacy data */ }
  const legacyTime = localStorage.getItem(legacyReminderTimeKey);
  const migrated = normalizeReminder(previous || { name: "Flashcard review", time: legacyTime, frequency: "daily" });
  if (!migrated) return [];
  const result = [migrated];
  try {
    localStorage.setItem(reminderStorageKey, JSON.stringify(result));
    localStorage.removeItem(previousReminderStorageKey);
    localStorage.removeItem(legacyReminderTimeKey);
  } catch (_error) { /* leave old data in place when storage is unavailable */ }
  return result;
}

function persistReminders(next) {
  localStorage.setItem(reminderStorageKey, JSON.stringify(next));
  reminders = next;
}

function compactLocalDateTime(date) {
  const part = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}${part(date.getMonth() + 1)}${part(date.getDate())}T${part(date.getHours())}${part(date.getMinutes())}00`;
}

function renderStatusBadges(labels) {
  const container = el("reminder-status-badges");
  container.replaceChildren();
  labels.forEach((label) => {
    const badge = document.createElement("span");
    badge.textContent = label;
    container.append(badge);
  });
}

function calendarUrl(reminder, start, timezone) {
  const end = new Date(start.getTime() + 10 * 60 * 1000);
  const url = new URL("https://calendar.google.com/calendar/render");
  url.searchParams.set("action", "TEMPLATE");
  url.searchParams.set("text", reminder.name);
  url.searchParams.set("details", `Reminder created in Recall. Schedule: ${frequencyLabel(reminder.frequency)}. https://alishare21.github.io/flashcard-reminder/`);
  url.searchParams.set("dates", `${compactLocalDateTime(start)}/${compactLocalDateTime(end)}`);
  url.searchParams.set("recur", recurrenceRule(reminder.frequency));
  url.searchParams.set("ctz", timezone);
  return url.toString();
}

function renderDraft() {
  saveReminderButton.textContent = editingReminderId ? "Update reminder" : "Save reminder";
  if (!validTime(reminderTime.value)) {
    el("next-reminder").textContent = "Name an event, choose a time, and decide when it repeats.";
    return;
  }
  const next = nextReminderDate(reminderTime.value, reminderFrequency.value, reminderWeekday);
  el("next-reminder").textContent = `Next: ${new Intl.DateTimeFormat(undefined, {
    weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  }).format(next)} · ${frequencyLabel(reminderFrequency.value)}`;
}

function resetReminderForm() {
  editingReminderId = null;
  reminderName.value = "";
  reminderTime.value = "";
  reminderFrequency.value = "daily";
  reminderWeekday = new Date().getDay();
  renderDraft();
}

function renderSavedReminders() {
  const now = new Date();
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const scheduled = reminders.map((reminder) => ({
    reminder, start: nextReminderDate(reminder.time, reminder.frequency, reminder.weekday, now),
  })).sort((a, b) => a.start - b.start || a.reminder.name.localeCompare(b.reminder.name));
  const today = scheduled.filter(({ start }) => start.toDateString() === now.toDateString());
  el("public-reminder-icon").textContent = today.length ? "◷" : "✓";
  el("public-reminder-heading").textContent = today.length ? today[0].reminder.name : "You're all caught up.";
  el("public-reminder-copy").textContent = today.length
    ? `${today.length} reminder${today.length === 1 ? "" : "s"} left today. Next at ${new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(today[0].start)}.`
    : "No reminders for today.";
  renderStatusBadges([`${reminders.length} saved`, timezone]);
  upcomingList.replaceChildren();
  scheduled.forEach(({ reminder, start }) => {
    const item = document.createElement("li");
    const name = document.createElement("strong");
    name.textContent = reminder.name;
    const date = document.createElement("span");
    date.textContent = `${new Intl.DateTimeFormat(undefined, {
      weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    }).format(start)} · ${frequencyLabel(reminder.frequency)}`;
    const actions = document.createElement("div");
    actions.className = "saved-reminder-actions";
    const calendar = document.createElement("a");
    calendar.href = calendarUrl(reminder, start, timezone);
    calendar.target = "_blank";
    calendar.rel = "noopener";
    calendar.textContent = "Add to Google Calendar";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = "Edit";
    edit.addEventListener("click", () => {
      editingReminderId = reminder.id;
      reminderName.value = reminder.name;
      reminderTime.value = reminder.time;
      reminderFrequency.value = reminder.frequency;
      reminderWeekday = reminder.weekday;
      renderDraft();
      reminderName.focus();
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      if (!window.confirm(`Remove "${reminder.name}" from this browser? This does not remove a Google Calendar event.`)) return;
      try {
        persistReminders(reminders.filter(({ id }) => id !== reminder.id));
        if (editingReminderId === reminder.id) resetReminderForm();
        el("reminder-feedback").textContent = "Reminder removed from this browser.";
        renderSavedReminders();
      } catch (_error) { el("reminder-feedback").textContent = "Could not save. Check browser storage settings."; }
    });
    actions.append(calendar, edit, remove);
    item.append(name, date, actions);
    upcomingList.append(item);
  });
  el("upcoming-timezone").textContent = timezone;
  upcomingPanel.classList.toggle("hidden", !scheduled.length);
}

function saveReminder() {
  if (!validTime(reminderTime.value)) {
    el("reminder-feedback").textContent = "Choose a valid reminder time first.";
    reminderTime.focus();
    return;
  }
  const reminder = normalizeReminder({
    id: editingReminderId || crypto.randomUUID(),
    name: reminderName.value, time: reminderTime.value,
    frequency: reminderFrequency.value, weekday: reminderWeekday,
  });
  const next = editingReminderId
    ? reminders.map((existing) => existing.id === editingReminderId ? reminder : existing)
    : [...reminders, reminder];
  try {
    persistReminders(next);
    el("reminder-feedback").textContent = editingReminderId ? "Reminder updated in this browser." : "Reminder saved in this browser. Use Add to Google Calendar on its card to save it there too.";
    resetReminderForm();
    renderSavedReminders();
  } catch (_error) { el("reminder-feedback").textContent = "Could not save. Check browser storage settings."; }
}

function showOnly(section) {
  [loading, stage, complete, errorState].forEach((item) => item.classList.toggle("hidden", item !== section));
}

function setGrades(enabled) {
  gradeButtons.forEach((button) => { button.disabled = !enabled || state.busy; });
}

function updateProgress(session) {
  const remaining = session.total;
  const total = Math.max(state.initialTotal, state.reviewed + remaining);
  el("reviewed-count").textContent = String(state.reviewed);
  el("remaining-count").textContent = String(remaining);
  el("new-count").textContent = String(session.new_count);
  el("progress-fill").style.width = total ? `${Math.round((state.reviewed / total) * 100)}%` : "100%";
}

function fillDecks(decks) {
  const selected = state.deck;
  deckSelect.replaceChildren(new Option("All decks", ""));
  decks.forEach(({ name, count }) => deckSelect.add(new Option(`${name} (${count})`, name)));
  deckSelect.value = selected;
}

function appendInlineMarkdown(target, text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  parts.forEach((part) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = part.slice(2, -2);
      target.append(strong);
    } else {
      target.append(document.createTextNode(part));
    }
  });
}

function renderCardText(target, text) {
  target.replaceChildren();
  const chunks = text.split("```");
  chunks.forEach((chunk, index) => {
    if (index % 2 === 1) {
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = chunk.replace(/^\s*[\w+-]*\r?\n/, "").trimEnd();
      pre.append(code);
      target.append(pre);
      return;
    }
    const lines = chunk.split(/\r?\n/);
    lines.forEach((line, lineIndex) => {
      appendInlineMarkdown(target, line);
      if (lineIndex < lines.length - 1) target.append(document.createElement("br"));
    });
  });
}

function renderCard() {
  const card = state.cards[0];
  state.flipped = false;
  state.busy = false;
  flashcard.classList.remove("flipped");
  flashcard.setAttribute("aria-pressed", "false");
  flashcard.setAttribute("aria-label", "Reveal answer");
  setGrades(false);
  if (!card) {
    el("complete-copy").textContent = state.reviewed
      ? `You reviewed ${state.reviewed} card${state.reviewed === 1 ? "" : "s"}. Everything due today is complete.`
      : "Nothing is due right now. Your schedule is clear.";
    showOnly(complete);
    return;
  }
  el("deck-badge").textContent = card.deck;
  const labels = typeLabels[card.type] || { front: "FRONT", back: "BACK", kind: "Flashcard" };
  const dueStatus = card.is_new ? "New card" : card.due_date < state.today ? "Overdue" : "Due today";
  el("front-label").textContent = labels.front;
  el("back-label").textContent = labels.back;
  el("card-kind").textContent = `${dueStatus} · ${labels.kind}`;
  el("card-position").textContent = `${state.reviewed + 1} of ${state.reviewed + state.cards.length}`;
  renderCardText(el("card-front-text"), card.front);
  renderCardText(el("card-back-text"), card.back);
  el("status-line").textContent = "";
  showOnly(stage);
  flashcard.focus({ preventScroll: true });
}

function applySession(session, reset = false) {
  state.cards = session.cards;
  state.today = session.today;
  if (reset) {
    state.reviewed = 0;
    state.initialTotal = session.total;
    fillDecks(session.decks);
  }
  updateProgress(session);
  renderCard();
}

function reveal() {
  if (!state.cards.length || state.busy || state.flipped) return;
  state.flipped = true;
  flashcard.classList.add("flipped");
  flashcard.setAttribute("aria-pressed", "true");
  flashcard.setAttribute("aria-label", "Answer revealed");
  setGrades(true);
}

async function loadSession() {
  if (window.location.protocol === "file:") {
    el("error-copy").textContent =
      `This page was opened as a file. Start it with: python src/main.py web — then use ${localServerUrl}`;
    el("retry-button").textContent = "Open flashcards";
    showOnly(errorState);
    return;
  }
  showOnly(loading);
  try {
    if (demoMode) {
      [loading, stage, complete, errorState].forEach((section) => section.classList.add("hidden"));
      publicReminderState.classList.remove("hidden");
      renderSavedReminders();
      return;
    }
    const query = state.deck ? `?deck=${encodeURIComponent(state.deck)}` : "";
    const response = await fetch(`/api/session${query}`, { headers: { Accept: "application/json" } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not load session");
    applySession(data, true);
  } catch (error) {
    el("error-copy").textContent = error.message;
    showOnly(errorState);
  }
}

async function gradeCard(grade) {
  if (!state.flipped || state.busy || !state.cards.length) return;
  state.busy = true;
  setGrades(false);
  el("status-line").textContent = "Saving review…";
  try {
    const response = await fetch("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ card_id: state.cards[0].id, grade, deck: state.deck }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not save review");
    state.reviewed += 1;
    applySession(data.session);
  } catch (error) {
    state.busy = false;
    setGrades(true);
    el("status-line").textContent = error.message;
  }
}

flashcard.addEventListener("click", reveal);
gradeButtons.forEach((button) => button.addEventListener("click", () => gradeCard(Number(button.dataset.grade))));
deckSelect.addEventListener("change", () => { state.deck = deckSelect.value; loadSession(); });
el("refresh-button").addEventListener("click", () => {
  loadSession();
});
el("clear-reminder").addEventListener("click", () => {
  resetReminderForm();
  el("reminder-feedback").textContent = "Form reset. Saved reminders are unchanged.";
});
saveReminderButton.addEventListener("click", saveReminder);
el("retry-button").addEventListener("click", () => {
  if (window.location.protocol === "file:") {
    window.location.assign(localServerUrl);
    return;
  }
  loadSession();
});

document.addEventListener("keydown", (event) => {
  if (
    event.target instanceof HTMLInputElement
    || event.target instanceof HTMLTextAreaElement
    || event.target instanceof HTMLSelectElement
  ) return;
  if ((event.code === "Space" || event.code === "Enter") && !state.flipped) {
    event.preventDefault();
    reveal();
    return;
  }
  if (state.flipped && ["1", "2", "3", "4"].includes(event.key)) gradeCard(Number(event.key));
});

if (demoMode) {
  el("runtime-note").textContent = "Public reminder dashboard · settings stay in this browser";
  el("brand-subtitle").textContent = "daily reminders";
  el("footer-divider").classList.add("hidden");
  el("scheduler-note").classList.add("hidden");
  document.querySelector(".shortcut-copy").classList.add("hidden");
  el("progress-panel").classList.add("hidden");
  el("deck-picker").classList.add("hidden");
  reminderPanel.classList.remove("hidden");
  reminders = loadReminders();
  reminderName.addEventListener("input", renderDraft);
  reminderTime.addEventListener("change", renderDraft);
  reminderFrequency.addEventListener("change", () => {
    if (reminderFrequency.value === "weekly") reminderWeekday = new Date().getDay();
    renderDraft();
  });
  renderDraft();
  renderSavedReminders();
}
el("today-label").textContent = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date());
loadSession();
