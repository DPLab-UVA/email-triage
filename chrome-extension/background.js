const PANEL_STATE_KEY = "triagePanelEnabled";
const CAPTURE_HISTORY_KEY = "triageCaptureHistory";
const INGEST_ENABLED_KEY = "triageAutoIngestEnabled";
const INGEST_ENDPOINT_KEY = "triageIngestEndpoint";
const DEFAULT_INGEST_ENDPOINT = "http://127.0.0.1:8765/capture";
const PLACEHOLDER_VALUES = new Set(["", "subject", "from", "home"]);

function normalizeText(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim();
}

function hasRealText(value) {
  const normalized = normalizeText(value).toLowerCase();
  if (!normalized) return false;
  if (PLACEHOLDER_VALUES.has(normalized)) return false;
  if (/^[^\p{L}\p{N}@]+$/u.test(normalized)) return false;
  return normalized.length >= 2;
}

function isMeaningfulCapture(report) {
  const view = report?.view || {};
  const bodyPreview = normalizeText(view.bodyPreview || "");
  const subject = normalizeText(view.subject || "");
  const sender = normalizeText(view.sender || "");
  const url = String(view.url || "");

  if (!url.includes("/mail/")) return false;
  if (bodyPreview.length < 80) return false;
  if (!hasRealText(subject) && !hasRealText(sender)) return false;
  if (/^(home|inbox|sent|drafts)$/i.test(subject || sender)) return false;
  return true;
}

async function ensureDefaults() {
  const current = await chrome.storage.local.get([
    PANEL_STATE_KEY,
    CAPTURE_HISTORY_KEY,
    INGEST_ENABLED_KEY,
    INGEST_ENDPOINT_KEY
  ]);

  const updates = {};
  if (typeof current[PANEL_STATE_KEY] === "undefined") {
    updates[PANEL_STATE_KEY] = false;
  }
  if (!Array.isArray(current[CAPTURE_HISTORY_KEY])) {
    updates[CAPTURE_HISTORY_KEY] = [];
  }
  if (typeof current[INGEST_ENABLED_KEY] === "undefined") {
    updates[INGEST_ENABLED_KEY] = true;
  }
  if (typeof current[INGEST_ENDPOINT_KEY] !== "string" || !current[INGEST_ENDPOINT_KEY]) {
    updates[INGEST_ENDPOINT_KEY] = DEFAULT_INGEST_ENDPOINT;
  }

  if (Object.keys(updates).length) {
    await chrome.storage.local.set(updates);
  }
}

function captureEntry(report) {
  const view = report?.view || {};
  const selected = report?.selectedMessage || {};
  const key =
    view.captureKey ||
    [view.url, view.subject, view.sender, view.bodyPreview].filter(Boolean).join(" | ");

  return {
    key,
    storedAt: new Date().toISOString(),
    report,
    triageLabel: report?.triageLabel || "Inbox Triage",
    subject: selected?.subject || view.subject || "",
    sender: selected?.sender || view.sender || ""
  };
}

async function ingestCapture(endpoint, report) {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(report)
  });
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { raw: text };
  }
  if (!response.ok) {
    throw new Error(payload?.error || `HTTP ${response.status}`);
  }
  return payload;
}

async function storeCapture(report) {
  if (!report?.view?.captureKey) {
    return { ok: false, stored: false, reason: "missing capture key" };
  }
  if (!isMeaningfulCapture(report)) {
    return { ok: true, stored: false, ignored: true, reason: "capture did not look like a message view" };
  }

  const current = await chrome.storage.local.get([
    CAPTURE_HISTORY_KEY,
    INGEST_ENABLED_KEY,
    INGEST_ENDPOINT_KEY
  ]);
  const history = Array.isArray(current[CAPTURE_HISTORY_KEY]) ? current[CAPTURE_HISTORY_KEY] : [];
  const entry = captureEntry(report);
  const existing = history.find(item => item.key === entry.key);

  if (existing) {
    await chrome.storage.local.set({ triageLastCapture: report });
    return { ok: true, stored: false, duplicate: true };
  }

  const nextHistory = [entry, ...history].slice(0, 100);
  await chrome.storage.local.set({
    [CAPTURE_HISTORY_KEY]: nextHistory,
    triageLastCapture: report
  });

  const ingestEnabled = current[INGEST_ENABLED_KEY] !== false;
  const endpoint = current[INGEST_ENDPOINT_KEY] || DEFAULT_INGEST_ENDPOINT;
  if (!ingestEnabled || !endpoint) {
    return { ok: true, stored: true, duplicate: false, ingest: { enabled: false } };
  }

  try {
    const payload = await ingestCapture(endpoint, report);
    return {
      ok: true,
      stored: true,
      duplicate: false,
      ingest: { enabled: true, ok: true, endpoint, payload }
    };
  } catch (error) {
    return {
      ok: true,
      stored: true,
      duplicate: false,
      ingest: { enabled: true, ok: false, endpoint, error: String(error?.message || error) }
    };
  }
}

chrome.runtime.onInstalled.addListener(async () => {
  await ensureDefaults();
});

chrome.runtime.onStartup?.addListener(async () => {
  await ensureDefaults();
});

chrome.action.onClicked?.addListener(async tab => {
  if (!tab?.id) return;
  await chrome.tabs.sendMessage(tab.id, { type: "triage:toggle-panel" });
});

chrome.commands.onCommand.addListener(async command => {
  if (command !== "toggle-panel") return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;
  await chrome.tabs.sendMessage(tab.id, { type: "triage:toggle-panel" });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "triage:save-rules") {
    chrome.storage.local.set(
      {
        triageRules: message.rules,
        triageLabel: message.label || "Inbox Triage"
      },
      () => sendResponse({ ok: true })
    );
    return true;
  }

  if (message?.type === "triage:store-capture") {
    storeCapture(message.report)
      .then(payload => sendResponse(payload))
      .catch(error => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }

  if (message?.type === "triage:get-capture-history") {
    chrome.storage.local.get([CAPTURE_HISTORY_KEY, INGEST_ENABLED_KEY, INGEST_ENDPOINT_KEY], value => {
      sendResponse({
        ok: true,
        history: Array.isArray(value[CAPTURE_HISTORY_KEY]) ? value[CAPTURE_HISTORY_KEY] : [],
        ingestEnabled: value[INGEST_ENABLED_KEY] !== false,
        ingestEndpoint: value[INGEST_ENDPOINT_KEY] || DEFAULT_INGEST_ENDPOINT
      });
    });
    return true;
  }

  return false;
});
