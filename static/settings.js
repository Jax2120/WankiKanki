const colorPurple = document.getElementById("colorPurple");
const colorPurple2 = document.getElementById("colorPurple2");
const colorGray = document.getElementById("colorGray");
const colorGood = document.getElementById("colorGood");
const colorBad = document.getElementById("colorBad");
const fontSelect = document.getElementById("fontSelect");
const saveSettingsBtn = document.getElementById("saveSettingsBtn");
const resetSettingsBtn = document.getElementById("resetSettingsBtn");
const settingsStatus = document.getElementById("settingsStatus");

function setStatus(text, isError = false) {
  settingsStatus.textContent = text;
  settingsStatus.classList.toggle("wk-settings-status-error", isError);
}

function applySettingsToForm(settings) {
  const colors = settings.colors || {};
  colorPurple.value = colors.purple || "#9f00ee";
  colorPurple2.value = colors.purple2 || "#9f00ee";
  colorGray.value = colors.gray || "#e9e9e9";
  colorGood.value = colors.good || "#83c700";
  colorBad.value = colors.bad || "#ff0037";
  fontSelect.value = settings.font || "modern";
}

function collectSettings() {
  return {
    colors: {
      purple: colorPurple.value,
      purple2: colorPurple2.value,
      gray: colorGray.value,
      good: colorGood.value,
      bad: colorBad.value,
    },
    font: fontSelect.value,
  };
}

function applyPreview(settings) {
  const root = document.body;
  root.style.setProperty("--wk-purple", settings.colors.purple);
  root.style.setProperty("--wk-purple2", settings.colors.purple2);
  root.style.setProperty("--wk-gray", settings.colors.gray);
  root.style.setProperty("--wk-good", settings.colors.good);
  root.style.setProperty("--wk-bad", settings.colors.bad);
  root.classList.remove(
    "font-modern",
    "font-friendly",
    "font-book",
    "font-clean",
    "font-system",
    "font-serif",
    "font-mono"
  );
  root.classList.add(`font-${settings.font}`);
}

async function loadSettings() {
  const res = await fetch("/api/settings", { cache: "no-store" });
  const data = await res.json();
  if (!data || data.ok === false) {
    setStatus("Could not load settings.", true);
    return;
  }
  applySettingsToForm(data.settings || {});
}

async function saveSettings() {
  const payload = collectSettings();
  applyPreview(payload);

  const res = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!data || data.ok === false) {
    setStatus((data && data.error) || "Save failed.", true);
    return;
  }
  setStatus("Saved.");
}

async function resetSettings() {
  const res = await fetch("/api/settings/reset", { method: "POST" });
  const data = await res.json();
  if (!data || data.ok === false) {
    setStatus((data && data.error) || "Reset failed.", true);
    return;
  }
  const settings = data.settings || {};
  applySettingsToForm(settings);
  applyPreview(settings);
  setStatus("Reset to default.");
}

saveSettingsBtn?.addEventListener("click", saveSettings);
resetSettingsBtn?.addEventListener("click", resetSettings);

for (const el of [colorPurple, colorPurple2, colorGray, colorGood, colorBad, fontSelect]) {
  el?.addEventListener("input", () => applyPreview(collectSettings()));
}
fontSelect?.addEventListener("change", () => applyPreview(collectSettings()));

loadSettings();
