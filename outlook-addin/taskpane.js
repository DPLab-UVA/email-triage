const STORAGE_KEY = "email-triage.policy.v1";
const DEFAULT_POLICY_URL = "./config/triage-policy.json";

const state = {
  policy: null,
  snapshot: null,
  analysis: null,
};

function $(id) {
  return document.getElementById(id);
}

function log(message) {
  const node = $("activityLog");
  node.textContent = `${new Date().toLocaleTimeString()}\n${message}\n\n${node.textContent}`.trim();
}

function setStatus(text) {
  $("hostBadge").textContent = text;
}

function normalizeText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9@._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function tokenize(value) {
  return new Set(normalizeText(value).split(" ").filter(Boolean));
}

function toLines(value, fallback = "") {
  const text = Array.isArray(value) ? value.join(", ") : value || fallback;
  return text || fallback;
}

async function safeGetAsync(target, method, ...args) {
  if (!target || typeof target[method] !== "function") {
    return "";
  }
  return new Promise((resolve) => {
    target[method](...args, (result) => {
      if (result.status === Office.AsyncResultStatus.Succeeded) {
        resolve(result.value ?? "");
      } else {
        resolve("");
      }
    });
  });
}

async function getRecipientList(item, field) {
  const direct = item?.[field];
  if (Array.isArray(direct)) {
    return direct.map((r) => r.emailAddress?.address || r.address || r.displayName || "").filter(Boolean);
  }
  if (direct && typeof direct.getAsync === "function") {
    const result = await safeGetAsync(direct, "getAsync");
    if (Array.isArray(result)) {
      return result.map((r) => r.emailAddress?.address || r.address || r.displayName || "").filter(Boolean);
    }
  }
  return [];
}

function renderSnapshot(snapshot) {
  const rows = [
    ["Mode", snapshot.mode],
    ["Type", snapshot.itemType],
    ["Subject", snapshot.subject],
    ["From", snapshot.from],
    ["To", snapshot.to],
    ["Cc", snapshot.cc],
    ["Keywords", snapshot.keywords.join(", ") || "none"],
    ["Body preview", snapshot.bodyPreview || "empty"],
  ];
  $("itemSummary").innerHTML = rows
    .map(
      ([label, value]) => `
      <div class="row-line">
        <div class="label">${label}</div>
        <div class="value">${escapeHtml(value || "n/a")}</div>
      </div>`
    )
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function scoreAgainstPolicy(snapshot, policy) {
  const text = normalizeText([snapshot.subject, snapshot.from, snapshot.to, snapshot.cc, snapshot.bodyPreview].join(" "));
  const tokens = tokenize(text);
  const reasons = [];
  let score = 0;

  for (const sender of policy.vipSenders || []) {
    if (text.includes(normalizeText(sender))) {
      score += 35;
      reasons.push(`VIP sender match: ${sender}`);
    }
  }

  for (const rule of policy.positiveKeywords || []) {
    if (text.includes(normalizeText(rule.term))) {
      score += Number(rule.weight || 0);
      reasons.push(`Positive keyword "${rule.term}"`);
    }
  }

  for (const rule of policy.negativeKeywords || []) {
    if (text.includes(normalizeText(rule.term))) {
      score += Number(rule.weight || 0);
      reasons.push(`Negative keyword "${rule.term}"`);
    }
  }

  const examples = policy.examples || [];
  let bestExample = null;
  let bestOverlap = 0;
  for (const example of examples) {
    const exampleTokens = tokenize([example.subject, example.body].join(" "));
    const overlap = [...tokens].filter((token) => exampleTokens.has(token)).length;
    if (overlap > bestOverlap) {
      bestOverlap = overlap;
      bestExample = example;
    }
  }

  if (bestExample) {
    const boost = bestExample.label === "important" ? 18 : bestExample.label === "needs_reply" ? 12 : -20;
    score += boost;
    reasons.push(`Closest sample: ${bestExample.label} (${bestOverlap} token overlap)`);
  }

  score = Math.max(0, Math.min(100, Math.round(score)));

  let decision = "review";
  if (score >= policy.importanceThreshold) {
    decision = "important";
  } else if (score <= policy.ignoreThreshold) {
    decision = "ignore";
  }

  return {
    score,
    decision,
    reasons,
    bestExample,
  };
}

function buildDraft(snapshot, analysis, policy) {
  const templates = policy.draftTemplates || {};
  if (analysis.decision === "ignore") {
    return {
      title: "No reply draft",
      body: templates.ignore || "No reply needed.",
    };
  }

  const subject = snapshot.subject || "this";
  const summary = snapshot.bodyPreview || "the request";
  const nextStep = snapshot.subject ? `the request in "${subject}"` : "the request";
  const base =
    analysis.decision === "important"
      ? templates.important || "Thanks for the update. I will review this and respond shortly."
      : templates.needs_reply || "Thanks for reaching out. I will follow up shortly.";

  return {
    title: analysis.decision === "important" ? "Priority reply draft" : "Suggested reply draft",
    body: base
      .replace("{summary}", summary)
      .replace("{next_step}", nextStep)
      .trim(),
  };
}

async function captureCurrentItem() {
  const item = Office.context.mailbox.item;
  if (!item) {
    throw new Error("No current Outlook item is available.");
  }

  const subject = typeof item.subject === "string" ? item.subject : await safeGetAsync(item.subject, "getAsync");
  const body = item.body ? await safeGetAsync(item.body, "getAsync", Office.CoercionType.Text) : "";
  const fromValue = item.from?.emailAddress?.address || item.sender?.emailAddress?.address || item.from?.displayName || item.sender?.displayName || "";
  const to = await getRecipientList(item, "to");
  const cc = await getRecipientList(item, "cc");
  const keywords = [...tokenize(`${subject} ${body}`)].slice(0, 24);

  return {
    mode: Office.context.mailbox.item?.itemType || "message",
    itemType: Office.context.mailbox.item?.itemType || "unknown",
    subject: subject || "(no subject)",
    from: fromValue || "unknown sender",
    to: toLines(to),
    cc: toLines(cc),
    bodyPreview: body.replace(/\s+/g, " ").trim().slice(0, 260),
    body,
    keywords,
  };
}

function renderAnalysis(snapshot, analysis, draft) {
  $("triageResult").innerHTML = `
    <strong>${analysis.decision.toUpperCase()}</strong> · score ${analysis.score}/100
    <br />
    <span class="muted">This is a local heuristic decision, not a real model call.</span>
    <br /><br />
    ${analysis.reasons.map((reason) => `- ${escapeHtml(reason)}`).join("<br />")}
  `;

  $("draftResult").textContent = `${draft.title}\n\n${draft.body}`;
  log(`Analyzed "${snapshot.subject}" -> ${analysis.decision} (${analysis.score}/100)`);
}

async function ensurePolicy() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) {
    return JSON.parse(saved);
  }
  const response = await fetch(DEFAULT_POLICY_URL);
  return response.json();
}

function persistPolicy(policy) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(policy, null, 2));
}

function updatePolicyEditor(policy) {
  $("policyEditor").value = JSON.stringify(policy, null, 2);
}

async function refreshSnapshot() {
  state.snapshot = await captureCurrentItem();
  renderSnapshot(state.snapshot);
  log(`Loaded current item: ${state.snapshot.subject}`);
}

async function runAnalysis() {
  if (!state.snapshot) {
    await refreshSnapshot();
  }
  state.analysis = scoreAgainstPolicy(state.snapshot, state.policy);
  const draft = buildDraft(state.snapshot, state.analysis, state.policy);
  renderAnalysis(state.snapshot, state.analysis, draft);
  return draft;
}

async function insertDraft() {
  const draft = await runAnalysis();
  const item = Office.context.mailbox.item;
  if (item?.body && typeof item.body.setAsync === "function") {
    await new Promise((resolve, reject) => {
      item.body.setAsync(
        draft.body,
        { coercionType: Office.CoercionType.Text },
        (result) => {
          if (result.status === Office.AsyncResultStatus.Succeeded) {
            resolve();
          } else {
            reject(new Error(result.error?.message || "Failed to insert draft into the compose body."));
          }
        }
      );
    });
    log("Inserted the generated draft into the compose body.");
    return;
  }

  if (item && typeof item.displayReplyForm === "function") {
    item.displayReplyForm({
      htmlBody: `<div style="font-family:Segoe UI, sans-serif; white-space:pre-wrap;">${escapeHtml(draft.body)}</div>`,
    });
    log("Opened a native reply form with the generated draft.");
    return;
  }

  log("Draft is ready. Copy it into a reply manually on this client.");
}

function labelCurrentItem(label) {
  if (!state.snapshot) {
    throw new Error("Load an item before labeling it.");
  }
  state.policy.examples = state.policy.examples || [];
  state.policy.examples.unshift({
    label,
    subject: state.snapshot.subject,
    body: state.snapshot.body || state.snapshot.bodyPreview || "",
    reply: label === "ignore" ? "" : $("draftResult").textContent || "",
  });
  persistPolicy(state.policy);
  updatePolicyEditor(state.policy);
  log(`Labeled current item as ${label} and saved it to local training samples.`);
}

function wireButton(id, handler) {
  $(id).addEventListener("click", async () => {
    try {
      await handler();
    } catch (error) {
      log(`Error: ${error.message}`);
    }
  });
}

async function main() {
  setStatus("Office.js ready");
  state.policy = await ensurePolicy();
  updatePolicyEditor(state.policy);
  await refreshSnapshot();
  await runAnalysis();

  wireButton("refreshButton", refreshSnapshot);
  wireButton("triageButton", runAnalysis);
  wireButton("applyDraftButton", insertDraft);
  wireButton("copyDraftButton", async () => {
    const text = $("draftResult").textContent || "";
    await navigator.clipboard.writeText(text);
    log("Copied the draft text to clipboard.");
  });
  wireButton("labelImportantButton", async () => labelCurrentItem("important"));
  wireButton("labelIgnoreButton", async () => labelCurrentItem("ignore"));
  wireButton("savePolicyButton", async () => {
    state.policy = JSON.parse($("policyEditor").value);
    persistPolicy(state.policy);
    log("Saved policy JSON to localStorage.");
  });
  wireButton("resetPolicyButton", async () => {
    localStorage.removeItem(STORAGE_KEY);
    state.policy = await ensurePolicy();
    updatePolicyEditor(state.policy);
    log("Reset to the bundled default policy.");
  });
}

Office.onReady((info) => {
  if (info.host !== Office.HostType.Outlook) {
    setStatus("Not Outlook");
    return;
  }
  main().catch((error) => {
    setStatus("Startup error");
    log(error.message);
  });
});
