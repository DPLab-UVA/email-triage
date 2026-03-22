#!/usr/bin/env python3
"""Draft helpers for Outlook Web reply suggestions and feedback."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from outlook_apply_triage import select_visible_message
from outlook_night_review import fetch_folder_messages
from gstack_browse_bridge import BridgeError, send_command
from outlook_recent_triage import (
    SHARED,
    TIME_LINE_RE,
    clean_line,
    current_visible_options,
    parse_option,
)
from outlook_web_workflow import (
    DEFAULT_BROWSER,
    DEFAULT_COOKIE_DOMAINS,
    DEFAULT_PROFILE,
    ensure_outlook_session,
)

sys.path.append(str(SHARED))

from triage_engine import load_json, load_jsonl, triage_message  # noqa: E402

DEFAULT_SUGGESTIONS = SHARED / "outlook_draft_suggestions.jsonl"
DEFAULT_FEEDBACK = SHARED / "outlook_draft_feedback.jsonl"
DEFAULT_STYLE_PROFILE = SHARED / "outlook_reply_style_profile.json"


def bridge_cmd(command: str, *args: str, timeout: float = 30.0) -> str:
    return send_command(command, list(args), timeout=timeout).strip()


def bridge_js(expr: str, *, timeout: float = 30.0) -> str:
    return bridge_cmd("js", expr, timeout=timeout)


def bridge_json(expr: str, *, timeout: float = 30.0) -> Any:
    raw = bridge_js(expr, timeout=timeout)
    return json.loads(raw or "null")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def ensure_session_ready() -> None:
    try:
        current_url = bridge_cmd("url", timeout=10.0)
    except Exception:
        current_url = ""
    if "outlook.office.com" in current_url:
        return
    ensure_outlook_session(DEFAULT_BROWSER, DEFAULT_PROFILE, DEFAULT_COOKIE_DOMAINS)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def useful_lines(text: str) -> list[str]:
    return [clean_line(line) for line in (text or "").splitlines() if clean_line(line)]


def is_thread_date_line(line: str) -> bool:
    return bool(
        TIME_LINE_RE.match(line)
        or re.match(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s?[AP]M$", line)
    )


def looks_like_self_line(line: str) -> bool:
    lower = (line or "").strip().lower()
    return lower == "you" or "tianhao" in lower or "nkp2mr" in lower


def extract_thread_blocks(lines: list[str]) -> list[dict[str, str]]:
    date_indexes = [idx for idx, line in enumerate(lines) if is_thread_date_line(line)]
    blocks: list[dict[str, str]] = []
    if not date_indexes:
        return blocks

    for pos, idx in enumerate(date_indexes):
        sender = ""
        for back in range(idx - 1, -1, -1):
            candidate = lines[back].strip()
            previous = lines[back - 1].strip() if back > 0 else ""
            if not candidate or candidate in {"Summarize", "Reply", "Reply all", "Forward"}:
                continue
            if re.match(r"^[A-Z]{1,3}$", candidate):
                continue
            if candidate.startswith(("To:", "Cc:", "Bcc:")):
                continue
            if previous.startswith(("To:", "Cc:", "Bcc:")):
                continue
            if looks_like_self_line(candidate):
                sender = "You"
                break
            sender = candidate
            break

        end = date_indexes[pos + 1] if pos + 1 < len(date_indexes) else len(lines)
        body_lines: list[str] = []
        for line in lines[idx + 1 : end]:
            if line in {"Reply", "Reply all", "Forward"}:
                break
            body_lines.append(line)
        body = "\n".join(body_lines).strip()
        if sender or body:
            blocks.append(
                {
                    "sender": sender,
                    "timestamp": lines[idx],
                    "body": body,
                }
            )
    return blocks


def latest_external_block(lines: list[str]) -> dict[str, str]:
    for block in reversed(extract_thread_blocks(lines)):
        sender = block.get("sender", "")
        if sender and sender != "You":
            return block
    return {}


def latest_self_block(lines: list[str]) -> dict[str, str]:
    for block in reversed(extract_thread_blocks(lines)):
        if block.get("sender", "") == "You":
            return block
    return {}


def selected_row() -> dict[str, Any]:
    for row in current_visible_options():
        if row.get("selected"):
            parsed = parse_option(row)
            if parsed:
                parsed["from"] = re.sub(r"^\[Draft\]\s*", "", str(parsed.get("from", "")).strip())
                return parsed
    raise BridgeError("No selected Outlook message in the visible list")


def selected_subject() -> str:
    return str(selected_row().get("subject", "")).strip()


def reading_pane_text() -> str:
    expr = """
JSON.stringify(
  (() => {
    const node = Array.from(document.querySelectorAll('[role="main"], main')).find((el) =>
      /Summarize|Reply all|Forward|To:/i.test((el.innerText || el.textContent || '').trim())
    );
    return node ? (node.innerText || node.textContent || '') : '';
  })()
)
""".strip()
    return str(bridge_json(expr, timeout=20.0) or "")


def compose_body_text() -> str:
    expr = """
JSON.stringify(
  (() => {
    const input = Array.from(document.querySelectorAll('textarea, [role="textbox"]')).find((el) =>
      (el.getAttribute('placeholder') || '').trim() === 'Add a message'
    );
    if (!input) return '';
    return 'value' in input ? String(input.value || '') : String(input.innerText || input.textContent || '');
  })()
)
""".strip()
    return str(bridge_json(expr, timeout=15.0) or "")


def compose_open() -> bool:
    expr = """
JSON.stringify(
  (() => Array.from(document.querySelectorAll('textarea, [role="textbox"]')).some((el) =>
    (el.getAttribute('placeholder') || '').trim() === 'Add a message'
  ))()
)
""".strip()
    return bool(bridge_json(expr, timeout=10.0))


def parse_reading_pane(message: dict[str, Any], pane_text: str) -> dict[str, Any]:
    lines = useful_lines(pane_text)
    subject = str(message.get("subject", "")).strip()
    sender = str(message.get("from", "")).strip()
    if not lines:
        return {**message, "body_full": "", "pane_lines": []}

    start_idx = 0
    if subject in lines:
        start_idx = lines.index(subject)
    lines = lines[start_idx:]

    body_start = 0
    for idx, line in enumerate(lines):
        if TIME_LINE_RE.match(line) or re.match(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s?[AP]M$", line):
            body_start = idx + 1
            break
        if line.startswith("To:"):
            continue

    body_lines = lines[body_start:]
    trimmed: list[str] = []
    for line in body_lines:
        if line.startswith("From: tianhao@virginia.edu"):
            break
        if line == "[Draft]":
            break
        if line in {"Send", "Discard", "My Day", "Notifications", "Settings", "Teams Chat"}:
            break
        trimmed.append(line)

    body_full = "\n".join(trimmed).strip()
    latest_incoming = latest_external_block(lines)
    latest_self = latest_self_block(lines)
    return {
        **message,
        "from": sender,
        "body_full": body_full,
        "pane_lines": lines,
        "latest_incoming_sender": latest_incoming.get("sender", ""),
        "latest_incoming_body": latest_incoming.get("body", ""),
        "latest_incoming_timestamp": latest_incoming.get("timestamp", ""),
        "latest_self_sender": latest_self.get("sender", ""),
        "latest_self_body": latest_self.get("body", ""),
        "latest_self_timestamp": latest_self.get("timestamp", ""),
    }


def selected_message_payload() -> dict[str, Any]:
    ensure_session_ready()
    row = selected_row()
    pane_text = reading_pane_text()
    return parse_reading_pane(row, pane_text)


def load_rules_examples(rules_path: Path, examples_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return load_json(rules_path), load_jsonl(examples_path)


def normalize_reply_text(value: str) -> str:
    text = (value or "").replace("\ufeff", "").replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def suggestion_record(
    message: dict[str, Any],
    triage: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    return {
        "timestamp": now_iso(),
        "source": source,
        "conversation_id": message.get("conversation_id", ""),
        "dom_id": message.get("dom_id", ""),
        "from": message.get("from", ""),
        "subject": message.get("subject", ""),
        "received_at": message.get("received_at", ""),
        "body_preview": message.get("body", ""),
        "body_full": message.get("body_full", ""),
        "category": triage.get("category", ""),
        "important": bool(triage.get("important")),
        "reasons": triage.get("reasons", []),
        "draft_reply": triage.get("draft_reply", ""),
    }


def save_suggestion(path: Path, message: dict[str, Any], triage: dict[str, Any], *, source: str) -> dict[str, Any]:
    record = suggestion_record(message, triage, source=source)
    append_jsonl(path, record)
    return record


def latest_suggestion(path: Path, *, subject: str, sender: str = "") -> dict[str, Any] | None:
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if row.get("subject") != subject:
            continue
        if sender and row.get("from") != sender:
            continue
        return row
    return None


def find_suggestion(
    path: Path,
    *,
    conversation_id: str = "",
    subject: str = "",
    sender: str = "",
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if conversation_id and row.get("conversation_id") == conversation_id:
            return row
        if subject and row.get("subject") != subject:
            continue
        if sender and row.get("from") != sender:
            continue
        if subject:
            return row
    return None


def save_feedback(
    feedback_path: Path,
    *,
    suggestion: dict[str, Any],
    status: str,
    note: str = "",
    source: str,
    final_body: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "timestamp": now_iso(),
        "source": source,
        "status": status,
        "note": note,
        "conversation_id": suggestion.get("conversation_id", ""),
        "from": suggestion.get("from", ""),
        "subject": suggestion.get("subject", ""),
        "category": suggestion.get("category", ""),
        "important": bool(suggestion.get("important")),
        "draft_reply": suggestion.get("draft_reply", ""),
        "final_compose_body": final_body,
    }
    if extra:
        payload.update(extra)
    append_jsonl(feedback_path, payload)
    return payload


def load_style_profile(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def message_body_for_model(message: dict[str, Any]) -> str:
    return str(
        message.get("latest_incoming_body")
        or message.get("body_full")
        or message.get("body")
        or ""
    ).strip()


def message_body_for_feedback(message: dict[str, Any]) -> str:
    return normalize_reply_text(
        str(
            message.get("latest_self_body")
            or message.get("body_full")
            or message.get("body")
            or ""
        )
    )


def feedback_identity(record: dict[str, Any]) -> str:
    conversation_id = str(record.get("conversation_id", "")).strip()
    if conversation_id:
        return f"convid:{conversation_id}"
    return "subject:{subject}|from:{sender}".format(
        subject=str(record.get("subject", "")).strip(),
        sender=str(record.get("from", "")).strip(),
    )


def load_feedback_identities(path: Path) -> set[str]:
    identities: set[str] = set()
    if not path.exists():
        return identities
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        identities.add(feedback_identity(row))
    return identities


def compare_draft_to_final(suggested_text: str, final_text: str) -> dict[str, Any]:
    suggested = normalize_reply_text(suggested_text)
    final = normalize_reply_text(final_text)
    if not final:
        return {"status": "sent_no_body", "similarity": 0.0}
    if suggested and final == suggested:
        return {"status": "sent_as_is", "similarity": 1.0}
    similarity = 0.0
    if suggested:
        similarity = SequenceMatcher(None, suggested.lower(), final.lower()).ratio()
    return {
        "status": "sent_modified" if suggested else "sent_without_suggestion",
        "similarity": round(similarity, 3),
    }


def looks_automated_sender(sender: str) -> bool:
    value = (sender or "").lower()
    automated_hints = [
        "noreply",
        "no-reply",
        "do-not-reply",
        "donotreply",
        "notification",
        "notifications",
        "hotcrp",
        "microsoft cmt",
        "huggingface",
        "bookstores",
        "editorial",
        "helpdesk",
        "google flights",
        "google scholar",
        "scholarcitations",
        "security",
        "center for faculty",
        "office of ",
    ]
    return any(token in value for token in automated_hints)


def looks_automated_message(message: dict[str, Any]) -> bool:
    sender = str(message.get("from", "")).strip().lower()
    subject = str(message.get("subject", "")).strip().lower()
    body = message_body_for_model(message).lower()
    automated_hints = [
        "unsubscribe",
        "view in browser",
        "do not reply",
        "donotreply",
        "no-reply",
        "noreply",
        "notification",
        "alert",
        "newsletter",
        "tracked flight",
        "price alert",
        "google flights",
        "google scholar",
        "call for papers",
        "invitation to contribute",
        "invitation to review",
        "submit your paper",
        "full apc waived",
        "featured:",
    ]
    if looks_automated_sender(sender):
        return True
    haystacks = [sender, subject, body]
    return any(token in text for token in automated_hints for text in haystacks)


def reply_eligible(message: dict[str, Any], triage: dict[str, Any]) -> bool:
    category = str(triage.get("category", "")).strip().lower()
    subject = str(message.get("subject", "")).strip().lower()
    sender = str(message.get("from", "")).strip()
    body = message_body_for_model(message).lower()
    llm_judgment = triage.get("llm_judgment", {}) or {}
    if any(
        token in body
        for token in [
            "dear colleague",
            "we are pleased to invite you",
            "registration page",
            "first-come, first-served",
            "we look forward to your registration",
        ]
    ):
        return False
    if not message.get("latest_incoming_body") and len(extract_thread_blocks(message.get("pane_lines", []))) > 1:
        return False
    actionable = any(
        token in body or token in subject
        for token in [
            "?",
            "can you",
            "could you",
            "please",
            "let me know",
            "send",
            "share",
            "confirm",
            "when you",
            "once",
            "deadline",
            "availability",
            "action required",
            "attn required",
        ]
    )
    if not triage.get("important"):
        return False
    if "needs_reply" in llm_judgment and not bool(llm_judgment.get("needs_reply")):
        return False
    if looks_automated_message(message):
        return False
    if message.get("pinned") and not looks_automated_sender(sender):
        return actionable
    if category in {"security", "review", "review_invitation", "ticket"}:
        return False
    if any(
        token in subject or token in body
        for token in [
            "new login to your",
            "tracked flight",
            "price alert",
            "google flights",
            "google scholar",
            "submitted review #",
            "comment for #",
            "response for #",
            "pre-register",
            "verification code",
        ]
    ):
        return False
    return True


def style_signoff(style_profile: dict[str, Any], rules: dict[str, Any]) -> str:
    signoff = str(style_profile.get("recommended_signoff") or "").strip()
    if signoff:
        return signoff
    return str(rules.get("draft_preferences", {}).get("signature", "")).strip()


def category_style_value(style_profile: dict[str, Any], field: str, category: str) -> str:
    category_map = style_profile.get(field, {}) or {}
    value = category_map.get(category, "")
    return str(value or "").strip()


def default_opening(message: dict[str, Any], triage: dict[str, Any]) -> str:
    subject = str(message.get("subject", "")).lower()
    body = message_body_for_model(message).lower()
    category = str(triage.get("category", "")).lower()
    preferred = category_style_value(style_profile=triage.get("style_profile", {}), field="category_openers", category=category)
    if preferred:
        return preferred

    if "availability" in subject or "availability" in body:
        return "I can do that."
    if "budget" in subject or "budget" in body:
        return "Noted."
    if "flight" in body and "detail" in body:
        return "Thanks."
    if "reimburse" in subject or "reimburse" in body or "reimbursement" in subject:
        return "Yes, that works."
    if category == "deadline" or "action required" in subject or "attn required" in subject:
        return "Noted."
    if category == "scheduling":
        return "I can do that."
    if category == "request":
        return "Yes, that works on my end."
    if "thank you" in body or "thanks" in body:
        return "Thanks."
    return "Noted."


def default_follow_up(message: dict[str, Any], triage: dict[str, Any]) -> str:
    subject = str(message.get("subject", "")).lower()
    body = message_body_for_model(message).lower()
    category = str(triage.get("category", "")).lower()
    preferred = category_style_value(style_profile=triage.get("style_profile", {}), field="category_follow_ups", category=category)
    if preferred:
        return preferred

    if "availability" in subject or "availability" in body:
        return "If needed, I can adjust a bit on my side."
    if "flight" in body and "detail" in body:
        return "I'll send the flight details once the plan is fixed."
    if "hotel" in body and "flight" in body:
        return "No preference on my end for the hotel or flight."
    if category == "deadline" or "action required" in subject or "attn required" in subject:
        return "I'll take care of it soon."
    if category == "request":
        return "Let me know if you need anything else from me."
    if "send" in body or "share" in body:
        return "I'll send it once it's fixed."
    if "confirm" in body:
        return "I'll confirm once the plan is fixed."
    return ""


def draft_reply_for_message(
    message: dict[str, Any],
    triage: dict[str, Any],
    rules: dict[str, Any],
    style_profile: dict[str, Any] | None = None,
) -> str:
    if not reply_eligible(message, triage):
        return ""
    style_profile = style_profile or {}
    triage = {**triage, "style_profile": style_profile}
    opening = default_opening(message, triage)
    follow_up = default_follow_up(message, triage)
    signoff = style_signoff(style_profile, rules)

    lines: list[str] = []
    use_greeting = bool(style_profile.get("use_greeting_default", False))
    if use_greeting:
        sender = str(message.get("from", "")).split(";", 1)[0].strip()
        if sender:
            lines.extend([f"Hi {sender},", ""])

    lines.append(opening)
    if follow_up:
        lines.append(follow_up)
    if signoff:
        lines.extend(["", signoff])
    return "\n".join(line for line in lines if line is not None).strip()


def classify_message_payload(
    message: dict[str, Any],
    rules: dict[str, Any],
    examples: list[dict[str, Any]],
    *,
    style_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    triage = triage_message(
        {
            **message,
            "body": message_body_for_model(message),
        },
        rules,
        examples,
    )
    triage["draft_reply"] = draft_reply_for_message(message, triage, rules, style_profile)
    return triage


def classify_selected_message(
    rules_path: Path,
    examples_path: Path,
    style_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    message = selected_message_payload()
    rules, examples = load_rules_examples(rules_path, examples_path)
    style_profile = load_style_profile(style_path)
    triage = classify_message_payload(message, rules, examples, style_profile=style_profile)
    return message, triage, rules, examples


def ensure_reply_open() -> dict[str, Any]:
    if compose_open():
        return {"ok": True, "already_open": True}
    reply_script = """
(() => {
  const normalize = (value) => (value || '').replace(/[\\uE000-\\uF8FF]/g, ' ').replace(/\\s+/g, ' ').trim();
  const click = (el) => {
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    el.click();
  };
  const button = Array.from(document.querySelectorAll('button,[role="button"],[role="menuitem"]')).find((el) =>
    normalize(el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.textContent || '') === 'Reply'
  );
  if (!button) return JSON.stringify({ ok: false, reason: 'reply-button-not-found' });
  click(button);
  return JSON.stringify({ ok: true, clicked: true });
})()
""".strip()
    result = json.loads(bridge_js(reply_script, timeout=15.0))
    if not result.get("ok"):
        return result
    for _ in range(12):
        time.sleep(0.25)
        if compose_open():
            return {"ok": True, "already_open": False}
    return {"ok": False, "reason": "compose-did-not-open"}


def set_compose_body(body: str) -> dict[str, Any]:
    expr = f"""
JSON.stringify(
  (() => {{
    const value = {json.dumps(body, ensure_ascii=False)};
    const input = Array.from(document.querySelectorAll('textarea, [role="textbox"]')).find((el) =>
      (el.getAttribute('placeholder') || '').trim() === 'Add a message'
    );
    if (!input) return {{ ok: false, reason: 'compose-input-not-found' }};
    input.focus();
    if ('value' in input) {{
      input.value = value;
      input.dispatchEvent(new Event('input', {{ bubbles: true }}));
      input.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }} else {{
      input.textContent = value;
      input.dispatchEvent(new InputEvent('input', {{ bubbles: true, data: value, inputType: 'insertText' }}));
    }}
    return {{ ok: true, value }};
  }})(),
  null,
  2
)
""".strip()
    return bridge_json(expr, timeout=15.0) or {}


def current_compose_state() -> dict[str, Any]:
    subject = selected_subject()
    sender = str(selected_row().get("from", "")).strip()
    body = compose_body_text()
    expr = """
JSON.stringify(
  (() => {
    const send = Array.from(document.querySelectorAll('button')).find((el) =>
      ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || el.textContent || '')).includes('Send')
    );
    return {
      send_enabled: !!send && !send.disabled
    };
  })(),
  null,
  2
)
""".strip()
    extra = bridge_json(expr, timeout=10.0) or {}
    return {
      "subject": subject,
      "from": sender,
      "compose_body": normalize_reply_text(body),
      **extra,
    }


def open_outlook_reply_draft(
    message: dict[str, Any],
    triage: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    draft_reply = str(triage.get("draft_reply", "")).strip()
    if not draft_reply and not force:
        return {"ok": False, "reason": "no-draft-reply"}
    if compose_open():
        return {
            "ok": False,
            "reason": "compose-already-open",
            "compose_state": current_compose_state(),
        }

    selected = select_visible_message(str(message.get("dom_id", "")), str(message.get("subject", "")))
    if not selected.get("ok"):
        return {"ok": False, "reason": "select-failed", "selection": selected}

    open_result = ensure_reply_open()
    if not open_result.get("ok"):
        return {"ok": False, "reason": "reply-open-failed", "selection": selected, "open_result": open_result}

    insert_result = set_compose_body(draft_reply)
    if not insert_result.get("ok"):
        return {"ok": False, "reason": "compose-insert-failed", "selection": selected, "open_result": open_result, "insert_result": insert_result}

    time.sleep(0.4)
    compose_state = current_compose_state()
    return {
        "ok": True,
        "selection": selected,
        "open_result": open_result,
        "insert_result": insert_result,
        "compose_state": compose_state,
        "draft_reply": draft_reply,
    }


def send_current_compose(feedback_path: Path, suggestions_path: Path) -> dict[str, Any]:
    compose = current_compose_state()
    suggestion = latest_suggestion(suggestions_path, subject=compose["subject"], sender=compose["from"])
    suggested_text = normalize_reply_text((suggestion or {}).get("draft_reply", ""))
    compose_text = normalize_reply_text(compose.get("compose_body", ""))
    match_type = "unknown"
    if suggested_text:
        match_type = "sent_as_is" if compose_text == suggested_text else "sent_modified"

    expr = """
JSON.stringify(
  (() => {
    const normalize = (value) => (value || '').replace(/[\\uE000-\\uF8FF]/g, ' ').replace(/\\s+/g, ' ').trim();
    const click = (el) => {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.click();
    };
    const send = Array.from(document.querySelectorAll('button')).find((el) =>
      normalize((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || el.textContent || '')).includes('Send')
    );
    if (!send) return { ok: false, reason: 'send-button-not-found' };
    if (send.disabled) return { ok: false, reason: 'send-button-disabled' };
    click(send);
    return { ok: true };
  })(),
  null,
  2
)
""".strip()
    result = bridge_json(expr, timeout=15.0) or {}
    feedback = {
        "timestamp": now_iso(),
        "subject": compose["subject"],
        "from": compose["from"],
        "suggested_draft": suggested_text,
        "final_compose_body": compose_text,
        "status": match_type if result.get("ok") else "send_failed",
        "send_result": result,
    }
    append_jsonl(feedback_path, feedback)
    return feedback


def harvest_sent_feedback(
    *,
    folder_name: str,
    screens: int,
    limit: int,
    suggestions_path: Path,
    feedback_path: Path,
) -> dict[str, Any]:
    ensure_session_ready()
    rows = fetch_folder_messages(folder_name, screens=screens, limit=limit)
    existing_feedback = load_feedback_identities(feedback_path)

    harvested: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for row in rows:
        suggestion = find_suggestion(
            suggestions_path,
            conversation_id=str(row.get("conversation_id", "")).strip(),
            subject=str(row.get("subject", "")).strip(),
        )
        if not suggestion:
            continue

        identity = feedback_identity(suggestion)
        if identity in existing_feedback:
            continue

        selected = select_visible_message(str(row.get("dom_id", "")), str(row.get("subject", "")))
        if not selected.get("ok"):
            skipped.append(
                {
                    "subject": row.get("subject", ""),
                    "from": row.get("from", ""),
                    "reason": f"select failed: {selected}",
                }
            )
            continue

        message = selected_message_payload()
        final_body = message_body_for_feedback(message)
        comparison = compare_draft_to_final(str(suggestion.get("draft_reply", "")), final_body)
        payload = save_feedback(
            feedback_path,
            suggestion=suggestion,
            status=str(comparison.get("status", "sent_modified")),
            source="sent-harvest",
            final_body=final_body,
            extra={
                "similarity": comparison.get("similarity", 0.0),
                "matched_folder": folder_name,
                "matched_subject": message.get("subject", ""),
                "matched_from": message.get("from", ""),
                "matched_dom_id": row.get("dom_id", ""),
                "latest_self_timestamp": message.get("latest_self_timestamp", ""),
            },
        )
        harvested.append(payload)
        existing_feedback.add(identity)

    return {
        "folder": folder_name,
        "scanned": len(rows),
        "harvested": len(harvested),
        "feedback": harvested,
        "skipped_examples": skipped[:8],
    }


def discard_current_compose() -> dict[str, Any]:
    expr = """
JSON.stringify(
  (() => {
    const normalize = (value) => (value || '').replace(/[\\uE000-\\uF8FF]/g, ' ').replace(/\\s+/g, ' ').trim();
    const click = (el) => {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.click();
    };
    const discard = Array.from(document.querySelectorAll('button')).find((el) =>
      normalize((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || el.textContent || '')).includes('Discard')
    );
    if (!discard) return { ok: false, reason: 'discard-button-not-found' };
    click(discard);
    return { ok: true };
  })(),
  null,
  2
)
""".strip()
    return bridge_json(expr, timeout=15.0) or {}


def command_selected(args: argparse.Namespace) -> int:
    payload = selected_message_payload()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_suggest_selected(args: argparse.Namespace) -> int:
    message, triage, _, _ = classify_selected_message(
        Path(args.rules),
        Path(args.examples),
        Path(args.style_profile),
    )
    payload = {
        "message": message,
        "triage": triage,
    }
    if args.log:
        payload["suggestion"] = save_suggestion(Path(args.suggestions), message, triage, source="selected")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_reply_selected(args: argparse.Namespace) -> int:
    message, triage, _, _ = classify_selected_message(
        Path(args.rules),
        Path(args.examples),
        Path(args.style_profile),
    )
    payload = open_outlook_reply_draft(message, triage, force=args.force)
    if not payload.get("ok"):
        raise BridgeError(str(payload))

    result = {
        "message": message,
        "triage": triage,
        "outlook_draft": payload,
    }
    if args.log:
        result["suggestion"] = save_suggestion(Path(args.suggestions), message, triage, source="reply-selected")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_compose(args: argparse.Namespace) -> int:
    print(json.dumps(current_compose_state(), ensure_ascii=False, indent=2))
    return 0


def command_send_current(args: argparse.Namespace) -> int:
    payload = send_current_compose(Path(args.feedback), Path(args.suggestions))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_discard_current(args: argparse.Namespace) -> int:
    print(json.dumps(discard_current_compose(), ensure_ascii=False, indent=2))
    return 0


def command_feedback(args: argparse.Namespace) -> int:
    conversation_id = str(args.conversation_id or "").strip()
    subject = str(args.subject or "").strip()
    sender = str(args.sender or "").strip()

    if args.selected:
        message = selected_message_payload()
        conversation_id = conversation_id or str(message.get("conversation_id", "")).strip()
        subject = subject or str(message.get("subject", "")).strip()
        sender = sender or str(message.get("from", "")).strip()

    if not conversation_id and not subject:
        raise BridgeError("feedback needs --selected or at least --subject/--conversation-id")

    suggestion = find_suggestion(
        Path(args.suggestions),
        conversation_id=conversation_id,
        subject=subject,
        sender=sender,
    )
    if not suggestion:
        raise BridgeError("No matching suggestion found for feedback")

    payload = save_feedback(
        Path(args.feedback),
        suggestion=suggestion,
        status=args.status,
        note=str(args.note or ""),
        source="manual-feedback",
        final_body=str(args.final_body or ""),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_harvest_sent_feedback(args: argparse.Namespace) -> int:
    payload = harvest_sent_feedback(
        folder_name=args.folder,
        screens=args.screens,
        limit=args.limit,
        suggestions_path=Path(args.suggestions),
        feedback_path=Path(args.feedback),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_suggest_folder(args: argparse.Namespace) -> int:
    ensure_session_ready()
    rules, examples = load_rules_examples(Path(args.rules), Path(args.examples))
    style_profile = load_style_profile(Path(args.style_profile))
    rows = fetch_folder_messages(args.folder, screens=args.screens, limit=args.limit)

    suggestions: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        if row.get("pinned") and not args.include_pinned:
            continue

        preview_triage = classify_message_payload(row, rules, examples, style_profile=style_profile)
        inspect_full = bool(preview_triage.get("important")) and not looks_automated_sender(str(row.get("from", "")))
        if not inspect_full:
            skipped.append(
                {
                    "from": row.get("from", ""),
                    "subject": row.get("subject", ""),
                    "reason": "; ".join(preview_triage.get("reasons", [])) or preview_triage.get("category", ""),
                }
            )
            continue

        selected = select_visible_message(str(row.get("dom_id", "")), str(row.get("subject", "")))
        if not selected.get("ok"):
            skipped.append(
                {
                    "from": row.get("from", ""),
                    "subject": row.get("subject", ""),
                    "reason": f"select failed: {selected}",
                }
            )
            continue

        message = selected_message_payload()
        triage = classify_message_payload(message, rules, examples, style_profile=style_profile)
        draft_reply = str(triage.get("draft_reply", "")).strip()
        if not draft_reply:
            skipped.append(
                {
                    "from": message.get("from", ""),
                    "subject": message.get("subject", ""),
                    "reason": "not reply-eligible after full-body parse",
                }
            )
            continue

        record = save_suggestion(Path(args.suggestions), message, triage, source=f"folder:{args.folder}")
        suggestions.append(
            {
                "message": message,
                "triage": triage,
                "suggestion": record,
            }
        )
        if len(suggestions) >= args.max_drafts:
            break

    payload = {
        "folder": args.folder,
        "scanned": len(rows),
        "drafts_created": len(suggestions),
        "drafts": suggestions,
        "skipped_examples": skipped[:8],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Draft helpers for Outlook Web.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    selected = subparsers.add_parser("selected", help="Capture the currently selected Outlook message.")
    selected.set_defaults(func=command_selected)

    suggest = subparsers.add_parser("suggest-selected", help="Generate a draft suggestion for the selected message.")
    suggest.add_argument("--rules", default=str(SHARED / "default_rules.json"))
    suggest.add_argument("--examples", default=str(SHARED / "example_labeled_emails.jsonl"))
    suggest.add_argument("--suggestions", default=str(DEFAULT_SUGGESTIONS))
    suggest.add_argument("--style-profile", default=str(DEFAULT_STYLE_PROFILE))
    suggest.add_argument("--log", action="store_true")
    suggest.set_defaults(func=command_suggest_selected)

    suggest_folder = subparsers.add_parser("suggest-folder", help="Generate draft suggestions for reply-worthy messages in one Outlook folder.")
    suggest_folder.add_argument("--folder", default="Inbox")
    suggest_folder.add_argument("--screens", type=int, default=8)
    suggest_folder.add_argument("--limit", type=int, default=25)
    suggest_folder.add_argument("--max-drafts", type=int, default=3)
    suggest_folder.add_argument("--include-pinned", action="store_true")
    suggest_folder.add_argument("--rules", default=str(SHARED / "default_rules.json"))
    suggest_folder.add_argument("--examples", default=str(SHARED / "example_labeled_emails.jsonl"))
    suggest_folder.add_argument("--suggestions", default=str(DEFAULT_SUGGESTIONS))
    suggest_folder.add_argument("--style-profile", default=str(DEFAULT_STYLE_PROFILE))
    suggest_folder.set_defaults(func=command_suggest_folder)

    reply = subparsers.add_parser("reply-selected", help="Open Outlook reply compose and inject the draft into Outlook.")
    reply.add_argument("--rules", default=str(SHARED / "default_rules.json"))
    reply.add_argument("--examples", default=str(SHARED / "example_labeled_emails.jsonl"))
    reply.add_argument("--suggestions", default=str(DEFAULT_SUGGESTIONS))
    reply.add_argument("--style-profile", default=str(DEFAULT_STYLE_PROFILE))
    reply.add_argument("--force", action="store_true")
    reply.add_argument("--log", action="store_true")
    reply.set_defaults(func=command_reply_selected)

    compose = subparsers.add_parser("compose", help="Inspect the currently open Outlook compose state.")
    compose.set_defaults(func=command_compose)

    send = subparsers.add_parser("send-current", help="Send the current Outlook compose draft and log feedback.")
    send.add_argument("--suggestions", default=str(DEFAULT_SUGGESTIONS))
    send.add_argument("--feedback", default=str(DEFAULT_FEEDBACK))
    send.set_defaults(func=command_send_current)

    discard = subparsers.add_parser("discard-current", help="Discard the currently open Outlook compose draft.")
    discard.set_defaults(func=command_discard_current)

    feedback = subparsers.add_parser("feedback", help="Log explicit feedback for a draft suggestion.")
    feedback.add_argument("--status", required=True, choices=["approved", "edited", "rejected"])
    feedback.add_argument("--selected", action="store_true")
    feedback.add_argument("--conversation-id")
    feedback.add_argument("--subject")
    feedback.add_argument("--sender")
    feedback.add_argument("--note")
    feedback.add_argument("--final-body")
    feedback.add_argument("--suggestions", default=str(DEFAULT_SUGGESTIONS))
    feedback.add_argument("--feedback", default=str(DEFAULT_FEEDBACK))
    feedback.set_defaults(func=command_feedback)

    harvest = subparsers.add_parser("harvest-sent-feedback", help="Match draft suggestions against recent Sent Items and log automatic feedback.")
    harvest.add_argument("--folder", default="Sent Items")
    harvest.add_argument("--screens", type=int, default=8)
    harvest.add_argument("--limit", type=int, default=40)
    harvest.add_argument("--suggestions", default=str(DEFAULT_SUGGESTIONS))
    harvest.add_argument("--feedback", default=str(DEFAULT_FEEDBACK))
    harvest.set_defaults(func=command_harvest_sent_feedback)
    return parser


def main() -> int:
    ensure_session_ready()
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BridgeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
