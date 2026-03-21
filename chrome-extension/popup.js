async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

const SUPPORTED_URL_PATTERNS = [
  /^https:\/\/outlook\.office\.com\//i,
  /^https:\/\/outlook\.live\.com\//i,
  /^https:\/\/outlook\.office365\.com\//i,
  /^https:\/\/outlook\.cloud\.microsoft\//i
];

function isSupportedOutlookUrl(url) {
  return SUPPORTED_URL_PATTERNS.some(pattern => pattern.test(url || ""));
}

async function pingContentScript(tabId) {
  return chrome.tabs.sendMessage(tabId, { type: "triage:ping" });
}

async function injectContentScript(tab) {
  if (!tab?.id) throw new Error("No active tab.");
  await chrome.scripting.insertCSS({
    target: { tabId: tab.id },
    files: ["content-style.css"]
  }).catch(() => {});
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["triage-core.js", "dom-extract.js", "content-script.js"]
  });
}

async function ensureContentScript(tab) {
  if (!tab?.id) throw new Error("No active tab.");
  if (!isSupportedOutlookUrl(tab.url || "")) {
    throw new Error("Open Outlook Web in the current tab first.");
  }

  try {
    await pingContentScript(tab.id);
    return;
  } catch (error) {
    const message = String(error?.message || error);
    if (!message.includes("Receiving end does not exist")) {
      throw error;
    }
  }

  await injectContentScript(tab);

  try {
    await pingContentScript(tab.id);
  } catch (error) {
    throw new Error("Injected the extension, but Outlook Web still did not respond. Refresh the tab once and try again.");
  }
}

async function sendToContentScript(message) {
  const tab = await getActiveTab();
  if (!tab?.id) throw new Error("No active tab.");
  await ensureContentScript(tab);
  return chrome.tabs.sendMessage(tab.id, message);
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

async function saveLastCapture(report) {
  await chrome.storage.local.set({ triageLastCapture: report });
}

async function loadLastCapture() {
  const { triageLastCapture } = await chrome.storage.local.get(["triageLastCapture"]);
  return triageLastCapture || null;
}

async function exportReport(report) {
  if (!report) {
    throw new Error("Capture a message first, then export it.");
  }
  const fileName = `email-triage-lab/outlook-capture-${new Date().toISOString().replaceAll(":", "-")}.json`;
  const blob = new Blob([pretty(report)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  try {
    await chrome.downloads.download({
      url,
      filename: fileName,
      saveAs: false
    });
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return fileName;
}

function renderError(error) {
  const message = String(error?.message || error);
  if (message.includes("Receiving end does not exist")) {
    return "Outlook page has not loaded the extension yet. Refresh the Outlook tab once and try again.";
  }
  return message;
}

const stateEl = document.getElementById("state");
const pageEl = document.getElementById("page");
const outputEl = document.getElementById("output");
const rulesEl = document.getElementById("rules");
const labelEl = document.getElementById("label");
let lastCapturedReport = null;

async function loadRules() {
  const { triageRules, triageLabel } = await chrome.storage.local.get(["triageRules", "triageLabel"]);
  const rules = Array.isArray(triageRules) && triageRules.length ? triageRules : window.EmailTriageCore.DEFAULT_RULES;
  rulesEl.value = JSON.stringify(rules, null, 2);
  labelEl.value = triageLabel || "Inbox Triage";
  lastCapturedReport = await loadLastCapture();
  if (lastCapturedReport) {
    pageEl.textContent = lastCapturedReport?.view?.url || "Last capture loaded";
    outputEl.textContent = pretty(lastCapturedReport);
    stateEl.textContent = "Last capture loaded";
  }
}

async function saveRules(rules, label) {
  await chrome.runtime.sendMessage({ type: "triage:save-rules", rules, label });
}

document.getElementById("capture").addEventListener("click", async () => {
  stateEl.textContent = "Capturing...";
  try {
    const response = await sendToContentScript({ type: "triage:capture" });
    lastCapturedReport = response?.report || response;
    await saveLastCapture(lastCapturedReport);
    stateEl.textContent = response?.ok ? "Captured" : "No response";
    pageEl.textContent = lastCapturedReport?.view?.url || "Unknown page";
    outputEl.textContent = pretty(lastCapturedReport);
  } catch (error) {
    stateEl.textContent = "Error";
    outputEl.textContent = renderError(error);
  }
});

document.getElementById("toggle").addEventListener("click", async () => {
  stateEl.textContent = "Toggling...";
  try {
    const response = await sendToContentScript({ type: "triage:toggle-panel" });
    stateEl.textContent = response?.ok ? "Panel toggled" : "No response";
    pageEl.textContent = response?.report?.view?.url || pageEl.textContent;
    outputEl.textContent = pretty(response?.report || response);
  } catch (error) {
    stateEl.textContent = "Error";
    outputEl.textContent = renderError(error);
  }
});

document.getElementById("export").addEventListener("click", async () => {
  stateEl.textContent = "Exporting...";
  try {
    const fileName = await exportReport(lastCapturedReport);
    stateEl.textContent = "Exported";
    outputEl.textContent = `Saved current capture to Downloads/${fileName}`;
  } catch (error) {
    stateEl.textContent = "Error";
    outputEl.textContent = renderError(error);
  }
});

document.getElementById("saveRules").addEventListener("click", async () => {
  try {
    const parsed = JSON.parse(rulesEl.value || "[]");
    await saveRules(parsed, labelEl.value.trim());
    stateEl.textContent = "Rules saved";
    outputEl.textContent = "Saved rules locally. Capture the current tab to apply them.";
  } catch (error) {
    stateEl.textContent = "Invalid rules";
    outputEl.textContent = String(error?.message || error);
  }
});

document.getElementById("resetRules").addEventListener("click", async () => {
  const defaults = [
    ...window.EmailTriageCore.DEFAULT_RULES
  ];
  rulesEl.value = JSON.stringify(defaults, null, 2);
  labelEl.value = "Inbox Triage";
  await saveRules(defaults, "Inbox Triage");
  stateEl.textContent = "Defaults restored";
  outputEl.textContent = "Default rules restored.";
});

loadRules().catch(error => {
  outputEl.textContent = renderError(error);
});
