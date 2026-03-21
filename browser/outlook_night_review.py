#!/usr/bin/env python3
"""Manage nightly reminder and next-day restore for Outlook Night Review."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from gstack_browse_bridge import BridgeError, send_command
from outlook_apply_triage import folder_exists, move_message_to_folder
from outlook_recent_triage import (
    SHARED,
    current_visible_options,
    parse_option,
    reset_message_list_scroll,
    scroll_message_list,
)
from outlook_web_workflow import (
    DEFAULT_BROWSER,
    DEFAULT_COOKIE_DOMAINS,
    DEFAULT_PROFILE,
    ensure_outlook_session,
)

DEFAULT_STATE = SHARED / "outlook_night_review_state.json"
DEFAULT_EVENT_LOG = SHARED / "outlook_night_review_events.jsonl"


def bridge_cmd(command: str, *args: str, timeout: float = 30.0) -> str:
    return send_command(command, list(args), timeout=timeout).strip()


def bridge_js(expr: str, *, timeout: float = 30.0) -> str:
    return bridge_cmd("js", expr, timeout=timeout)


def bridge_json(expr: str, *, timeout: float = 30.0) -> Any:
    raw = bridge_js(expr, timeout=timeout)
    return json.loads(raw or "null")


def now_local() -> datetime:
    return datetime.now().astimezone()


def now_iso() -> str:
    return now_local().isoformat()


def today_key(now: datetime | None = None) -> str:
    stamp = now or now_local()
    return stamp.date().isoformat()


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "created_at": now_iso(),
            "updated_at": "",
            "pending": {},
            "last_reminder_date": "",
            "last_restore_date": "",
            "last_run": {},
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "created_at": now_iso(),
            "updated_at": "",
            "pending": {},
            "last_reminder_date": "",
            "last_restore_date": "",
            "last_run": {"error": "state file was invalid json and was reset"},
        }


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def message_key(row: dict[str, Any]) -> str:
    conversation_id = str(row.get("conversation_id", "")).strip()
    if conversation_id:
        return f"convid:{conversation_id}"
    dom_id = str(row.get("dom_id", "")).strip()
    if dom_id:
        return f"dom:{dom_id}"
    return "fallback:{from_}|{subject}|{received_at}".format(
        from_=str(row.get("from", "")).strip(),
        subject=str(row.get("subject", "")).strip(),
        received_at=str(row.get("received_at", "")).strip(),
    )


def register_pending_message(state_path: Path, row: dict[str, Any], *, moved_at: str | None = None) -> dict[str, Any]:
    state = load_state(state_path)
    pending = dict(state.get("pending", {}))
    key = message_key(row)
    record = {
        "key": key,
        "from": row.get("from", ""),
        "subject": row.get("subject", ""),
        "conversation_id": row.get("conversation_id", ""),
        "received_at": row.get("received_at", ""),
        "moved_at": moved_at or now_iso(),
        "last_seen_folder": "Night Review",
    }
    pending[key] = record
    state["pending"] = pending
    state["updated_at"] = now_iso()
    save_state(state_path, state)
    return record


def bootstrap_pending_messages(
    *,
    state_path: Path,
    folder_name: str,
    screens: int,
    limit: int,
    moved_at: str | None = None,
) -> dict[str, Any]:
    rows = fetch_folder_messages(folder_name, screens=screens, limit=limit)
    state = load_state(state_path)
    pending = dict(state.get("pending", {}))
    added = 0
    updated = 0
    stamp = moved_at or now_iso()
    for row in rows:
        key = message_key(row)
        record = {
            "key": key,
            "from": row.get("from", ""),
            "subject": row.get("subject", ""),
            "conversation_id": row.get("conversation_id", ""),
            "received_at": row.get("received_at", ""),
            "moved_at": pending.get(key, {}).get("moved_at", stamp),
            "last_seen_folder": folder_name,
        }
        if key in pending:
            updated += 1
        else:
            added += 1
        pending[key] = record
    state["pending"] = pending
    state["updated_at"] = now_iso()
    state["last_run"] = {
        "action": "bootstrap-pending",
        "folder_name": folder_name,
        "captured": len(rows),
        "added": added,
        "updated": updated,
    }
    save_state(state_path, state)
    return state["last_run"]


def folder_selected_name() -> str:
    expr = """
JSON.stringify(
  (() => {
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const cleanFolder = (value) => normalize(value)
      .replace(/\\bselected\\b/gi, '')
      .replace(/\\b\\d+\\s+(?:item|items|unread)\\b/gi, '')
      .replace(/\\s+/g, ' ')
      .trim();
    const selected = Array.from(document.querySelectorAll('[role="treeitem"]')).find(
      (el) => el.getAttribute('aria-selected') === 'true'
    );
    return selected ? cleanFolder(selected.innerText || selected.textContent || '') : '';
  })()
)
""".strip()
    return str(bridge_json(expr, timeout=10.0) or "")


def open_folder(folder_name: str) -> dict[str, Any]:
    expr = f"""
JSON.stringify(
  (() => {{
    const target = {json.dumps(folder_name, ensure_ascii=False)};
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const cleanFolder = (value) => normalize(value)
      .replace(/\\bselected\\b/gi, '')
      .replace(/\\b\\d+\\s+(?:item|items|unread)\\b/gi, '')
      .replace(/\\s+/g, ' ')
      .trim();
    const click = (el) => {{
      el.scrollIntoView({{ block: 'center' }});
      el.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
      el.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
      el.click();
    }};
    const candidates = Array.from(document.querySelectorAll('[role="treeitem"]')).filter(
      (el) => cleanFolder(el.innerText || el.textContent || '') === target
    );
    if (!candidates.length) {{
      return {{ ok: false, reason: 'folder-not-found', target }};
    }}
    const selected = candidates.find((el) => el.getAttribute('aria-selected') === 'true');
    if (selected) {{
      return {{ ok: true, already_selected: true, label: cleanFolder(selected.innerText || selected.textContent || '') }};
    }}
    click(candidates[0]);
    return {{ ok: true, already_selected: false, label: cleanFolder(candidates[0].innerText || candidates[0].textContent || '') }};
  }})(),
  null,
  2
)
""".strip()
    result = bridge_json(expr, timeout=15.0) or {}
    if not result.get("ok"):
        return result
    for _ in range(10):
        time.sleep(0.25)
        if folder_selected_name() == folder_name:
            return {**result, "selected_folder": folder_name}
    return {**result, "ok": False, "reason": "folder-selection-timeout"}


def fetch_folder_messages(folder_name: str, *, screens: int, limit: int) -> list[dict[str, Any]]:
    ensure_outlook_session(DEFAULT_BROWSER, DEFAULT_PROFILE, DEFAULT_COOKIE_DOMAINS)
    opened = open_folder(folder_name)
    if not opened.get("ok"):
        raise BridgeError(f"Could not open Outlook folder {folder_name}: {opened}")

    collected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for _ in range(max(1, screens)):
        for row in current_visible_options():
            parsed = parse_option(row)
            if not parsed:
                continue
            key = (
                parsed.get("conversation_id", ""),
                parsed.get("subject", ""),
                parsed.get("received_at", ""),
            )
            if key in seen:
                continue
            seen.add(key)
            collected.append(parsed)
            if len(collected) >= limit:
                reset_message_list_scroll()
                return collected
        scroll_info = scroll_message_list()
        if not scroll_info.get("ok") or scroll_info.get("after") == scroll_info.get("before"):
            break
        time.sleep(0.6)
    reset_message_list_scroll()
    return collected[:limit]


def ready_for_restore(record: dict[str, Any], now: datetime) -> bool:
    moved_at = str(record.get("moved_at", "")).strip()
    if not moved_at:
        return False
    try:
        moved_stamp = datetime.fromisoformat(moved_at)
    except ValueError:
        return False
    return moved_stamp.astimezone().date() < now.date()


def notify_user(title: str, subtitle: str, body: str) -> bool:
    script = (
        'display notification "{body}" with title "{title}" subtitle "{subtitle}"'
    ).format(
        body=body.replace('"', "'")[:220],
        title=title.replace('"', "'")[:80],
        subtitle=subtitle.replace('"', "'")[:120],
    )
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def process_cycle(
    *,
    state_path: Path,
    event_log: Path,
    folder_name: str,
    restore_folder: str,
    reminder_hour: int,
    restore_hour: int,
    screens: int,
    limit: int,
    notify: bool,
) -> dict[str, Any]:
    if not folder_exists(folder_name):
        raise BridgeError(f"Outlook folder not found: {folder_name}")
    if not folder_exists(restore_folder):
        raise BridgeError(f"Outlook folder not found: {restore_folder}")

    state = load_state(state_path)
    pending = dict(state.get("pending", {}))
    now = now_local()
    today = today_key(now)
    need_reminder = bool(pending) and now.hour >= reminder_hour and state.get("last_reminder_date") != today
    need_restore_check = bool(pending) and now.hour >= restore_hour and state.get("last_restore_date") != today

    summary = {
        "timestamp": now.isoformat(),
        "pending_before": len(pending),
        "pending_after": len(pending),
        "folder_name": folder_name,
        "restore_folder": restore_folder,
        "reminder_sent": False,
        "restored": 0,
        "restore_failed": 0,
        "left_for_later": 0,
        "removed_missing": 0,
        "events": [],
    }

    if not pending or not (need_reminder or need_restore_check):
        state["updated_at"] = now.isoformat()
        state["last_run"] = summary
        save_state(state_path, state)
        return summary

    fetch_limit = max(limit, len(pending) + 10)
    rows = fetch_folder_messages(folder_name, screens=screens, limit=fetch_limit)
    rows_by_key = {message_key(row): row for row in rows}

    removed_missing: list[dict[str, Any]] = []
    for key in list(pending):
        if key not in rows_by_key:
            removed_missing.append(pending.pop(key))
    if removed_missing:
        summary["removed_missing"] = len(removed_missing)
        append_jsonl(
            event_log,
            {
                "timestamp": now.isoformat(),
                "action": "sync-pending",
                "status": "removed-missing",
                "count": len(removed_missing),
                "subjects": [row.get("subject", "") for row in removed_missing[:5]],
            },
        )

    if need_restore_check:
        state["last_restore_date"] = today
        ready_keys = [key for key, record in pending.items() if ready_for_restore(record, now)]
        ready_rows = [rows_by_key[key] for key in ready_keys if key in rows_by_key]
        unread_ready = [row for row in ready_rows if row.get("unread")]
        if ready_rows and not unread_ready:
            for row in ready_rows:
                key = message_key(row)
                result = move_message_to_folder(row, restore_folder)
                event = {
                    "timestamp": now_iso(),
                    "action": "restore-to-inbox",
                    "key": key,
                    "from": row.get("from", ""),
                    "subject": row.get("subject", ""),
                    "status": "restored" if result.get("ok") else "restore-failed",
                    "result": result,
                }
                if result.get("ok"):
                    summary["restored"] += 1
                    pending.pop(key, None)
                else:
                    summary["restore_failed"] += 1
                summary["events"].append(event)
                append_jsonl(event_log, event)
                time.sleep(0.4)
        elif ready_keys:
            summary["left_for_later"] = len(ready_keys)
            event = {
                "timestamp": now_iso(),
                "action": "restore-to-inbox",
                "status": "deferred-unread",
                "count": len(ready_keys),
                "subjects": [row.get("subject", "") for row in unread_ready[:5]],
            }
            summary["events"].append(event)
            append_jsonl(event_log, event)

    state["pending"] = pending
    summary["pending_after"] = len(pending)

    if need_reminder and pending:
        preview = [record.get("subject", "") for record in list(pending.values())[:3]]
        body = "; ".join(subject for subject in preview if subject) or "Night Review has messages waiting."
        notified = notify and notify_user(
            "Night Review",
            f"{len(pending)} message(s) waiting",
            body,
        )
        state["last_reminder_date"] = today
        summary["reminder_sent"] = notified or not notify
        event = {
            "timestamp": now_iso(),
            "action": "night-review-reminder",
            "status": "notified" if notified else ("logged" if not notify else "notify-failed"),
            "count": len(pending),
            "subjects": preview,
        }
        summary["events"].append(event)
        append_jsonl(event_log, event)

    open_folder(restore_folder)
    state["updated_at"] = now_iso()
    state["last_run"] = summary
    save_state(state_path, state)
    return summary


def command_run_once(args: argparse.Namespace) -> int:
    payload = process_cycle(
        state_path=Path(args.state),
        event_log=Path(args.event_log),
        folder_name=args.folder,
        restore_folder=args.restore_folder,
        reminder_hour=args.reminder_hour,
        restore_hour=args.restore_hour,
        screens=args.screens,
        limit=args.limit,
        notify=not args.no_notify,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_status(args: argparse.Namespace) -> int:
    print(json.dumps(load_state(Path(args.state)), ensure_ascii=False, indent=2))
    return 0


def command_bootstrap_pending(args: argparse.Namespace) -> int:
    payload = bootstrap_pending_messages(
        state_path=Path(args.state),
        folder_name=args.folder,
        screens=args.screens,
        limit=args.limit,
        moved_at=args.moved_at,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Night Review reminder and restore helper for Outlook Web.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_once = subparsers.add_parser("run-once", help="Run one Night Review reminder/restore cycle.")
    run_once.add_argument("--state", default=str(DEFAULT_STATE))
    run_once.add_argument("--event-log", default=str(DEFAULT_EVENT_LOG))
    run_once.add_argument("--folder", default="Night Review")
    run_once.add_argument("--restore-folder", default="Inbox")
    run_once.add_argument("--reminder-hour", type=int, default=21)
    run_once.add_argument("--restore-hour", type=int, default=7)
    run_once.add_argument("--screens", type=int, default=4)
    run_once.add_argument("--limit", type=int, default=50)
    run_once.add_argument("--no-notify", action="store_true")
    run_once.set_defaults(func=command_run_once)

    status = subparsers.add_parser("status", help="Show Night Review pending state.")
    status.add_argument("--state", default=str(DEFAULT_STATE))
    status.set_defaults(func=command_status)

    bootstrap = subparsers.add_parser("bootstrap-pending", help="Register currently visible Night Review messages into pending state.")
    bootstrap.add_argument("--state", default=str(DEFAULT_STATE))
    bootstrap.add_argument("--folder", default="Night Review")
    bootstrap.add_argument("--screens", type=int, default=4)
    bootstrap.add_argument("--limit", type=int, default=50)
    bootstrap.add_argument("--moved-at")
    bootstrap.set_defaults(func=command_bootstrap_pending)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except BridgeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
