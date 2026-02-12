const lessonsCount = document.getElementById("lessonsCount");
const reviewsCount = document.getElementById("reviewsCount");
const deckSelect = document.getElementById("deckSelect");
const splashDeckName = document.getElementById("splashDeckName");
const splashMain = document.querySelector(".wk-splash-main");
const ankiStatus = document.getElementById("ankiStatus");
const ankiStatusCopy = document.getElementById("ankiStatusCopy");
const ankiSteps = document.getElementById("ankiSteps");
const toggleDeckExamples = document.getElementById("toggleDeckExamples");
const deckExamples = document.getElementById("deckExamples");

function updateDeckHeader(deck) {
  splashDeckName.textContent = deck || "-";
}

function fillDeckOptions(decks, currentDeck) {
  deckSelect.innerHTML = "";
  for (const deck of decks || []) {
    const opt = document.createElement("option");
    opt.value = deck;
    opt.textContent = deck;
    if (deck === currentDeck) opt.selected = true;
    deckSelect.appendChild(opt);
  }
}

function setAnkiStatus(connected, errorText = "", steps = []) {
  splashMain?.classList.toggle("api-required", !connected);
  ankiStatus?.classList.toggle("hidden", connected);

  if (connected) {
    ankiSteps.innerHTML = "";
    return;
  }

  ankiStatusCopy.textContent = errorText
    ? `Could not connect to AnkiConnect (${errorText}). Follow these steps, then refresh.`
    : "Could not connect to AnkiConnect. Follow these steps, then refresh.";

  ankiSteps.innerHTML = "";
  for (const step of steps || []) {
    const li = document.createElement("li");
    li.textContent = step;
    ankiSteps.appendChild(li);
  }
}

async function loadSplashData() {
  const res = await fetch("/api/splash", { cache: "no-store" });
  const data = await res.json();

  if (!data || data.ok === false) return;

  lessonsCount.textContent = String(data.lessonsAvailable ?? 0);
  reviewsCount.textContent = String(data.reviewsAvailable ?? 0);
  updateDeckHeader(data.deck || "");
  fillDeckOptions(data.decks || [], data.deck || "");
  setAnkiStatus(Boolean(data.ankiConnected), data.error || "", data.instructions || []);
}

async function setDeck(deck) {
  const res = await fetch("/set_deck", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ deck })
  });
  const data = await res.json();
  if (!data || data.ok === false) return;
  await loadSplashData();
}

deckSelect?.addEventListener("change", async () => {
  const chosen = deckSelect.value || "";
  if (!chosen) return;
  await setDeck(chosen);
});

toggleDeckExamples?.addEventListener("click", () => {
  const isHidden = deckExamples.classList.contains("hidden");
  deckExamples.classList.toggle("hidden", !isHidden);
  toggleDeckExamples.textContent = isHidden ? "Hide card format examples" : "Show card format examples";
});

loadSplashData();
