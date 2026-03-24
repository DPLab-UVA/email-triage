#!/usr/bin/env python3
"""Continuously monitor Outlook Web and apply triage actions to new mail."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from gstack_browse_bridge import BridgeError
from outlook_apply_triage import (
    DEFAULT_ACTION_LOG,
    folder_exists,
    move_message_to_folder,
    select_visible_message,
)
from outlook_auto_actions import attempt_expense_approval_from_selected
from outlook_draft_helper import (
    DEFAULT_FEEDBACK,
    DEFAULT_STYLE_PROFILE,
    DEFAULT_SUGGESTIONS,
    classify_message_payload,
    harvest_sent_feedback,
    load_style_profile,
    open_outlook_reply_draft,
    selected_message_payload,
)
from outlook_night_review import (
    DEFAULT_EVENT_LOG as DEFAULT_NIGHT_REVIEW_EVENT_LOG,
    DEFAULT_STATE as DEFAULT_NIGHT_REVIEW_STATE,
    open_folder,
    process_cycle as process_night_review_cycle,
    register_pending_message,
)
from outlook_recent_triage import (
    SHARED,
    fetch_recent_messages,
    load_json,
    load_jsonl,
    message_cursor_key,
    top_cursor_keys,
    triage_recent_messages,
    wait_for_visible_options,
)
from outlook_reply_style import DEFAULT_SAMPLES as DEFAULT_STYLE_SAMPLES, refresh_style_profile
from outlook_wake_hook import (
    DEFAULT_WAKE_EVENT_LOG,
    DEFAULT_WAKE_HOST,
    DEFAULT_WAKE_PORT,
    WakeSignalServer,
    install_outlook_wake_hook,
    read_wake_hook_state,
)
from outlook_web_workflow import (
    DEFAULT_BROWSER,
    DEFAULT_COOKIE_DOMAINS,
    DEFAULT_PROFILE,
    ensure_outlook_session,
)
sys.path.append(str(SHARED))
from sqlite_store import (  # noqa: E402
    append_event,
    load_recent_event_rows,
    load_state_snapshot,
    save_state_snapshot,
)

DEFAULT_STATE = "outlook_monitor_state"
DEFAULT_EVENT_LOG = "outlook_monitor_events"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def load_state(path: Path) -> dict[str, Any]:
    raw_state = load_state_snapshot(path)
    if raw_state is None:
        return {
            "created_at": now_iso(),
            "updated_at": "",
            "initialized": False,
            "key_schema_version": 2,
            "seen_keys": [],
            "scan_cursor_keys": [],
            "attempt_counts": {},
            "last_feedback_scan_at": "",
            "last_run": {},
        }
    try:
        state = raw_state
        if int(state.get("key_schema_version", 1)) < 2:
            state["initialized"] = False
            state["seen_keys"] = []
            state["scan_cursor_keys"] = []
            state["attempt_counts"] = {}
            state["key_schema_version"] = 2
            state["last_run"] = {
                "status": "migrated-key-schema",
                "note": "reset seen state so the new cursor-based key schema can re-baseline cleanly",
            }
        else:
            state.setdefault("scan_cursor_keys", [])
            state.setdefault("key_schema_version", 2)
        return state
    except json.JSONDecodeError:
        return {
            "created_at": now_iso(),
            "updated_at": "",
            "initialized": False,
            "key_schema_version": 2,
            "seen_keys": [],
            "scan_cursor_keys": [],
            "attempt_counts": {},
            "last_feedback_scan_at": "",
            "last_run": {"error": "state file was invalid json and was reset"},
        }


def save_state(path: Path, state: dict[str, Any]) -> None:
    save_state_snapshot(path, state)


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    append_event(path, row)


def load_recent_events(path: Path, limit: int = 5) -> list[dict[str, Any]]:
    return load_recent_event_rows(path, limit=limit)


def defer_llm_fallback(
    *,
    event: dict[str, Any],
    state: dict[str, Any],
    key: str,
    max_seen: int,
    max_retries: int,
) -> dict[str, Any]:
    event["action"] = "hold-in-inbox"
    attempt = increment_attempt(state, key)
    event["attempt"] = attempt
    if attempt >= max_retries:
        event["status"] = "llm-fallback-max-retries"
        mark_seen(state, key, max_seen=max_seen)
        clear_attempt(state, key)
    else:
        event["status"] = "llm-fallback-deferred"
    return event


def wait_for_wake_trigger(
    *,
    timeout_seconds: float,
    probe_interval_seconds: float,
    wake_server: WakeSignalServer | None,
    last_hook_seq: int,
) -> tuple[int, dict[str, Any] | None]:
    deadline = time.time() + max(0.0, timeout_seconds)
    current_seq = max(0, int(last_hook_seq))
    probe_interval_seconds = max(0.5, float(probe_interval_seconds))
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return current_seq, None
        wait_slice = min(probe_interval_seconds, remaining)
        if wake_server is not None:
            signal = wake_server.wait(timeout=wait_slice)
            if signal is not None:
                return current_seq, {
                    "timestamp": now_iso(),
                    "action": "wake-signal",
                    "status": "received",
                    **signal.as_dict(),
                }
        else:
            time.sleep(wait_slice)
        try:
            hook_state = read_wake_hook_state()
        except Exception:
            continue
        seq = int(hook_state.get("seq", 0) or 0)
        if seq > current_seq:
            current_seq = seq
            return current_seq, {
                "timestamp": now_iso(),
                "action": "wake-signal",
                "status": "page-hook",
                "reason": str(hook_state.get("lastReason", "")),
                "fingerprint": str(hook_state.get("lastFingerprintPreview", "")),
                "source": "outlook-dom-hook-state",
                "path": "page-hook",
                "method": "observer",
                "seq": current_seq,
            }
        current_seq = max(current_seq, seq)


def message_key(row: dict[str, Any]) -> str:
    return message_cursor_key(row)


def mark_seen(state: dict[str, Any], key: str, *, max_seen: int) -> None:
    seen = [value for value in state.get("seen_keys", []) if value != key]
    seen.append(key)
    if len(seen) > max_seen:
        seen = seen[-max_seen:]
    state["seen_keys"] = seen


def clear_attempt(state: dict[str, Any], key: str) -> None:
    attempts = dict(state.get("attempt_counts", {}))
    attempts.pop(key, None)
    state["attempt_counts"] = attempts


def increment_attempt(state: dict[str, Any], key: str) -> int:
    attempts = dict(state.get("attempt_counts", {}))
    attempts[key] = int(attempts.get(key, 0)) + 1
    state["attempt_counts"] = attempts
    return attempts[key]


def notify_user(row: dict[str, Any], reason: str) -> bool:
    title = "Important Outlook Mail"
    subtitle = str(row.get("from", "")).replace('"', "'").strip()[:120]
    body = str(row.get("subject", "")).replace('"', "'").strip()[:220]
    if reason:
        body = f"{body} | {reason[:120].replace(chr(10), ' ')}"
    script = f'display notification "{body}" with title "{title}" subtitle "{subtitle}"'
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def feedback_scan_due(state: dict[str, Any], interval_minutes: int) -> bool:
    if interval_minutes <= 0:
        return False
    last_scan = str(state.get("last_feedback_scan_at", "")).strip()
    if not last_scan:
        return True
    try:
        previous = datetime.fromisoformat(last_scan)
    except ValueError:
        return True
    delta = datetime.now().astimezone() - previous.astimezone()
    return delta.total_seconds() >= interval_minutes * 60


def run_cycle(
    *,
    state_path: Path,
    event_log: Path,
    screens: int,
    limit: int,
    include_pinned: bool,
    rules_path: Path,
    examples_path: Path,
    notify: bool,
    bootstrap_seen: bool,
    max_seen: int,
    max_retries: int,
    suggestions_path: Path,
    feedback_path: Path,
    night_review_state_path: Path,
    night_review_event_log: Path,
) -> dict[str, Any]:
    ensure_outlook_session(DEFAULT_BROWSER, DEFAULT_PROFILE, DEFAULT_COOKIE_DOMAINS)

    rules = load_json(rules_path)
    examples = load_jsonl(examples_path)
    source_folder = str(rules.get("monitor_source_folder", "Inbox"))
    scan_screens = max(1, int(rules.get("monitor_scan_screens", 1)))
    max_scan_screens = max(scan_screens, int(rules.get("monitor_max_scan_screens", 6)))
    cursor_window = max(3, int(rules.get("monitor_cursor_window", 12)))
    opened = open_folder(source_folder)
    if not opened.get("ok"):
        raise BridgeError(f"Could not open Outlook folder {source_folder}: {opened}")
    wait_for_visible_options(recent_only=not include_pinned)

    state = load_state(state_path)
    seen = set(state.get("seen_keys", []))
    stop_keys = (
        {key for key in state.get("scan_cursor_keys", []) if key in seen}
        if state.get("initialized")
        else set()
    )
    rows = fetch_recent_messages(
        screens=scan_screens,
        max_screens=max_scan_screens,
        limit=limit,
        recent_only=not include_pinned,
        stop_keys=stop_keys,
    )
    triaged, summary = triage_recent_messages(rows, rules=rules, examples=examples)
    style_profile = load_style_profile(DEFAULT_STYLE_PROFILE)
    next_cursor_keys = top_cursor_keys(limit=cursor_window, recent_only=not include_pinned)
    unseen_cursor_keys = [key for key in next_cursor_keys if key not in seen]
    if triaged or not unseen_cursor_keys or not state.get("initialized"):
        state["scan_cursor_keys"] = next_cursor_keys
    folder_name = str(summary.get("nightly_digest_folder", "Night Review"))
    reminder_hour = int(rules.get("nightly_digest_hour_local", 21))
    restore_hour = int(rules.get("night_review_restore_hour_local", 7))
    restore_folder = str(rules.get("night_review_restore_folder", "Inbox"))
    feedback_scan_interval = max(0, int(rules.get("feedback_scan_interval_minutes", 60)))
    feedback_scan_screens = max(1, int(rules.get("feedback_scan_screens", 8)))
    feedback_scan_limit = max(1, int(rules.get("feedback_scan_limit", 40)))
    style_refresh_screens = max(1, int(rules.get("style_refresh_screens", 20)))
    style_refresh_limit = max(1, int(rules.get("style_refresh_limit", 80)))

    payload = {
        "timestamp": now_iso(),
        "total_visible": len(triaged),
        "new_visible": 0,
        "important_notified": 0,
        "night_moved": 0,
        "move_failures": 0,
        "baseline_only": False,
        "source_folder": source_folder,
        "nightly_digest_folder": folder_name,
        "night_review_restore_folder": restore_folder,
        "events": [],
    }
    if not triaged and unseen_cursor_keys and state.get("initialized"):
        payload["events"].append(
            {
                "type": "cursor-hold",
                "reason": "visible-unseen-rows-with-empty-fetch",
                "count": len(unseen_cursor_keys),
            }
        )

    if not folder_exists(folder_name):
        raise BridgeError(f"Outlook folder not found: {folder_name}")

    current_keys = [message_key(row) for row in triaged]
    if bootstrap_seen and not state.get("initialized"):
        for key in current_keys:
            mark_seen(state, key, max_seen=max_seen)
        state["initialized"] = True
        state["updated_at"] = now_iso()
        state["last_run"] = {**payload, "baseline_only": True}
        save_state(state_path, state)
        payload["baseline_only"] = True
        return payload

    for row in triaged:
        key = message_key(row)
        if key in seen:
            continue
        payload["new_visible"] += 1
        event = {
            "timestamp": now_iso(),
            "key": key,
            "from": row.get("from", ""),
            "subject": row.get("subject", ""),
            "bucket": row.get("bucket", ""),
            "target_folder": row.get("target_folder", ""),
        }

        if row.get("pinned"):
            event["action"] = "skip-pinned"
            event["status"] = "seen"
            mark_seen(state, key, max_seen=max_seen)
            clear_attempt(state, key)
        elif row.get("bucket") == "important_notify":
            event["action"] = "notify"
            full_message = None
            full_triage = None
            try:
                selection = select_visible_message(
                    str(row.get("dom_id", "")),
                    str(row.get("subject", "")),
                    sender=str(row.get("from", "")),
                    received_at=str(row.get("received_at", "")),
                    conversation_id=str(row.get("conversation_id", "")),
                )
                event["selection_for_draft"] = selection
                if selection.get("ok"):
                    full_message = selected_message_payload()
                    full_triage = classify_message_payload(full_message, rules, examples, style_profile=style_profile)
                    event["full_triage"] = {
                        "important": bool(full_triage.get("important")),
                        "category": full_triage.get("category", ""),
                        "action": full_triage.get("action", ""),
                        "reasons": full_triage.get("reasons", []),
                        "llm_judgment": full_triage.get("llm_judgment", {}),
                        "decision_source": full_triage.get("decision_source", ""),
                        "needs_manual_review": bool(full_triage.get("needs_manual_review")),
                    }
            except Exception as exc:
                event["draft_prep_error"] = str(exc)
            if full_triage and str(full_triage.get("decision_source", "")) == "llm-fallback":
                event["outlook_draft"] = {
                    "ok": False,
                    "reason": "llm-fallback-no-draft",
                }
                event["status"] = "logged" if not notify else ("notified" if notify_user(row, str(row.get("reason", ""))) else "notify-failed")
            elif full_message and full_triage and str(full_triage.get("draft_reply", "")).strip():
                event["outlook_draft"] = open_outlook_reply_draft(full_message, full_triage)
                if notify:
                    notified = notify_user(row, str(row.get("reason", "")))
                    event["status"] = "notified" if notified else "notify-failed"
                else:
                    event["status"] = "logged"
            else:
                event["outlook_draft"] = {
                    "ok": False,
                    "reason": "no-draft-reply-after-full-thread-parse",
                }
                if notify:
                    notified = notify_user(row, str(row.get("reason", "")))
                    event["status"] = "notified" if notified else "notify-failed"
                else:
                    event["status"] = "logged"
            if event["status"] == "notified":
                payload["important_notified"] += 1
            mark_seen(state, key, max_seen=max_seen)
            clear_attempt(state, key)
        elif row.get("bucket") in {"night_digest", "auto_action"}:
            attempt = int(state.get("attempt_counts", {}).get(key, 0))
            if attempt >= max_retries:
                event["action"] = "queue-auto-action" if row.get("bucket") == "auto_action" else "move-to-night-review"
                event["status"] = "max-retries-exhausted"
                event["attempt"] = attempt
                mark_seen(state, key, max_seen=max_seen)
            elif row.get("bucket") == "night_digest":
                selection = select_visible_message(
                    str(row.get("dom_id", "")),
                    str(row.get("subject", "")),
                    sender=str(row.get("from", "")),
                    received_at=str(row.get("received_at", "")),
                    conversation_id=str(row.get("conversation_id", "")),
                )
                event["selection_for_recheck"] = selection
                if selection.get("ok"):
                    try:
                        full_message = selected_message_payload()
                        full_triage = classify_message_payload(full_message, rules, examples, style_profile=style_profile)
                        event["full_triage"] = {
                            "important": bool(full_triage.get("important")),
                            "category": full_triage.get("category", ""),
                            "action": full_triage.get("action", ""),
                            "reasons": full_triage.get("reasons", []),
                            "llm_judgment": full_triage.get("llm_judgment", {}),
                            "decision_source": full_triage.get("decision_source", ""),
                            "needs_manual_review": bool(full_triage.get("needs_manual_review")),
                        }
                        if str(full_triage.get("decision_source", "")) == "llm-fallback":
                            defer_llm_fallback(
                                event=event,
                                state=state,
                                key=key,
                                max_seen=max_seen,
                                max_retries=max_retries,
                            )
                            payload["events"].append(event)
                            append_jsonl(event_log, event)
                            seen = set(state.get("seen_keys", []))
                            continue
                        if full_triage.get("important"):
                            event["action"] = "notify-after-recheck"
                            if str(full_triage.get("draft_reply", "")).strip():
                                event["outlook_draft"] = open_outlook_reply_draft(full_message, full_triage)
                            else:
                                event["outlook_draft"] = {
                                    "ok": False,
                                    "reason": "no-draft-reply-after-full-thread-parse",
                                }
                            event["status"] = "logged" if not notify else ("notified" if notify_user(full_message, str(full_triage.get("reasons", [""])[-1])) else "notify-failed")
                            if event["status"] == "notified":
                                payload["important_notified"] += 1
                            mark_seen(state, key, max_seen=max_seen)
                            clear_attempt(state, key)
                            payload["events"].append(event)
                            append_jsonl(event_log, event)
                            seen = set(state.get("seen_keys", []))
                            continue
                    except Exception as exc:
                        event["recheck_error"] = str(exc)
                result = move_message_to_folder(row, folder_name, mark_read_before_move=True)
                event["action"] = "move-to-night-review"
                event["result"] = result
                if result.get("ok"):
                    event["status"] = "moved"
                    event["night_review_record"] = register_pending_message(
                        night_review_state_path,
                        row,
                        moved_at=event["timestamp"],
                    )
                    payload["night_moved"] += 1
                    mark_seen(state, key, max_seen=max_seen)
                    clear_attempt(state, key)
                else:
                    event["status"] = "move-failed"
                    event["attempt"] = increment_attempt(state, key)
                    payload["move_failures"] += 1
            elif str(row.get("triage", {}).get("action", "")) == "queue-auto-approve-expense":
                selection = select_visible_message(
                    str(row.get("dom_id", "")),
                    str(row.get("subject", "")),
                    sender=str(row.get("from", "")),
                    received_at=str(row.get("received_at", "")),
                    conversation_id=str(row.get("conversation_id", "")),
                )
                event["action"] = "auto-approve-expense"
                event["selection_for_auto_action"] = selection
                if not selection.get("ok"):
                    event["status"] = "select-failed"
                    event["attempt"] = increment_attempt(state, key)
                    payload["move_failures"] += 1
                else:
                    result = attempt_expense_approval_from_selected()
                    event["result"] = result
                    if result.get("ok"):
                        event["status"] = "approved"
                        mark_seen(state, key, max_seen=max_seen)
                        clear_attempt(state, key)
                    elif result.get("opened"):
                        event["status"] = str(result.get("status") or "opened-manual-followup")
                        mark_seen(state, key, max_seen=max_seen)
                        clear_attempt(state, key)
                    else:
                        event["status"] = str(result.get("status") or "approve-failed")
                        event["attempt"] = increment_attempt(state, key)
                        payload["move_failures"] += 1
            else:
                result = move_message_to_folder(row, folder_name, mark_read_before_move=True)
                event["action"] = "queue-auto-action" if row.get("bucket") == "auto_action" else "move-to-night-review"
                event["result"] = result
                if result.get("ok"):
                    event["status"] = "moved"
                    event["night_review_record"] = register_pending_message(
                        night_review_state_path,
                        row,
                        moved_at=event["timestamp"],
                    )
                    payload["night_moved"] += 1
                    mark_seen(state, key, max_seen=max_seen)
                    clear_attempt(state, key)
                else:
                    event["status"] = "move-failed"
                    event["attempt"] = increment_attempt(state, key)
                    payload["move_failures"] += 1
        else:
            event["action"] = "log-only"
            event["status"] = "seen"
            mark_seen(state, key, max_seen=max_seen)
            clear_attempt(state, key)

        payload["events"].append(event)
        append_jsonl(event_log, event)
        seen = set(state.get("seen_keys", []))

    payload["night_review"] = process_night_review_cycle(
        state_path=night_review_state_path,
        event_log=night_review_event_log,
        folder_name=folder_name,
        restore_folder=restore_folder,
        reminder_hour=reminder_hour,
        restore_hour=restore_hour,
        screens=max(2, screens),
        limit=max(20, limit),
        notify=notify,
    )
    if feedback_scan_due(state, feedback_scan_interval):
        try:
            payload["draft_feedback_harvest"] = harvest_sent_feedback(
                folder_name="Sent Items",
                screens=feedback_scan_screens,
                limit=feedback_scan_limit,
                suggestions_path=suggestions_path,
                feedback_path=feedback_path,
            )
            if int(payload["draft_feedback_harvest"].get("harvested", 0)) > 0:
                payload["style_profile_refresh"] = refresh_style_profile(
                    screens=style_refresh_screens,
                    limit=style_refresh_limit,
                    feedback_path=feedback_path,
                    samples_output=DEFAULT_STYLE_SAMPLES,
                    profile_output=DEFAULT_STYLE_PROFILE,
                )
        except Exception as exc:
            payload["draft_feedback_harvest"] = {
                "status": "error",
                "error": str(exc),
            }
        state["last_feedback_scan_at"] = now_iso()
    state["initialized"] = True
    state["key_schema_version"] = 2
    state["updated_at"] = now_iso()
    state["last_run"] = payload
    save_state(state_path, state)
    return payload


def command_run_once(args: argparse.Namespace) -> int:
    payload = run_cycle(
        state_path=Path(args.state),
        event_log=Path(args.event_log),
        screens=args.screens,
        limit=args.limit,
        include_pinned=args.include_pinned,
        rules_path=Path(args.rules),
        examples_path=Path(args.examples),
        notify=not args.no_notify,
        bootstrap_seen=not args.no_bootstrap_seen,
        max_seen=args.max_seen,
        max_retries=args.max_retries,
        suggestions_path=Path(args.suggestions),
        feedback_path=Path(args.feedback),
        night_review_state_path=Path(args.night_review_state),
        night_review_event_log=Path(args.night_review_event_log),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_watch(args: argparse.Namespace) -> int:
    interval = max(10, int(args.interval))
    wake_probe_interval = max(1.0, float(args.wake_probe_interval))
    wake_server: WakeSignalServer | None = None
    last_hook_seq = 0
    if not args.no_wake_hook:
        wake_server = WakeSignalServer(
            host=args.wake_host,
            port=args.wake_port,
            event_log=Path(args.wake_event_log),
        )
        wake_server.start()
    while True:
        try:
            payload = run_cycle(
                state_path=Path(args.state),
                event_log=Path(args.event_log),
                screens=args.screens,
                limit=args.limit,
                include_pinned=args.include_pinned,
                rules_path=Path(args.rules),
                examples_path=Path(args.examples),
                notify=not args.no_notify,
                bootstrap_seen=not args.no_bootstrap_seen,
                max_seen=args.max_seen,
                max_retries=args.max_retries,
                suggestions_path=Path(args.suggestions),
                feedback_path=Path(args.feedback),
                night_review_state_path=Path(args.night_review_state),
                night_review_event_log=Path(args.night_review_event_log),
            )
            if wake_server is not None:
                payload["wake_hook"] = install_outlook_wake_hook(
                    host=args.wake_host,
                    port=args.wake_port,
                )
                last_hook_seq = max(last_hook_seq, int(payload["wake_hook"].get("seq", 0) or 0))
            print(json.dumps(payload, ensure_ascii=False), flush=True)
        except KeyboardInterrupt:
            if wake_server is not None:
                wake_server.stop()
            return 0
        except Exception as exc:
            error_event = {
                "timestamp": now_iso(),
                "action": "watch-cycle",
                "status": "error",
                "error": str(exc),
            }
            append_jsonl(Path(args.event_log), error_event)
            print(json.dumps(error_event, ensure_ascii=False), flush=True)
        if args.no_wake_hook:
            time.sleep(interval)
            continue
        last_hook_seq, wake_event = wait_for_wake_trigger(
            timeout_seconds=interval,
            probe_interval_seconds=wake_probe_interval,
            wake_server=wake_server,
            last_hook_seq=last_hook_seq,
        )
        if wake_event is not None:
            print(
                json.dumps(wake_event, ensure_ascii=False),
                flush=True,
            )


def command_status(args: argparse.Namespace) -> int:
    state = load_state(Path(args.state))
    payload = {
        "state_path": args.state,
        "event_log": args.event_log,
        "state": state,
        "recent_events": load_recent_events(Path(args.event_log), limit=args.limit),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Continuously monitor Outlook Web and triage new mail.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_arguments(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--screens", type=int, default=4)
        subparser.add_argument("--limit", type=int, default=20)
        subparser.add_argument("--include-pinned", action="store_true")
        subparser.add_argument("--rules", default=str(SHARED / "default_rules.json"))
        subparser.add_argument("--examples", default=str(SHARED / "example_labeled_emails.jsonl"))
        subparser.add_argument("--state", default=str(DEFAULT_STATE))
        subparser.add_argument("--event-log", default=str(DEFAULT_EVENT_LOG))
        subparser.add_argument("--action-log", default=str(DEFAULT_ACTION_LOG))
        subparser.add_argument("--suggestions", default=str(DEFAULT_SUGGESTIONS))
        subparser.add_argument("--feedback", default=str(DEFAULT_FEEDBACK))
        subparser.add_argument("--night-review-state", default=str(DEFAULT_NIGHT_REVIEW_STATE))
        subparser.add_argument("--night-review-event-log", default=str(DEFAULT_NIGHT_REVIEW_EVENT_LOG))
        subparser.add_argument("--wake-event-log", default=str(DEFAULT_WAKE_EVENT_LOG))
        subparser.add_argument("--no-notify", action="store_true")
        subparser.add_argument("--no-bootstrap-seen", action="store_true")
        subparser.add_argument("--max-seen", type=int, default=500)
        subparser.add_argument("--max-retries", type=int, default=3)

    run_once = subparsers.add_parser("run-once", help="Poll once and handle new Outlook mail.")
    add_common_arguments(run_once)
    run_once.set_defaults(func=command_run_once)

    watch = subparsers.add_parser("watch", help="Continuously poll Outlook Web and handle new mail.")
    add_common_arguments(watch)
    watch.add_argument("--interval", type=int, default=30, help="Polling interval in seconds.")
    watch.add_argument("--no-wake-hook", action="store_true", help="Disable the page-side wake hook and use pure polling.")
    watch.add_argument("--wake-host", default=DEFAULT_WAKE_HOST)
    watch.add_argument("--wake-port", type=int, default=DEFAULT_WAKE_PORT)
    watch.add_argument("--wake-probe-interval", type=float, default=2.0, help="How often to check the page-side wake observer between full cycles.")
    watch.set_defaults(func=command_watch)

    status = subparsers.add_parser("status", help="Show monitor state and recent events.")
    status.add_argument("--state", default=str(DEFAULT_STATE))
    status.add_argument("--event-log", default=str(DEFAULT_EVENT_LOG))
    status.add_argument("--limit", type=int, default=8)
    status.set_defaults(func=command_status)
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
