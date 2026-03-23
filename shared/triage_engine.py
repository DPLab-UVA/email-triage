#!/usr/bin/env python3
"""Rule- and example-driven email triage engine."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

WORD_RE = re.compile(r"[A-Za-z0-9_@.+-]+")
SHARED = Path(__file__).resolve().parent
ROOT = SHARED.parent
DEFAULT_LLM_SCHEMA = SHARED / "triage_llm_schema.json"
_CACHE_MEMO: dict[str, dict[str, Any]] = {}


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


def clipped_text(value: str | None, max_chars: int) -> str:
    text = normalize_text(value)
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " ..."


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


def load_cache(path: Path) -> dict[str, Any]:
    cache_key = str(path.resolve())
    if cache_key in _CACHE_MEMO:
        return _CACHE_MEMO[cache_key]
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _CACHE_MEMO[cache_key] = data
                return data
        except json.JSONDecodeError:
            pass
    _CACHE_MEMO[cache_key] = {}
    return _CACHE_MEMO[cache_key]


def save_cache(path: Path, cache: dict[str, Any]) -> None:
    cache_key = str(path.resolve())
    _CACHE_MEMO[cache_key] = cache
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def is_automated_sender(sender: str) -> bool:
    value = normalize_text(sender).lower()
    hints = [
        "noreply",
        "no-reply",
        "do-not-reply",
        "notification",
        "notifications",
        "editorial",
        "newsletter",
        "helpdesk",
        "hotcrp",
        "microsoft cmt",
        "google flights",
        "google scholar",
        "survey monkey",
        "surveymonkey",
        "bookstores",
        "workday",
    ]
    return any(token in value for token in hints)


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
    if (
        "expense report" in text
        and "submitted on your behalf" in text
        and "has been approved" not in text
    ):
        return "expense_approval"
    if any(
        token in text
        for token in [
            "reimbursement",
            "budget clarification",
            "travel reimbursement",
            "expense report",
            "award budget",
        ]
    ):
        return "finance_admin"
    if any(
        token in text
        for token in [
            "postdoctoral",
            "postdoc",
            "candidate",
            "research posting",
            "screen candidates",
            "hire",
            "hiring",
            "intake meeting",
        ]
    ):
        return "hiring"
    if any(
        token in text
        for token in [
            "jaguar04",
            "sds01",
            "research computing",
            "rc operations",
            "infrastructure",
            "prototype",
            "repair",
        ]
    ):
        return "infrastructure"
    if "speaker" in text and any(token in text for token in ["availability", "logistics", "apr ", "invite", "invitation", "confirm"]):
        return "speaker_logistics"
    if any(
        token in text
        for token in [
            "nvidia research",
            "project plan",
            "next steps",
            "follow-up on",
            "follow up on",
            "project",
        ]
    ):
        return "collaboration"
    if any(token in text for token in ["invitation to review", "review invitation", "invited to review", "would you review"]) and any(
        token in text for token in ["journal", "manuscript", "editor", "associate editor", "referee"]
    ):
        return "review_invitation"
    if any(
        token in text
        for token in [
            "invitation to contribute",
            "invitation to submit",
            "invite you to contribute",
            "call for papers",
            "submit your manuscript",
            "submit to section",
            "special invitation to prof",
            "special invitation to dr",
            "fee waiver",
            "manuscript consideration request",
            "share your research with our readers",
            "full apc waived",
            "apc waived",
            "waived apc",
        ]
    ):
        return "submission_invitation"
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
    if any(token in text for token in ["security alert", "verification code", "code is", "2fa", "mfa", "new login", "logged in to your account"]):
        return "security"
    if any(token in text for token in ["helpdesk", "ticket", "cshd-", "reply above this line", "repair"]):
        return "ticket"
    if any(token in text for token in ["submitted review", "review #", "hotcrp", "microsoft cmt"]):
        return "review"
    if any(token in text for token in ["deadline", "due", "by friday", "by tomorrow", "asap", "pre-register", "register by"]):
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
    elif category == "submission_invitation":
        body = "Thank you for the invitation. I will not be submitting to this venue."
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


def message_metadata(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "from": normalize_text(message.get("from")),
        "subject": normalize_text(message.get("subject")),
        "message_id": message.get("message_id", ""),
        "mailbox_id": message.get("id", ""),
    }


def broad_policy_summary(rules: dict[str, Any]) -> str:
    lines = [f"- {line}" for line in rules.get("decision_principles", []) if normalize_text(line)]
    return "\n".join(lines)


def heuristic_summary_for_prompt(heuristic: dict[str, Any]) -> str:
    parts = [
        f"sender_kind: {'human' if heuristic.get('human_sender') else 'automated_or_system'}",
        f"heuristic_category: {heuristic.get('category', 'generic')}",
        f"heuristic_bucket: {'important_notify' if heuristic.get('important') else 'night_digest'}",
        f"heuristic_score: {heuristic.get('score', 0.0)}",
    ]
    reasons = heuristic.get("reasons", [])
    if reasons:
        parts.append("heuristic_reasons: " + " | ".join(reasons[:6]))
    return "\n".join(parts)


def top_similar_examples(message_text: str, examples: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for example in examples:
        similarity = similarity_score(message_text, example)
        if similarity <= 0:
            continue
        scored.append((similarity, example))
    scored.sort(key=lambda item: item[0], reverse=True)
    rows: list[dict[str, Any]] = []
    for similarity, example in scored[:limit]:
        rows.append(
            {
                "label": example.get("label", ""),
                "from": normalize_text(example.get("from")),
                "subject": normalize_text(example.get("subject")),
                "similarity": round(similarity, 2),
            }
        )
    return rows


def llm_cache_key(message: dict[str, Any], rules: dict[str, Any]) -> str:
    llm_cfg = rules.get("llm_triage", {}) or {}
    payload = {
        "policy_version": rules.get("policy_version", 1),
        "provider": llm_cfg.get("provider", "codex"),
        "model": llm_cfg.get("model", ""),
        "from": normalize_text(message.get("from")),
        "subject": normalize_text(message.get("subject")),
        "body": clipped_text(message.get("body"), int(llm_cfg.get("max_body_chars", 5000))),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def run_codex_llm_judge(prompt: str, *, model: str, timeout_seconds: int) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(prefix="triage-judge-", suffix=".json", delete=False) as handle:
        output_path = Path(handle.name)
    command = [
        "/opt/homebrew/bin/codex",
        "exec",
        "-",
        "--skip-git-repo-check",
        "--cd",
        str(ROOT),
        "--sandbox",
        "read-only",
        "--output-schema",
        str(DEFAULT_LLM_SCHEMA),
        "--output-last-message",
        str(output_path),
    ]
    if model:
        command.extend(["--model", model])
    try:
        result = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            check=False,
            timeout=max(5, timeout_seconds),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"codex exited {result.returncode}")
        raw = output_path.read_text(encoding="utf-8").strip()
        return json.loads(raw)
    finally:
        output_path.unlink(missing_ok=True)


def llm_judge_message(message: dict[str, Any], rules: dict[str, Any], examples: list[dict[str, Any]], heuristic: dict[str, Any]) -> dict[str, Any] | None:
    llm_cfg = rules.get("llm_triage", {}) or {}
    if not llm_cfg.get("enabled"):
        return None

    provider = normalize_text(llm_cfg.get("provider") or "codex").lower()
    if provider != "codex":
        return None

    cache_path = Path(str(llm_cfg.get("cache_path") or (SHARED / "triage_llm_cache.json")))
    cache = load_cache(cache_path)
    key = llm_cache_key(message, rules)
    cached = cache.get(key)
    if isinstance(cached, dict):
        return cached

    message_text = f"{normalize_text(message.get('subject'))}\n{normalize_text(message.get('body'))}"
    examples_block = top_similar_examples(message_text, examples)
    prompt = f"""
You are triaging one email for Tianhao.

Return exactly one JSON object that matches the provided schema.

Hard boundaries already handled elsewhere:
- publication/review invitations can be auto-declined upstream
- pinned mail is kept separately
- automated mail should almost never need a reply draft

Broad decision principles:
{broad_policy_summary(rules)}

You are deciding only between:
- important_notify: keep in Inbox and notify now
- night_digest: move to Night Review for later

Message:
from: {normalize_text(message.get('from'))}
subject: {normalize_text(message.get('subject'))}
body:
{clipped_text(message.get('body'), int(llm_cfg.get('max_body_chars', 5000)))}

Heuristic context (advisory only, not binding):
{heuristic_summary_for_prompt(heuristic)}

Closest labeled examples:
{json.dumps(examples_block, ensure_ascii=False, indent=2)}

Rules for needs_reply:
- true only if this is likely a human thread that deserves a near-term human reply
- false for automated, mass, bulk, newsletter, alert, or generic notification emails
""".strip()

    decision = run_codex_llm_judge(
        prompt,
        model=str(llm_cfg.get("model", "")).strip(),
        timeout_seconds=int(llm_cfg.get("timeout_seconds", 90)),
    )
    cache[key] = decision
    save_cache(cache_path, cache)
    return decision


def heuristic_triage(message: dict[str, Any], rules: dict[str, Any], examples: list[dict[str, Any]]) -> dict[str, Any]:
    subject = normalize_text(message.get("subject"))
    body = normalize_text(message.get("body"))
    sender = normalize_text(message.get("from"))
    sender_addr = sender_email(sender)
    sender_domain = domain_of(sender_addr)
    full_text = f"{subject}\n{body}"
    human_sender = not is_automated_sender(sender)

    for override in rules.get("force_not_important", []):
        if override_matches(override, sender=sender, sender_addr=sender_addr, subject=subject, body=body):
            return {
                "important": False,
                "score": -99.0,
                "threshold": float(rules.get("priority_threshold", 4)),
                "action": "digest-later",
                "category": "override",
                "reasons": [f"forced not important: {override.get('reason', 'override')}"],
                "message": message_metadata(message),
                "draft_reply": "",
                "decision_source": "rule",
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
                "message": message_metadata(message),
                "draft_reply": build_draft(message, rules, "generic"),
                "decision_source": "rule",
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
    if category in {"review_invitation", "submission_invitation"}:
        return {
            "important": False,
            "score": -50.0,
            "threshold": float(rules.get("priority_threshold", 4)),
            "action": "queue-auto-decline-invitation",
            "category": category,
            "reasons": ["publication invitation should be auto-declined for this user"],
            "message": message_metadata(message),
            "draft_reply": build_draft(message, rules, category),
            "decision_source": "rule",
        }
    if category == "expense_approval":
        return {
            "important": True,
            "score": 90.0,
            "threshold": float(rules.get("priority_threshold", 4)),
            "action": "queue-auto-approve-expense",
            "category": category,
            "reasons": ["expense reports submitted on the user's behalf should be approved promptly"],
            "message": message_metadata(message),
            "draft_reply": "",
            "human_sender": False,
            "decision_source": "rule",
        }
    if category in {"deadline", "request", "scheduling", "ticket", "review", "security"}:
        score += 1
        reasons.append(f"action-oriented category: {category}")
    if category == "infrastructure":
        score += 2.5
        reasons.append("high-signal category: infrastructure")
    if human_sender and category in {"finance_admin", "hiring", "infrastructure", "speaker_logistics", "collaboration"}:
        score += 2.5
        reasons.append(f"human-thread category: {category}")
    actionable_hints = [
        "can you",
        "could you",
        "please",
        "let me know",
        "confirm",
        "next steps",
        "follow-up",
        "follow up",
    ]
    if human_sender and any(token in full_text.lower() for token in actionable_hints):
        score += 1.5
        reasons.append("human thread with explicit follow-up signal")
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
        "message": message_metadata(message),
        "draft_reply": draft,
        "human_sender": human_sender,
        "decision_source": "heuristic",
    }


def apply_llm_decision(message: dict[str, Any], rules: dict[str, Any], heuristic: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    bucket = normalize_text(decision.get("bucket")).lower()
    if bucket not in {"important_notify", "night_digest"}:
        bucket = "important_notify" if heuristic.get("important") else "night_digest"
    important = bucket == "important_notify"
    category = normalize_text(decision.get("category_hint")) or str(heuristic.get("category", "generic"))
    reason = normalize_text(decision.get("reason")) or "llm judgment"
    reasons = [*heuristic.get("reasons", []), f"llm: {reason}"]
    return {
        "important": important,
        "score": float(heuristic.get("score", 0.0)),
        "threshold": float(heuristic.get("threshold", rules.get("priority_threshold", 4))),
        "action": "notify-and-draft" if important else "digest-later",
        "category": category,
        "reasons": reasons,
        "message": heuristic.get("message", message_metadata(message)),
        "draft_reply": build_draft(message, rules, category) if important else "",
        "human_sender": heuristic.get("human_sender"),
        "decision_source": "llm",
        "llm_judgment": decision,
    }


def triage_message(message: dict[str, Any], rules: dict[str, Any], examples: list[dict[str, Any]]) -> dict[str, Any]:
    heuristic = heuristic_triage(message, rules, examples)
    if heuristic.get("decision_source") == "rule":
        return heuristic
    try:
        llm_decision = llm_judge_message(message, rules, examples, heuristic)
    except Exception as exc:
        heuristic.setdefault("reasons", []).append(f"llm fallback: {exc}")
        return heuristic
    if not llm_decision:
        return heuristic
    return apply_llm_decision(message, rules, heuristic, llm_decision)


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
