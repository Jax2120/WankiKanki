let current = null;
let currentPrompt = "reading";
let state = "question"; // "question" | "result" | "lesson_study"

let lessonChunk = [];
let lessonIndex = 0;

const big = document.getElementById("big");
const mode = document.getElementById("mode");
const answer = document.getElementById("answer");
const bar = document.getElementById("bar");
const remaining = document.getElementById("remaining");

const resultStrip = document.getElementById("resultStrip");
const resultText = document.getElementById("resultText");
const expected = document.getElementById("expected");
const hint = document.getElementById("hint");
const deckLabel = document.getElementById("deckLabel");
const notesToggle = document.getElementById("notesToggle");
const notesPanel = document.getElementById("notesPanel");
const notesContent = document.getElementById("notesContent");

const lessonStudy = document.getElementById("lessonStudy");
const lessonFront = document.getElementById("lessonFront");
const lessonReading = document.getElementById("lessonReading");
const lessonMeaning = document.getElementById("lessonMeaning");
const lessonPrevBtn = document.getElementById("lessonPrevBtn");
const lessonNextBtn = document.getElementById("lessonNextBtn");
const lessonQuizBtn = document.getElementById("lessonQuizBtn");

function showHint(text) {
  hint.classList.remove("hidden");
  hint.textContent = text;
}

function escapeHtml(s) {
  return (s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function isKanji(ch) {
  return /[\u3400-\u9fff々〆ヵヶ]/.test(ch || "");
}

function isKana(ch) {
  return /[\u3040-\u30ffー]/.test(ch || "");
}

function toHiragana(s) {
  return (s || "").replace(/[\u30a1-\u30f6]/g, (ch) =>
    String.fromCharCode(ch.charCodeAt(0) - 0x60)
  );
}

function setBigText(text) {
  big.textContent = text || "-";
}

function setBigWithFurigana(front, readingKana) {
  const f = (front || "").trim();
  const r = toHiragana((readingKana || "").trim());
  if (!f || !r) {
    setBigText(f || "-");
    return;
  }

  // Build ruby for mixed kanji/kana words by anchoring kana in reading.
  const chars = [...f];
  const out = [];
  let i = 0;
  let rIdx = 0;

  while (i < chars.length) {
    const ch = chars[i];
    if (!isKanji(ch)) {
      out.push(escapeHtml(ch));
      const hk = toHiragana(ch);
      if (r.slice(rIdx, rIdx + hk.length) === hk) {
        rIdx += hk.length;
      }
      i += 1;
      continue;
    }

    // Kanji run
    const runStart = i;
    while (i < chars.length && isKanji(chars[i])) i += 1;
    const runText = chars.slice(runStart, i).join("");

    // Next kana anchor in front
    let anchor = "";
    let j = i;
    while (j < chars.length && !isKanji(chars[j])) {
      anchor += chars[j];
      j += 1;
    }
    const anchorH = toHiragana(anchor);

    let rt = "";
    if (!anchorH) {
      rt = r.slice(rIdx);
      rIdx = r.length;
    } else {
      const anchorPos = r.indexOf(anchorH, rIdx);
      if (anchorPos >= 0) {
        rt = r.slice(rIdx, anchorPos);
        rIdx = anchorPos;
      }
    }

    if (rt) {
      out.push(`<ruby>${escapeHtml(runText)}<rt>${escapeHtml(rt)}</rt></ruby>`);
    } else {
      out.push(escapeHtml(runText));
    }
  }

  big.innerHTML = out.join("") || escapeHtml(f);
}

function normalizeNotesHtml(raw) {
  const text = (raw || "")
    .replace(/<\s*br\s*\/?>/gi, "\n")
    .replace(/<[^>]*>/g, "");
  const el = document.createElement("textarea");
  el.innerHTML = text;
  return (el.value || "").trim();
}

function setNotesVisible(visible) {
  if (!notesPanel || !notesToggle) return;
  notesPanel.classList.toggle("hidden", !visible);
  notesToggle.setAttribute("aria-expanded", visible ? "true" : "false");
}

function loadNotesForCurrentCard() {
  if (!notesContent || !notesToggle) return;
  const notesText = normalizeNotesHtml(current?.notes || "");
  notesContent.textContent = notesText || "(No notes on this card)";
  notesToggle.classList.remove("hidden");
  setNotesVisible(false);
}

function setProgress(rem, total, completed = 0) {
  remaining.textContent = `Left ${rem} | Done ${completed}`;
  if (!total || total <= 0) {
    bar.style.width = "0%";
    return;
  }
  const done = Math.max(0, total - rem);
  const pct = Math.max(0, Math.min(100, (done / total) * 100));
  bar.style.width = `${pct}%`;
}

function resetResultUI() {
  resultStrip.classList.add("hidden");
  resultStrip.classList.remove("good", "bad");
  expected.classList.add("hidden");
  expected.textContent = "";
  hint.classList.add("hidden");
  answer.classList.remove("shake");
  document.body.classList.remove("wk-good", "wk-bad");
}

function setTheme(kind) {
  document.body.classList.remove("wk-good", "wk-bad");
  if (kind === "good") document.body.classList.add("wk-good");
  if (kind === "bad") document.body.classList.add("wk-bad");
}

function setPromptThemeClass(prompt) {
  document.body.classList.remove("prompt-reading", "prompt-meaning");
  if (prompt === "reading") document.body.classList.add("prompt-reading");
  if (prompt === "meaning") document.body.classList.add("prompt-meaning");
}

function applyPromptUI(prompt) {
  currentPrompt = (prompt === "meaning") ? "meaning" : "reading";
  setPromptThemeClass(currentPrompt);
  mode.textContent = currentPrompt === "reading" ? "Reading" : "Meaning";
  answer.placeholder = currentPrompt === "reading" ? "答え" : "Your Response";
}

function setLessonStudyVisible(visible) {
  if (!lessonStudy) return;
  lessonStudy.classList.toggle("hidden", !visible);
  document.querySelector(".wk-answer-row")?.classList.toggle("hidden", visible);
  notesToggle?.classList.toggle("hidden", visible);
  notesPanel?.classList.add("hidden");
  expected.classList.toggle("hidden", true);
  if (visible) {
    setPromptThemeClass(null);
    answer.disabled = true;
    answer.value = "";
  } else {
    answer.disabled = false;
  }
}

function renderLessonCard() {
  if (!lessonChunk.length) return;
  const card = lessonChunk[lessonIndex];
  lessonFront.textContent = card.front || "-";
  lessonReading.textContent = card.reading || "-";
  lessonMeaning.textContent = (card.meanings && card.meanings.length) ? card.meanings.join(", ") : "-";

  setBigWithFurigana(card.front, card.readingKana || card.reading);
  mode.textContent = "Lessons";

  if (lessonPrevBtn) lessonPrevBtn.disabled = lessonIndex === 0;
  if (lessonNextBtn) lessonNextBtn.classList.toggle("hidden", lessonIndex >= lessonChunk.length - 1);
  if (lessonQuizBtn) lessonQuizBtn.classList.toggle("hidden", lessonIndex < lessonChunk.length - 1);

  showHint(`Card ${lessonIndex + 1} of ${lessonChunk.length}`);
}

async function startLessonQuiz() {
  try {
    const res = await fetch("/lesson/start_quiz", { method: "POST" });
    const out = await res.json();
    if (!out || out.ok === false) {
      showHint((out && out.error) || "Could not start lesson quiz.");
      return;
    }
    await loadCard();
  } catch (e) {
    showHint("Network/server error. Could not start quiz.");
  }
}

// Convert only on reading prompts.
let suppressKana = false;
answer.addEventListener("input", () => {
  if (suppressKana) return;
  if (currentPrompt !== "reading") return;
  if (!window.wanakana || typeof window.wanakana.toKana !== "function") return;

  const v = answer.value;
  const k = window.wanakana.toKana(v, { IMEMode: true });
  if (k !== v) {
    suppressKana = true;
    answer.value = k;
    try { answer.setSelectionRange(k.length, k.length); } catch {}
    suppressKana = false;
  }
});

async function loadCard() {
  resetResultUI();

  const res = await fetch("/next", { cache: "no-store" });
  const data = await res.json();

  if (data.ok === false) {
    showHint(data.error || "Server error.");
    return;
  }

  if (deckLabel && data.deck) deckLabel.textContent = data.deck;

  if (data.done) {
    state = "question";
    setLessonStudyVisible(false);
    setPromptThemeClass(null);
    setBigText("Done!");
    answer.style.display = "none";
    setProgress(0, data.total || 0, data.completed || 0);
    return;
  }

  if (data.mode === "lessons" && data.lessonPhase === "study") {
    state = "lesson_study";
    lessonChunk = Array.isArray(data.chunk) ? data.chunk : [];
    lessonIndex = 0;
    setLessonStudyVisible(true);
    setProgress(data.remaining, data.total, data.completed || 0);
    renderLessonCard();
    return;
  }

  state = "question";
  setLessonStudyVisible(false);

  current = data.card;
  applyPromptUI(data.prompt);
  loadNotesForCurrentCard();

  setBigText(current.front || "-");
  setProgress(data.remaining, data.total, data.completed || 0);

  answer.style.display = "";
  answer.disabled = false;
  answer.value = "";
  answer.focus();
}

async function submit() {
  if (!current) return;
  const user = (answer.value || "").trim();

  let out;
  try {
    const res = await fetch("/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cardId: current.cardId, answer: user })
    });
    out = await res.json();
  } catch (e) {
    showHint("Network/server error. Press Enter to retry.");
    return;
  }

  if (out && out.ok === false) {
    showHint(out.error || "Server error. Press Enter to retry.");
    return;
  }

  state = "result";
  answer.disabled = true;

  resultStrip.classList.remove("hidden");
  hint.classList.remove("hidden");

  expected.classList.add("hidden");
  expected.textContent = "";

  if (out.correct) {
    resultStrip.classList.add("good");
    resultText.textContent = out.ideal || out.expected || "OK";
    setTheme("good");
    hint.textContent = "Press Enter to continue - Backspace/Ctrl+Z to undo";
  } else {
    resultStrip.classList.add("bad");
    resultText.textContent = out.ideal || out.expected || "...";
    if (currentPrompt === "reading" && (out.ideal || out.expected)) {
      setBigText(out.ideal || out.expected);
    }
    answer.classList.add("shake");
    setTheme("bad");
    hint.textContent = "Press Enter to continue - Backspace/Ctrl+Z to undo";
  }

  setProgress(out.remaining, out.total, out.completed || 0);
}

async function undoLast() {
  let out;
  try {
    const res = await fetch("/undo", { method: "POST" });
    out = await res.json();
  } catch (e) {
    showHint("Undo failed (network).");
    return;
  }

  if (out && out.ok === false) {
    showHint(out.error || "Undo failed.");
    return;
  }

  await loadCard();
}

document.addEventListener("keydown", async (e) => {
  const isZ = e.key === "z" || e.key === "Z";
  const undoCombo = (e.ctrlKey || e.metaKey) && isZ;

  if (state === "lesson_study") {
    if (e.key === "Enter") {
      e.preventDefault();
      if (lessonIndex < lessonChunk.length - 1) {
        lessonIndex += 1;
        renderLessonCard();
      } else {
        await startLessonQuiz();
      }
    }
    if (e.key === "Backspace") {
      e.preventDefault();
      if (lessonIndex > 0) {
        lessonIndex -= 1;
        renderLessonCard();
      }
    }
    return;
  }

  if (state === "result" && (e.key === "Backspace" || undoCombo)) {
    e.preventDefault();
    e.stopPropagation();
    await undoLast();
    return;
  }

  if (e.key === "Enter") {
    e.preventDefault();
    e.stopPropagation();
    if (state === "question") {
      await submit();
    } else {
      await loadCard();
    }
  }
}, true);

document.querySelector(".wk-arrow")?.addEventListener("click", (e) => {
  e.preventDefault();
  if (state === "question") submit();
  else loadCard();
});

lessonPrevBtn?.addEventListener("click", () => {
  if (lessonIndex <= 0) return;
  lessonIndex -= 1;
  renderLessonCard();
});

lessonNextBtn?.addEventListener("click", () => {
  if (lessonIndex >= lessonChunk.length - 1) return;
  lessonIndex += 1;
  renderLessonCard();
});

lessonQuizBtn?.addEventListener("click", async () => {
  await startLessonQuiz();
});

notesToggle?.addEventListener("click", () => {
  const isHidden = notesPanel?.classList.contains("hidden");
  setNotesVisible(Boolean(isHidden));
});

loadCard();
