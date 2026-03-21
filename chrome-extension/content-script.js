const PANEL_ID = "triage-panel-root";
const STORAGE_KEY = "triagePanelEnabled";

let panelVisible = false;
let extensionContextAlive = true;
let observer = null;
let rerenderTimer = null;
let lastReport = null;
let lastPersistedCaptureKey = "";

function removeExistingPanel() {
  const root = document.getElementById(PANEL_ID);
  if (root) {
    root.remove();
  }
}

function snapshot() {
  return window.OutlookDomTriage.visibleTextSnapshot(document);
}

function isContextInvalidated(error) {
  return String(error?.message || error).includes("Extension context invalidated");
}

function markContextInvalid(error) {
  if (!isContextInvalidated(error)) return false;
  extensionContextAlive = false;
  if (observer) observer.disconnect();
  if (rerenderTimer) {
    clearTimeout(rerenderTimer);
    rerenderTimer = null;
  }
  if (panelVisible) {
    renderStatusPanel("Extension reloaded. Refresh the Outlook tab once, then capture again.");
  }
  return true;
}

async function safeStorageGet(keys) {
  try {
    return await chrome.storage.local.get(keys);
  } catch (error) {
    if (markContextInvalid(error)) {
      return {};
    }
    throw error;
  }
}

async function safeStorageSet(payload) {
  try {
    await chrome.storage.local.set(payload);
  } catch (error) {
    if (!markContextInvalid(error)) {
      throw error;
    }
  }
}

async function awaitLocalRules() {
  return safeStorageGet(["triageRules", "triageLabel"]).then(({ triageRules, triageLabel }) => {
    const rules = Array.isArray(triageRules) && triageRules.length
      ? triageRules
      : window.EmailTriageCore.DEFAULT_RULES;
    return {
      triageRules: rules,
      triageLabel: triageLabel || "Inbox Triage"
    };
  });
}

async function scan() {
  const base = snapshot();
  const messages = window.OutlookDomTriage.discoverVisibleMessages(document);
  const { triageRules, triageLabel } = await awaitLocalRules();
  const selectedMessage = window.EmailTriageCore.triageMessage(
    {
      id: base.captureKey || base.url,
      subject: base.subject,
      sender: base.sender,
      from: base.sender,
      snippet: base.bodyPreview,
      bodyPreview: base.bodyPreview,
      bodyText: base.bodyText
    },
    triageRules
  );
  const triaged = window.EmailTriageCore.triageInbox(
    messages.map(message => ({
      ...message,
      bodyPreview: message.snippet,
      bodyText: "",
      from: message.sender || base.sender
    })),
    triageRules
  );

  return {
    view: base,
    messages: triaged,
    selectedMessage,
    triageLabel
  };
}

async function persistReport(report) {
  const captureKey = report?.view?.captureKey || "";
  if (!captureKey || captureKey === lastPersistedCaptureKey) {
    return { ok: true, stored: false, duplicate: true };
  }
  try {
    const response = await chrome.runtime.sendMessage({ type: "triage:store-capture", report });
    if (response?.ok) {
      lastPersistedCaptureKey = captureKey;
    }
    return response;
  } catch (error) {
    if (!markContextInvalid(error)) {
      throw error;
    }
    return { ok: false, error: "Extension context invalidated" };
  }
}

function ensurePanel() {
  let root = document.getElementById(PANEL_ID);
  if (root) return root;

  root = document.createElement("aside");
  root.id = PANEL_ID;
  root.innerHTML = `
    <div class="triage-shell">
      <div class="triage-header">
        <div>
          <div class="triage-kicker">Auto capture active</div>
          <h1>Outlook Triage</h1>
        </div>
        <button type="button" data-action="close">Hide</button>
      </div>
      <div class="triage-body">
        <div class="triage-status">Waiting for a message view...</div>
      </div>
      <div class="triage-footer">
        <button type="button" data-action="refresh">Capture now</button>
      </div>
    </div>
  `;

  root.querySelector('[data-action="close"]').addEventListener("click", () => {
    setPanelVisible(false).catch(() => {});
    root.classList.add("triage-hidden");
  });

  root.querySelector('[data-action="refresh"]').addEventListener("click", async () => {
    await captureAndMaybeRender({ renderPanelNow: true, persist: true });
  });

  document.documentElement.appendChild(root);
  return root;
}

function renderStatusPanel(message) {
  if (!panelVisible) return;
  const root = ensurePanel();
  root.classList.remove("triage-hidden");
  const body = root.querySelector(".triage-body");
  body.innerHTML = `
    <div class="triage-section">
      <div class="triage-section-title">Status</div>
      <div>${escapeHtml(message)}</div>
    </div>
  `;
}

function renderPanel(report) {
  if (!panelVisible) return;
  const root = ensurePanel();
  root.classList.remove("triage-hidden");
  const body = root.querySelector(".triage-body");
  const label = report?.selectedMessage?.importance || "review";
  const messages = report?.messages || [];
  const title = report?.triageLabel || "Inbox Triage";
  const topMatches = messages.slice(0, 5);

  body.innerHTML = `
    <div class="triage-summary triage-${label}">
      <div><strong>${escapeHtml(title)}</strong></div>
      <div>${escapeHtml(report?.view?.subject || "No visible subject")}</div>
      <div>${escapeHtml(report?.view?.sender || "Unknown sender")}</div>
      <div class="triage-muted">${escapeHtml(report?.view?.url || location.href)}</div>
    </div>
    <div class="triage-section">
      <div class="triage-section-title">Current Decision</div>
      <div><strong>${escapeHtml(report?.selectedMessage?.importance || "review")}</strong></div>
      <div>${escapeHtml(report?.selectedMessage?.draftPrompt || "No draft hint yet.")}</div>
    </div>
    <div class="triage-section">
      <div class="triage-section-title">Nearby Messages</div>
      <ul>
        ${topMatches.map(message => `
          <li>
            <strong>${escapeHtml(message.subject || "(no subject)")}</strong>
            <span>${escapeHtml(message.importance)}</span>
            <div>${escapeHtml(message.sender || "")}</div>
          </li>
        `).join("")}
      </ul>
    </div>
  `;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function setPanelVisible(nextValue) {
  panelVisible = Boolean(nextValue);
  await safeStorageSet({ [STORAGE_KEY]: panelVisible });
}

async function captureAndMaybeRender({ renderPanelNow = panelVisible, persist = true } = {}) {
  if (!extensionContextAlive) {
    if (panelVisible) {
      renderStatusPanel("Extension reloaded. Refresh the Outlook tab once, then capture again.");
    }
    return {
      ok: false,
      error: "Extension context invalidated"
    };
  }

  const report = await scan();
  lastReport = report;
  if (persist) {
    await persistReport(report);
  }
  if (renderPanelNow) {
    renderPanel(report);
  }
  return report;
}

async function boot() {
  const value = await safeStorageGet([STORAGE_KEY]);
  panelVisible = false;
  removeExistingPanel();
  if (value[STORAGE_KEY] === true) {
    await safeStorageSet({ [STORAGE_KEY]: false });
  }
  await captureAndMaybeRender({ renderPanelNow: false, persist: true }).catch(error => {
    markContextInvalid(error);
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!extensionContextAlive) {
    sendResponse({ ok: false, error: "Extension context invalidated. Refresh the Outlook tab." });
    return false;
  }

  if (message?.type === "triage:ping") {
    sendResponse({ ok: true, url: location.href });
    return false;
  }

  if (message?.type === "triage:toggle-panel") {
    setPanelVisible(!panelVisible)
      .then(() => {
        if (!panelVisible) {
          const root = document.getElementById(PANEL_ID);
          if (root) root.classList.add("triage-hidden");
          sendResponse({ ok: true, report: lastReport });
          return;
        }
        return captureAndMaybeRender({ renderPanelNow: true, persist: true })
          .then(report => sendResponse({ ok: true, report }));
      })
      .catch(error => {
        if (markContextInvalid(error)) {
          sendResponse({ ok: false, error: "Extension context invalidated. Refresh the Outlook tab." });
          return;
        }
        sendResponse({ ok: false, error: String(error?.message || error) });
      });
    return true;
  }

  if (message?.type === "triage:capture") {
    captureAndMaybeRender({ renderPanelNow: panelVisible, persist: true })
      .then(report => sendResponse({ ok: true, report }))
      .catch(error => {
        if (markContextInvalid(error)) {
          sendResponse({ ok: false, error: "Extension context invalidated. Refresh the Outlook tab." });
          return;
        }
        sendResponse({ ok: false, error: String(error?.message || error) });
      });
    return true;
  }

  if (message?.type === "triage:get-snapshot") {
    const report = snapshot();
    sendResponse({ ok: true, report });
    return false;
  }

  return false;
});

boot().catch(error => {
  markContextInvalid(error);
});

observer = new MutationObserver(mutations => {
  if (!extensionContextAlive) return;
  const root = document.getElementById(PANEL_ID);
  const changedOutsidePanel = mutations.some(mutation => {
    const target = mutation.target;
    return !root || !target || (target instanceof Node && !root.contains(target));
  });
  if (!changedOutsidePanel) return;
  if (rerenderTimer) clearTimeout(rerenderTimer);
  rerenderTimer = setTimeout(() => {
    captureAndMaybeRender({ renderPanelNow: panelVisible, persist: true }).catch(error => {
      markContextInvalid(error);
    });
  }, 400);
});

observer.observe(document.documentElement, {
  subtree: true,
  childList: true,
  characterData: true
});
