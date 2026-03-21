#!/usr/bin/env python3
"""Draft helpers for Outlook Web reply suggestions and feedback."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

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

from triage_engine import build_draft, load_json, load_jsonl, triage_message  # noqa: E402

DEFAULT_SUGGESTIONS = SHARED / "outlook_draft_suggestions.jsonl"
DEFAULT_FEEDBACK = SHARED / "outlook_draft_feedback.jsonl"


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
    return {
        **message,
        "from": sender,
        "body_full": body_full,
        "pane_lines": lines,
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


def classify_selected_message(rules_path: Path, examples_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    message = selected_message_payload()
    rules, examples = load_rules_examples(rules_path, examples_path)
    triage = triage_message(
        {
            **message,
            "body": message.get("body_full") or message.get("body", ""),
        },
        rules,
        examples,
    )
    if triage.get("important") and not triage.get("draft_reply"):
        triage["draft_reply"] = build_draft(message, rules, triage.get("category", "generic"))
    return message, triage


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
    message, triage = classify_selected_message(Path(args.rules), Path(args.examples))
    payload = {
        "message": message,
        "triage": triage,
    }
    if args.log:
        payload["suggestion"] = save_suggestion(Path(args.suggestions), message, triage, source="selected")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_reply_selected(args: argparse.Namespace) -> int:
    message, triage = classify_selected_message(Path(args.rules), Path(args.examples))
    draft_reply = str(triage.get("draft_reply", "")).strip()
    if not draft_reply and not args.force:
        raise BridgeError("Selected message is not currently classified for drafting; use --force if you want to inject anyway")

    suggestion = save_suggestion(Path(args.suggestions), message, triage, source="reply-selected")
    open_result = ensure_reply_open()
    if not open_result.get("ok"):
        raise BridgeError(str(open_result))

    inserted = None
    if args.insert:
        inserted = set_compose_body(draft_reply)
        if not inserted.get("ok"):
            raise BridgeError(str(inserted))

    payload = {
        "message": message,
        "triage": triage,
        "suggestion": suggestion,
        "open_result": open_result,
        "insert_result": inserted,
        "compose_state": current_compose_state(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Draft helpers for Outlook Web.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    selected = subparsers.add_parser("selected", help="Capture the currently selected Outlook message.")
    selected.set_defaults(func=command_selected)

    suggest = subparsers.add_parser("suggest-selected", help="Generate a draft suggestion for the selected message.")
    suggest.add_argument("--rules", default=str(SHARED / "default_rules.json"))
    suggest.add_argument("--examples", default=str(SHARED / "example_labeled_emails.jsonl"))
    suggest.add_argument("--suggestions", default=str(DEFAULT_SUGGESTIONS))
    suggest.add_argument("--log", action="store_true")
    suggest.set_defaults(func=command_suggest_selected)

    reply = subparsers.add_parser("reply-selected", help="Open Outlook reply compose and optionally inject the draft.")
    reply.add_argument("--rules", default=str(SHARED / "default_rules.json"))
    reply.add_argument("--examples", default=str(SHARED / "example_labeled_emails.jsonl"))
    reply.add_argument("--suggestions", default=str(DEFAULT_SUGGESTIONS))
    reply.add_argument("--insert", action="store_true")
    reply.add_argument("--force", action="store_true")
    reply.set_defaults(func=command_reply_selected)

    compose = subparsers.add_parser("compose", help="Inspect the currently open Outlook compose state.")
    compose.set_defaults(func=command_compose)

    send = subparsers.add_parser("send-current", help="Send the current Outlook compose draft and log feedback.")
    send.add_argument("--suggestions", default=str(DEFAULT_SUGGESTIONS))
    send.add_argument("--feedback", default=str(DEFAULT_FEEDBACK))
    send.set_defaults(func=command_send_current)

    discard = subparsers.add_parser("discard-current", help="Discard the currently open Outlook compose draft.")
    discard.set_defaults(func=command_discard_current)
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
