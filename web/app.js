"use strict";

const el = (id) => document.getElementById(id);
const localServerUrl = "http://127.0.0.1:8765/";
const state = { cards: [], reviewed: 0, initialTotal: 0, flipped: false, busy: false, deck: "", today: "" };
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
el("refresh-button").addEventListener("click", loadSession);
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

el("today-label").textContent = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date());
loadSession();
