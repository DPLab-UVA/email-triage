const DEFAULT_RULES = [
  {
    id: "calendar",
    label: "Calendar / meetings",
    when: "subject or snippet mentions meeting, calendar, invite, zoom, teams, schedule",
    score: 3,
    action: "likely-important"
  },
  {
    id: "ops",
    label: "Ops / review / ticket",
    when: "hotcrp, submitted review, review #, helpdesk, cshd-, ticket, security alert, verification code, ci failed, follow-up",
    score: 3,
    action: "likely-important"
  },
  {
    id: "deadline",
    label: "Deadline / action",
    when: "urgent, deadline, action required, action advised, due, asap, pre-register",
    score: 3,
    action: "likely-important"
  },
  {
    id: "money",
    label: "Money / billing",
    when: "mentions invoice, payment, receipt, billing, bank, refund, tax",
    score: 3,
    action: "likely-important"
  },
  {
    id: "noise",
    label: "Marketing / auto",
    when: "newsletter, promotion, unsubscribe, digest, no-reply, automated, view this email in your browser, early-bird pricing, call for speakers, prices for your tracked flights",
    score: -3,
    action: "suppress-notification"
  }
];

function normalizeText(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function scoreAgainstRule(message, rule) {
  const haystack = normalizeText([
    message.subject,
    message.snippet,
    message.bodyText,
    message.bodyPreview,
    message.sender,
    message.from
  ].join(" "));

  const terms = String(rule.when || "")
    .split(",")
    .map(term => term.trim().toLowerCase())
    .filter(Boolean);

  let matched = false;
  let score = 0;
  for (const term of terms) {
    if (haystack.includes(term)) {
      matched = true;
      score += 1;
    }
  }

  return {
    matched,
    score: matched ? score * Math.sign(rule.score || 1) || rule.score || 0 : 0
  };
}

function inferReplyPrompt(message) {
  const subject = normalizeText(message.subject);
  const body = normalizeText(message.bodyText || message.bodyPreview || message.snippet || "");
  const combined = `${subject} ${body}`;

  if (combined.includes("meeting") || combined.includes("schedule") || combined.includes("calendar")) {
    return "Draft a concise reply confirming availability, proposing a time, and asking for an agenda if missing.";
  }

  if (combined.includes("invoice") || combined.includes("billing") || combined.includes("payment")) {
    return "Draft a short reply asking for the invoice details, due date, and any required reference number.";
  }

  if (combined.includes("review #") || combined.includes("submitted review") || combined.includes("hotcrp")) {
    return "Draft a short acknowledgement that you saw the review update and will check the submission site shortly.";
  }

  if (combined.includes("helpdesk") || combined.includes("cshd-") || combined.includes("ticket")) {
    return "Draft a short reply acknowledging the ticket update and confirming the next action or missing detail.";
  }

  if (combined.includes("security alert") || combined.includes("verification code")) {
    return "Draft a short security reply only if needed; otherwise treat this as an account alert that may need immediate manual review.";
  }

  if (combined.includes("interview") || combined.includes("apply") || combined.includes("application")) {
    return "Draft a professional reply acknowledging receipt and asking for the next steps or timeline.";
  }

  return "Draft a brief, polite reply that acknowledges the message and asks the minimum clarifying question needed.";
}

function triageMessage(message, rules = DEFAULT_RULES) {
  const normalizedRules = Array.isArray(rules) && rules.length ? rules : DEFAULT_RULES;
  const matches = normalizedRules
    .map(rule => ({ rule, result: scoreAgainstRule(message, rule) }))
    .filter(entry => entry.result.matched);

  const score = matches.reduce((sum, entry) => sum + entry.result.score, 0);
  const shouldSuppress = matches.some(entry => entry.rule.action === "suppress-notification");
  const likelyImportant = score >= 2 || (!shouldSuppress && score > 0);

  return {
    ...message,
    triageScore: score,
    importance: shouldSuppress ? "suppress" : likelyImportant ? "important" : "review",
    matchedRules: matches.map(entry => ({
      id: entry.rule.id,
      label: entry.rule.label,
      action: entry.rule.action
    })),
    draftPrompt: inferReplyPrompt(message)
  };
}

function triageInbox(messages, rules) {
  return (messages || []).map(message => triageMessage(message, rules));
}

window.EmailTriageCore = {
  DEFAULT_RULES,
  triageMessage,
  triageInbox,
  inferReplyPrompt
};
