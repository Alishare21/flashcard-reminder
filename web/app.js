"use strict";

const el = (id) => document.getElementById(id);
const localServerUrl = "http://127.0.0.1:8765/";
const demoMode = window.location.hostname.endsWith("github.io") || new URLSearchParams(window.location.search).has("demo");
const demoStorageKey = "recall-public-demo-v1";
const reminderStorageKey = "recall-reminder-time-v1";
const state = {
  cards: [], reviewed: 0, initialTotal: 0, flipped: false, busy: false,
  deck: "", today: "", demoCatalog: [],
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
const reminderTime = el("reminder-time");
const calendarLink = el("google-calendar-link");

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

function nextReminderDate(timeText) {
  const [hours, minutes] = timeText.split(":").map(Number);
  const next = new Date();
  next.setHours(hours, minutes, 0, 0);
  if (next <= new Date()) next.setDate(next.getDate() + 1);
  return next;
}

function compactLocalDateTime(date) {
  const part = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}${part(date.getMonth() + 1)}${part(date.getDate())}T${part(date.getHours())}${part(date.getMinutes())}00`;
}

function updateReminder() {
  const timeText = reminderTime.value || "08:00";
  localStorage.setItem(reminderStorageKey, timeText);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const start = nextReminderDate(timeText);
  const end = new Date(start.getTime() + 10 * 60 * 1000);
  const display = new Intl.DateTimeFormat(undefined, {
    weekday: "long", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  }).format(start);
  el("next-reminder").textContent = `Next review: ${display} · ${timezone}`;
  const url = new URL("https://calendar.google.com/calendar/render");
  url.searchParams.set("action", "TEMPLATE");
  url.searchParams.set("text", "Review flashcards");
  url.searchParams.set("details", "Review the flashcards due today in Recall: https://alishare21.github.io/flashcard-reminder/");
  url.searchParams.set("dates", `${compactLocalDateTime(start)}/${compactLocalDateTime(end)}`);
  url.searchParams.set("recur", "RRULE:FREQ=DAILY");
  url.searchParams.set("ctz", timezone);
  calendarLink.href = url.toString();
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

function loadDemoProgress() {
  try {
    return JSON.parse(localStorage.getItem(demoStorageKey) || "{}");
  } catch (_error) {
    return {};
  }
}

function demoSession() {
  const today = localDate();
  const progress = loadDemoProgress();
  const cards = state.demoCatalog
    .filter((card) => !state.deck || card.deck === state.deck)
    .map((card) => {
      const saved = progress[card.id];
      return { ...card, due_date: saved?.due_date || today, is_new: !saved };
    })
    .filter((card) => card.due_date <= today)
    .sort((left, right) => {
      if (left.is_new !== right.is_new) return left.is_new ? 1 : -1;
      return left.due_date.localeCompare(right.due_date);
    });
  const deckCounts = new Map();
  cards.forEach((card) => deckCounts.set(card.deck, (deckCounts.get(card.deck) || 0) + 1));
  return {
    cards,
    total: cards.length,
    today,
    new_count: cards.filter((card) => card.is_new).length,
    review_count: cards.filter((card) => !card.is_new).length,
    decks: [...deckCounts.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([name, count]) => ({ name, count })),
  };
}

function nextDemoState(previous, grade) {
  const quality = { 1: 1, 2: 3, 3: 4, 4: 5 }[grade];
  let ease = previous?.ease ?? 2.5;
  let intervalDays = previous?.interval_days ?? 0;
  let repetitions = previous?.repetitions ?? 0;
  if (quality < 3) {
    repetitions = 0;
    intervalDays = 1;
  } else {
    repetitions += 1;
    if (repetitions === 1) intervalDays = 1;
    else if (repetitions === 2) intervalDays = 6;
    else intervalDays = Math.floor(intervalDays * ease + 0.5);
    ease = Math.max(1.3, Math.round((ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)) * 100) / 100);
  }
  intervalDays = Math.min(intervalDays, 365);
  return { ease, interval_days: intervalDays, repetitions, due_date: addDays(localDate(), intervalDays) };
}

async function loadDemoSession() {
  if (!state.demoCatalog.length) {
    const response = await fetch("demo-cards.json", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("Could not load the public demo cards");
    state.demoCatalog = await response.json();
  }
  applySession(demoSession(), true);
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
      await loadDemoSession();
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
    if (demoMode) {
      const card = state.cards[0];
      const progress = loadDemoProgress();
      progress[card.id] = nextDemoState(progress[card.id], grade);
      localStorage.setItem(demoStorageKey, JSON.stringify(progress));
      state.reviewed += 1;
      applySession(demoSession());
      return;
    }
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
  if (demoMode) localStorage.removeItem(demoStorageKey);
  loadSession();
});
el("retry-button").addEventListener("click", () => {
  if (window.location.protocol === "file:") {
    window.location.assign(localServerUrl);
    return;
  }
  loadSession();
});

document.addEventListener("keydown", (event) => {
  if (event.target instanceof HTMLSelectElement) return;
  if ((event.code === "Space" || event.code === "Enter") && !state.flipped) {
    event.preventDefault();
    reveal();
    return;
  }
  if (state.flipped && ["1", "2", "3", "4"].includes(event.key)) gradeCard(Number(event.key));
});

if (demoMode) {
  el("runtime-note").textContent = "Public demo · progress stays in this browser";
  el("refresh-button").textContent = "Reset demo";
  reminderPanel.classList.remove("hidden");
  reminderTime.value = localStorage.getItem(reminderStorageKey) || "08:00";
  reminderTime.addEventListener("change", updateReminder);
  updateReminder();
}
el("today-label").textContent = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date());
loadSession();
