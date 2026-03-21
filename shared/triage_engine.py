#!/usr/bin/env python3
"""Rule- and example-driven email triage engine."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

WORD_RE = re.compile(r"[A-Za-z0-9_@.+-]+")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


def sender_email(sender: str) -> str:
    match = re.search(r"<([^>]+)>", sender or "")
    if match:
        return match.group(1).strip().lower()
    inline_match = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", sender or "", re.I)
    if inline_match:
        return inline_match.group(0).strip().lower()
    return normalize_text(sender).lower()


def sender_name(sender: str) -> str:
    sender = normalize_text(sender)
    match = re.match(r"(.+?)\s*<[^>]+>", sender)
    if match:
        return match.group(1).strip()
    return sender.split("@", 1)[0].replace(".", " ").title() if "@" in sender else sender


def domain_of(address: str) -> str:
    if "@" not in address:
        return ""
    return address.split("@", 1)[1].lower()


def tokenize(*values: str) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for token in WORD_RE.findall(value.lower()):
            tokens.add(token)
    return tokens


def keyword_matches(keywords: list[str], haystack: str) -> list[str]:
    lower_haystack = haystack.lower()
    return [keyword for keyword in keywords if keyword.lower() in lower_haystack]


def override_matches(override: dict[str, Any], *, sender: str, sender_addr: str, subject: str, body: str) -> bool:
    sender_text = normalize_text(sender).lower()
    sender_addr_text = normalize_text(sender_addr).lower()
    subject_text = normalize_text(subject).lower()
    body_text = normalize_text(body).lower()

    sender_contains = normalize_text(override.get("sender_contains")).lower()
    subject_contains = normalize_text(override.get("subject_contains")).lower()
    body_contains = normalize_text(override.get("body_contains")).lower()

    if sender_contains and sender_contains not in sender_text and sender_contains not in sender_addr_text:
        return False
    if subject_contains and subject_contains not in subject_text:
        return False
    if body_contains and body_contains not in body_text:
        return False
    return any([sender_contains, subject_contains, body_contains])


def similarity_score(message_text: str, example: dict[str, Any]) -> float:
    left = tokenize(message_text)
    right = tokenize(example.get("subject", ""), example.get("body", ""), example.get("from", ""))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def infer_category(subject: str, body: str) -> str:
    text = f"{subject}\n{body}".lower()
    if any(token in text for token in ["invitation to review", "review invitation", "invited to review", "would you review"]) and any(
        token in text for token in ["journal", "manuscript", "editor", "associate editor", "referee"]
    ):
        return "review_invitation"
    if any(
        token in text
        for token in [
            "newsletter",
            "unsubscribe",
            "digest",
            "promotion",
            "sale",
            "view this email in your browser",
            "read more",
            "news highlights",
            "early-bird pricing",
            "call for speakers",
            "prices for your tracked flights",
        ]
    ):
        return "bulk"
    if any(token in text for token in ["security alert", "verification code", "code is", "2fa", "mfa"]):
        return "security"
    if any(token in text for token in ["helpdesk", "ticket", "cshd-", "reply above this line", "repair"]):
        return "ticket"
    if any(token in text for token in ["submitted review", "review #", "hotcrp", "microsoft cmt"]):
        return "review"
    if any(token in text for token in ["deadline", "due", "by friday", "by tomorrow", "asap"]):
        return "deadline"
    if any(token in text for token in ["meeting", "calendar", "schedule", "availability", "zoom"]):
        return "scheduling"
    if any(token in text for token in ["could you", "can you", "please send", "please review", "?"]):
        return "request"
    return "generic"


def build_draft(message: dict[str, Any], rules: dict[str, Any], category: str) -> str:
    prefs = rules.get("draft_preferences", {})
    sender = sender_name(message.get("from", ""))
    subject = normalize_text(message.get("subject"))
    signature = prefs.get("signature", "").strip()
    greeting = f"Hi {sender}," if sender else "Hi,"
    if category == "deadline":
        body = prefs.get("deadline_template", "Thanks for the reminder. I will take care of it promptly.")
    elif category == "scheduling":
        body = prefs.get("scheduling_template", "Thanks for reaching out. I am available [insert availability].")
    elif category == "review":
        body = "Thanks for the update. I saw the review-related message and will check the submission site shortly."
    elif category == "ticket":
        body = "Thanks for the update. I saw the ticket status and will follow up if any additional details are needed."
    elif category == "security":
        body = "Thanks for the alert. I saw the security-related message and will verify the account status right away."
    elif category == "review_invitation":
        body = "Thank you for the invitation. I am unavailable to review this manuscript."
    elif category == "request":
        body = prefs.get(
            "ask_for_clarification_template",
            "Thanks for the message. Could you clarify [insert missing detail] so I can respond accurately?",
        )
    else:
        body = prefs.get("generic_template", "Thanks for the message. I reviewed it and will follow up shortly.")
    lines = [greeting, "", body]
    if subject:
        lines.extend(["", f"Context: {subject}"])
    if signature:
        lines.extend(["", signature])
    return "\n".join(lines)


def triage_message(message: dict[str, Any], rules: dict[str, Any], examples: list[dict[str, Any]]) -> dict[str, Any]:
    subject = normalize_text(message.get("subject"))
    body = normalize_text(message.get("body"))
    sender = normalize_text(message.get("from"))
    sender_addr = sender_email(sender)
    sender_domain = domain_of(sender_addr)
    full_text = f"{subject}\n{body}"

    for override in rules.get("force_not_important", []):
        if override_matches(override, sender=sender, sender_addr=sender_addr, subject=subject, body=body):
            return {
                "important": False,
                "score": -99.0,
                "threshold": float(rules.get("priority_threshold", 4)),
                "action": "digest-later",
                "category": "override",
                "reasons": [f"forced not important: {override.get('reason', 'override')}"],
                "message": {
                    "from": sender,
                    "subject": subject,
                    "message_id": message.get("message_id", ""),
                    "mailbox_id": message.get("id", ""),
                },
                "draft_reply": "",
            }

    for override in rules.get("force_important", []):
        if override_matches(override, sender=sender, sender_addr=sender_addr, subject=subject, body=body):
            return {
                "important": True,
                "score": 99.0,
                "threshold": float(rules.get("priority_threshold", 4)),
                "action": "notify-and-draft",
                "category": "override",
                "reasons": [f"forced important: {override.get('reason', 'override')}"],
                "message": {
                    "from": sender,
                    "subject": subject,
                    "message_id": message.get("message_id", ""),
                    "mailbox_id": message.get("id", ""),
                },
                "draft_reply": build_draft(message, rules, "generic"),
            }

    score = 0.0
    reasons: list[str] = []

    important_senders = {value.lower() for value in rules.get("important_senders", [])}
    important_domains = {value.lower() for value in rules.get("important_domains", [])}
    ignore_senders = {value.lower() for value in rules.get("ignore_senders", [])}
    ignore_domains = {value.lower() for value in rules.get("ignore_domains", [])}

    if sender_addr in important_senders:
        score += 5
        reasons.append(f"important sender: {sender_addr}")
    if sender_domain in important_domains:
        score += 2
        reasons.append(f"important domain: {sender_domain}")
    if sender_addr in ignore_senders:
        score -= 5
        reasons.append(f"ignored sender: {sender_addr}")
    if sender_domain in ignore_domains:
        score -= 3
        reasons.append(f"ignored domain: {sender_domain}")

    important_hits = keyword_matches(rules.get("important_keywords", []), full_text)
    ignore_hits = keyword_matches(rules.get("ignore_keywords", []), full_text)

    if important_hits:
        score += min(4, len(important_hits) * 1.5)
        reasons.append(f"important keywords: {', '.join(sorted(set(important_hits)))}")
    if ignore_hits:
        score -= min(4, len(ignore_hits) * 1.5)
        reasons.append(f"ignore keywords: {', '.join(sorted(set(ignore_hits)))}")

    category = infer_category(subject, body)
    if category == "review_invitation":
        return {
            "important": False,
            "score": -50.0,
            "threshold": float(rules.get("priority_threshold", 4)),
            "action": "queue-auto-decline-review-invite",
            "category": category,
            "reasons": ["journal review invitation should be auto-declined for this user"],
            "message": {
                "from": sender,
                "subject": subject,
                "message_id": message.get("message_id", ""),
                "mailbox_id": message.get("id", ""),
            },
            "draft_reply": build_draft(message, rules, category),
        }
    if category in {"deadline", "request", "scheduling", "ticket", "review", "security"}:
        score += 1
        reasons.append(f"action-oriented category: {category}")
    if category == "bulk":
        score -= 2
        reasons.append("bulk-style content")

    best_example: dict[str, Any] | None = None
    best_similarity = 0.0
    for example in examples:
        similarity = similarity_score(full_text, example)
        if similarity > best_similarity:
            best_similarity = similarity
            best_example = example
    if best_example and best_similarity >= 0.15:
        if best_example.get("label") == "important":
            score += 2
        else:
            score -= 2
        reasons.append(
            f"similar to {best_example.get('label')} example ({best_similarity:.2f})"
        )

    threshold = float(rules.get("priority_threshold", 4))
    important = score >= threshold
    action = "notify-and-draft" if important else "digest-later"
    draft = build_draft(message, rules, category) if important else ""

    return {
        "important": important,
        "score": round(score, 2),
        "threshold": threshold,
        "action": action,
        "category": category,
        "reasons": reasons,
        "message": {
            "from": sender,
            "subject": subject,
            "message_id": message.get("message_id", ""),
            "mailbox_id": message.get("id", ""),
        },
        "draft_reply": draft,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify one email with rules and examples.")
    parser.add_argument("--rules", required=True, help="Path to rules JSON.")
    parser.add_argument("--examples", required=True, help="Path to labeled example JSONL.")
    parser.add_argument("--input", help="Path to one message JSON file. If omitted, read stdin.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rules = load_json(Path(args.rules))
    examples = load_jsonl(Path(args.examples))
    if args.input:
        with Path(args.input).open("r", encoding="utf-8") as handle:
            message = json.load(handle)
    else:
        message = json.load(sys.stdin)
    result = triage_message(message, rules, examples)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
