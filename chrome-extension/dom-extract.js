const PLACEHOLDER_TEXT = new Set([
  "subject",
  "from",
  "to",
  "cc",
  "bcc",
  "received",
  "attachments"
]);

const UI_NOISE_PATTERNS = [
  /new mail/i,
  /reply all/i,
  /quick steps/i,
  /navigation pane/i,
  /assign policy/i,
  /report message/i,
  /categories applied/i,
  /mark this message as read or unread/i,
  /move this message to your archive folder/i,
  /create a new email message/i
];

function normalizeWhitespace(value) {
  return String(value || "")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function sanitizeBodyText(value) {
  return normalizeWhitespace(
    String(value || "")
      .replace(/<!--[\s\S]*?-->/g, " ")
      .replace(/\.[A-Za-z0-9_-]+\s*\{[^}]*\}/g, " ")
      .replace(/[A-Za-z0-9_.#:-]+\s*\{[^}]*\}/g, " ")
      .replace(/\b(?:margin|padding|font-size|font-family|line-height|color|background(?:-color)?|display|border|width|height|text-align|letter-spacing)\s*:\s*[^;]+;/gi, " ")
      .replace(/^[^\w@<]*(view this email in your browser\s*)?/i, "")
  );
}

function looksLikeSender(text) {
  const normalized = normalizeWhitespace(text);
  if (!normalized) return false;
  if (PLACEHOLDER_TEXT.has(normalized.toLowerCase())) return false;
  if (/^[^\p{L}\p{N}@]+$/u.test(normalized)) return false;
  if (normalized.length < 2) return false;
  return /[A-Za-z]{2,}|@/.test(normalized);
}

function inferSenderFromBody(bodyText) {
  const text = normalizeWhitespace(bodyText);
  if (!text) return "";

  const signoffMatch = text.match(
    /(?:warm regards|best regards|kind regards|regards|best|thanks|thank you)[, ]+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){0,4})/i
  );
  if (signoffMatch) {
    return normalizeWhitespace(signoffMatch[1]);
  }

  const deanMatch = text.match(/warm regards,\s*([A-Z][A-Za-z.\-'\s]{2,80}),\s*Dean/i);
  if (deanMatch) {
    return normalizeWhitespace(deanMatch[1]);
  }

  return "";
}

function scoreText(text) {
  const normalized = normalizeWhitespace(text);
  if (!normalized) return -1000;
  const lower = normalized.toLowerCase();
  if (PLACEHOLDER_TEXT.has(lower)) return -500;

  let score = Math.min(normalized.length, 240);
  if (normalized.length < 4) score -= 50;
  if (normalized.length > 220) score -= 80;
  if (/@/.test(normalized)) score += 20;
  if (/[A-Za-z]{3,}/.test(normalized)) score += 10;
  if (/[.!?]/.test(normalized)) score -= 20;
  if (UI_NOISE_PATTERNS.some(pattern => pattern.test(normalized))) score -= 150;
  return score;
}

function uniqueTexts(nodes) {
  const seen = new Set();
  const texts = [];
  for (const node of nodes) {
    const text = normalizeWhitespace(node?.textContent);
    if (!text) continue;
    if (seen.has(text)) continue;
    seen.add(text);
    texts.push(text);
  }
  return texts;
}

function collectCandidates(root, selectors) {
  const nodes = [];
  for (const selector of selectors) {
    for (const node of root.querySelectorAll(selector)) {
      nodes.push(node);
    }
  }
  return nodes;
}

function pickBestText(root, selectors) {
  const candidates = uniqueTexts(collectCandidates(root, selectors))
    .map(text => ({ text, score: scoreText(text) }))
    .filter(entry => entry.score > -100);
  candidates.sort((left, right) => right.score - left.score);
  return candidates[0]?.text || "";
}

function candidateText(node) {
  return sanitizeBodyText(node?.innerText || node?.textContent || "");
}

function bodyScore(text) {
  if (!text) return -1000;
  let score = Math.min(text.length, 500);
  const lower = text.toLowerCase();
  if (text.length < 80) score -= 300;
  if (/@/.test(text)) score += 10;
  if (/(hi|hello|dear|thanks|best|regards)\b/i.test(text)) score += 80;
  if (/\b(march|april|may|june|july|august|september|october|november|december)\b/i.test(text)) score += 20;
  if ((text.match(/[.?!]/g) || []).length >= 2) score += 30;
  if (UI_NOISE_PATTERNS.some(pattern => pattern.test(lower))) score -= 250;
  if (/\bfilehomehomeviewviewhelphelp\b/i.test(lower)) score -= 300;
  return score;
}

function pickBodyNode(root) {
  const selectors = [
    '[data-testid*="message-body"]',
    '[aria-label*="message body" i]',
    '[aria-label*="reading pane" i]',
    '[role="document"]',
    'article',
    'main'
  ];

  const candidates = [];
  for (const node of collectCandidates(root, selectors)) {
    const text = candidateText(node);
    const score = bodyScore(text);
    if (score > -200) {
      candidates.push({ node, text, score });
    }
  }

  candidates.sort((left, right) => right.score - left.score);
  return candidates[0] || { node: root, text: "", score: -1000 };
}

function selectedRow(root) {
  const rows = Array.from(root.querySelectorAll('[aria-selected="true"], [aria-current="true"]'));
  const candidates = rows
    .map(node => {
      const texts = uniqueTexts([node, ...Array.from(node.querySelectorAll("span, div, button, a"))])
        .filter(text => scoreText(text) > -50)
        .slice(0, 12);
      const joined = normalizeWhitespace(texts.join(" | "));
      if (!joined) return null;

      let score = scoreText(joined);
      if (texts.length >= 2) score += 35;
      if (/\b(?:am|pm|today|yesterday|\d{1,2}:\d{2})\b/i.test(joined)) score += 20;
      if (/^(home|inbox|sent|drafts)$/i.test(joined)) score -= 250;
      if (joined.length < 20) score -= 120;

      const sender = texts.find(looksLikeSender) || texts[0] || "";
      const subject =
        texts.find(text => text !== sender && !/^(home|inbox|sent|drafts)$/i.test(text)) ||
        texts.find(text => text !== sender) ||
        "";

      return {
        text: joined,
        sender,
        subject,
        score
      };
    })
    .filter(Boolean)
    .sort((left, right) => right.score - left.score);

  return candidates[0] || null;
}

function headerRootFromBody(bodyNode) {
  if (!bodyNode) return document;
  return bodyNode.closest('[role="main"], article, section, div') || document;
}

function visibleTextSnapshot(root) {
  const bodyCandidate = pickBodyNode(root);
  const headerRoot = headerRootFromBody(bodyCandidate.node);
  const selected = selectedRow(root);

  const subject =
    pickBestText(headerRoot, [
      '[data-testid*="conversation-subject"]',
      '[data-testid*="subject"]',
      '[role="heading"]',
      'h1',
      'h2'
    ]) ||
    selected?.subject ||
    "";

  let sender =
    pickBestText(headerRoot, [
      '[data-testid*="sender"]',
      '[data-testid*="from"]',
      '[aria-label^="From" i]',
      '[title*="@"]',
      'button[title]',
      'span[title]'
    ]) ||
    selected?.sender ||
    "";

  const bodyText = bodyCandidate.text.slice(0, 20000);
  if (!looksLikeSender(sender)) {
    sender = inferSenderFromBody(bodyText) || "";
  }
  const bodyPreview = bodyText.slice(0, 1000);
  const captureKey = [
    location.pathname,
    subject,
    sender,
    bodyPreview.slice(0, 240)
  ]
    .map(part => normalizeWhitespace(part))
    .filter(Boolean)
    .join(" | ");

  return {
    subject,
    sender,
    bodyText,
    bodyPreview,
    snippets: [selected?.text, bodyPreview].filter(Boolean),
    selectedRowText: selected?.text || "",
    url: location.href,
    capturedAt: new Date().toISOString(),
    captureKey
  };
}

function summarizeNode(node, index) {
  const texts = uniqueTexts([node, ...Array.from(node.querySelectorAll("span, div, a, button"))])
    .filter(text => scoreText(text) > -50);
  if (!texts.length) return null;

  const joined = normalizeWhitespace(texts.join(" | "));
  if (joined.length < 30) return null;
  if (UI_NOISE_PATTERNS.some(pattern => pattern.test(joined))) return null;

  const sender = texts[0] || "";
  const subject = texts.find(text => text !== sender) || joined.slice(0, 120);
  const snippet = texts.slice(2).join(" ").slice(0, 240) || joined.slice(0, 240);

  return {
    id: node.getAttribute("data-message-id") || node.id || `candidate-${index}`,
    text: joined,
    sender,
    subject,
    snippet
  };
}

function discoverVisibleMessages(root) {
  const candidates = Array.from(
    root.querySelectorAll(
      [
        '[aria-selected="true"]',
        '[role="option"]',
        '[role="listitem"]',
        '[data-message-id]',
        '[aria-label*="message" i]'
      ].join(",")
    )
  );

  const messages = [];
  const seen = new Set();
  candidates.forEach((node, index) => {
    const summary = summarizeNode(node, index);
    if (!summary) return;
    const dedupeKey = `${summary.sender}|${summary.subject}|${summary.snippet}`;
    if (seen.has(dedupeKey)) return;
    seen.add(dedupeKey);
    messages.push(summary);
  });

  return messages.slice(0, 30);
}

window.OutlookDomTriage = {
  visibleTextSnapshot,
  discoverVisibleMessages
};
