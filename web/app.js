"use strict";

const el = (id) => document.getElementById(id);
const localServerUrl = "http://127.0.0.1:8765/";
const demoMode = window.location.hostname.endsWith("github.io") || new URLSearchParams(window.location.search).has("demo");
const reminderStorageKey = "recall-reminder-config-v2";
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
const calendarLink = el("google-calendar-link");
const publicReminderState = el("public-reminder-state");
const upcomingPanel = el("upcoming-panel");
const upcomingList = el("upcoming-list");
let reminderWeekday = new Date().getDay();

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

function advanceOccurrence(date, frequency) {
  const next = new Date(date);
  next.setDate(next.getDate() + (frequency === "weekly" ? 7 : 1));
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

function loadReminderConfig() {
  const fallback = {
    name: "Flashcard review", time: localStorage.getItem(legacyReminderTimeKey) || "",
    frequency: "daily", weekday: new Date().getDay(),
  };
  try {
    const saved = JSON.parse(localStorage.getItem(reminderStorageKey));
    if (!saved || typeof saved !== "object") return fallback;
    return {
      name: typeof saved.name === "string" ? saved.name.slice(0, 80) : fallback.name,
      time: /^\d{2}:\d{2}$/.test(saved.time || "") ? saved.time : fallback.time,
      frequency: allowedFrequencies.has(saved.frequency) ? saved.frequency : "daily",
      weekday: Number.isInteger(saved.weekday) && saved.weekday >= 0 && saved.weekday <= 6
        ? saved.weekday : fallback.weekday,
    };
  } catch (_error) {
    return fallback;
  }
}

function saveReminderConfig(name, time, frequency) {
  localStorage.setItem(reminderStorageKey, JSON.stringify({ name, time, frequency, weekday: reminderWeekday }));
  localStorage.removeItem(legacyReminderTimeKey);
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

function renderUpcoming(start, title, frequency, timezone) {
  upcomingList.replaceChildren();
  let occurrence = new Date(start);
  for (let index = 0; index < 3; index += 1) {
    const item = document.createElement("li");
    const name = document.createElement("strong");
    const date = document.createElement("span");
    name.textContent = title;
    date.textContent = new Intl.DateTimeFormat(undefined, {
      weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    }).format(occurrence);
    item.append(name, date);
    upcomingList.append(item);
    occurrence = advanceOccurrence(occurrence, frequency);
  }
  el("upcoming-timezone").textContent = timezone;
  upcomingPanel.classList.remove("hidden");
}

function updateReminder(persist = true) {
  const title = reminderName.value.trim().slice(0, 80) || "Flashcard review";
  const timeText = reminderTime.value;
  const frequency = allowedFrequencies.has(reminderFrequency.value) ? reminderFrequency.value : "daily";
  if (!timeText) {
    if (persist) saveReminderConfig(title, "", frequency);
    el("next-reminder").textContent = "No schedule yet. Choose a time when you're ready.";
    el("public-reminder-icon").textContent = "✓";
    el("public-reminder-heading").textContent = "You're all caught up.";
    el("public-reminder-copy").textContent = "No reminders for today.";
    renderStatusBadges(["Schedule clear"]);
    upcomingPanel.classList.add("hidden");
    calendarLink.removeAttribute("href");
    calendarLink.classList.add("disabled");
    calendarLink.setAttribute("aria-disabled", "true");
    calendarLink.textContent = "Set a time to continue";
    return;
  }
  if (persist) saveReminderConfig(title, timeText, frequency);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const start = nextReminderDate(timeText, frequency, reminderWeekday);
  const end = new Date(start.getTime() + 10 * 60 * 1000);
  const display = new Intl.DateTimeFormat(undefined, {
    weekday: "long", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  }).format(start);
  el("next-reminder").textContent = `Next: ${display} · ${frequencyLabel(frequency)}`;
  const isToday = start.toDateString() === new Date().toDateString();
  el("public-reminder-icon").textContent = isToday ? "◷" : "✓";
  el("public-reminder-heading").textContent = isToday ? title : "You're all caught up.";
  el("public-reminder-copy").textContent = isToday
    ? `Scheduled today at ${new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(start)}.`
    : `No reminders for today. Next: ${title} · ${display}.`;
  renderStatusBadges([frequencyLabel(frequency), timezone]);
  renderUpcoming(start, title, frequency, timezone);
  const url = new URL("https://calendar.google.com/calendar/render");
  url.searchParams.set("action", "TEMPLATE");
  url.searchParams.set("text", title);
  url.searchParams.set("details", `Flashcard reminder created in Recall. Schedule: ${frequencyLabel(frequency)}. https://alishare21.github.io/flashcard-reminder/`);
  url.searchParams.set("dates", `${compactLocalDateTime(start)}/${compactLocalDateTime(end)}`);
  url.searchParams.set("recur", recurrenceRule(frequency));
  url.searchParams.set("ctz", timezone);
  calendarLink.href = url.toString();
  calendarLink.classList.remove("disabled");
  calendarLink.setAttribute("aria-disabled", "false");
  calendarLink.textContent = "Add to Google Calendar";
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
      updateReminder();
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
  reminderName.value = "Flashcard review";
  reminderTime.value = "";
  reminderFrequency.value = "daily";
  reminderWeekday = new Date().getDay();
  localStorage.removeItem(reminderStorageKey);
  localStorage.removeItem(legacyReminderTimeKey);
  updateReminder(false);
});
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
  const reminderConfig = loadReminderConfig();
  reminderName.value = reminderConfig.name;
  reminderTime.value = reminderConfig.time;
  reminderFrequency.value = reminderConfig.frequency;
  reminderWeekday = reminderConfig.weekday;
  reminderName.addEventListener("input", () => updateReminder());
  reminderTime.addEventListener("change", updateReminder);
  reminderFrequency.addEventListener("change", () => {
    if (reminderFrequency.value === "weekly") reminderWeekday = new Date().getDay();
    updateReminder();
  });
  updateReminder();
}
el("today-label").textContent = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date());
loadSession();
