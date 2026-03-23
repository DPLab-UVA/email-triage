#!/usr/bin/env python3
"""Triage Mail.app messages with the shared rule engine."""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = ROOT / "shared"


def resolve_mail_app_cli() -> Path:
    env = Path(os.environ["MAIL_APP_MAILBOX_CLI"]).expanduser() if "MAIL_APP_MAILBOX_CLI" in os.environ else None
    candidates = [
        env,
        Path.home() / "Library/CloudStorage/Dropbox/notes/skills/mail-app-mailbox/scripts/mail_app_mailbox.py",
        ROOT / "skill-snapshots" / "mail-app-mailbox" / "scripts" / "mail_app_mailbox.py",
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return candidates[1]


MAIL_APP_CLI = resolve_mail_app_cli()
DEFAULT_RULES = SHARED_DIR / "default_rules.json"
DEFAULT_EXAMPLES = SHARED_DIR / "example_labeled_emails.jsonl"
DEFAULT_STATE = Path(__file__).with_name("mail_app_state.json")
DEFAULT_DRAFT_LOG = SHARED_DIR / "draft_suggestions.jsonl"
DEFAULT_FEEDBACK_LOG = SHARED_DIR / "draft_feedback.jsonl"
DEFAULT_FEEDBACK_STATE = SHARED_DIR / "draft_feedback_state.json"
DEFAULT_MAIL_CLI_TIMEOUT = 20.0


class TriageError(RuntimeError):
    """Raised for recoverable triage workflow errors."""


def load_triage_engine() -> Any:
    module_path = SHARED_DIR / "triage_engine.py"
    spec = importlib.util.spec_from_file_location("triage_engine", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load triage engine from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_rules_and_examples(engine: Any, rules: Path, examples: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return engine.load_json(rules), engine.load_jsonl(examples)


def run_mail_cli(*args: str, timeout: float | None = None) -> Any:
    try:
        process = subprocess.run(
            ["python3", str(MAIL_APP_CLI), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout or DEFAULT_MAIL_CLI_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        used_timeout = timeout or DEFAULT_MAIL_CLI_TIMEOUT
        raise TriageError(f"Mail CLI timed out after {used_timeout} seconds: {' '.join(args)}") from exc
    if process.returncode != 0:
        raise TriageError(process.stderr.strip() or process.stdout.strip() or "Mail CLI failed.")
    output = process.stdout.strip()
    return json.loads(output) if output else {}


def normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    payload = dict(message)
    payload["from"] = payload.get("sender", payload.get("from", ""))
    payload["mailbox_path"] = "/".join(
        part for part in [payload.get("account", ""), payload.get("mailbox", "")] if part
    )
    return payload


def selected_messages(*, include_body: bool, limit: int) -> list[dict[str, Any]]:
    cli_args = ["selected", "--limit", str(limit), "--json"]
    if include_body:
        cli_args.append("--include-body")
    payload = run_mail_cli(*cli_args)
    return payload.get("messages", [])


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"seen_ids": []}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def save_state(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_for_compare(text: str) -> str:
    return " ".join((text or "").split()).strip()


def message_key(mailbox: str, message_id: str | int) -> str:
    return f"{mailbox}::{message_id}"


def notify(title: str, subtitle: str, message: str) -> None:
    script = f'display notification "{message}" with title "{title}" subtitle "{subtitle}"'
    subprocess.run(["osascript", "-e", script], check=False)


def triage_one(mailbox: str, message_id: int, rules: Path, examples: Path) -> dict[str, Any]:
    engine = load_triage_engine()
    message_payload = run_mail_cli("read", "--mailbox", mailbox, "--id", str(message_id), "--json")
    message = normalize_message(message_payload["message"])
    message["mailbox"] = message_payload["mailbox"]["path"]
    rules_payload, examples_payload = load_rules_and_examples(engine, rules, examples)
    return engine.triage_message(message, rules_payload, examples_payload)


def load_message(mailbox: str, message_id: int) -> dict[str, Any]:
    message_payload = run_mail_cli("read", "--mailbox", mailbox, "--id", str(message_id), "--json")
    message = normalize_message(message_payload["message"])
    message["mailbox"] = message_payload["mailbox"]["path"]
    return message


def command_message(args: argparse.Namespace) -> int:
    result = triage_one(args.mailbox, args.id, Path(args.rules), Path(args.examples))
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def command_selected(args: argparse.Namespace) -> int:
    engine = load_triage_engine()
    rules_path = Path(args.rules)
    examples_path = Path(args.examples)
    rules_payload, examples_payload = load_rules_and_examples(engine, rules_path, examples_path)
    rows = selected_messages(include_body=args.include_body, limit=args.limit)
    results = []
    for row in rows:
        message = normalize_message(row)
        result = engine.triage_message(message, rules_payload, examples_payload)
        result["source_message"] = message
        results.append(result)
    print(json.dumps(results, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def reply_subject(subject: str) -> str:
    clean = (subject or "").strip()
    if not clean:
        return "Re:"
    return clean if clean.lower().startswith("re:") else f"Re: {clean}"


def derive_reply_address(engine: Any, message: dict[str, Any]) -> str:
    reply_to = normalize_for_compare(message.get("reply_to", ""))
    if reply_to:
        reply_to_address = engine.sender_email(reply_to)
        if reply_to_address and "@" in reply_to_address:
            return reply_to_address
    sender_address = engine.sender_email(message.get("from", ""))
    return sender_address if sender_address and "@" in sender_address else ""


def should_auto_draft(*, reply_address: str, result: dict[str, Any], force: bool) -> bool:
    if force:
        return True
    local_part = reply_address.split("@", 1)[0].lower()
    if any(token in local_part for token in ["noreply", "no-reply", "do-not-reply", "donotreply"]):
        return False
    if result.get("category") in {"bulk", "review_invitation"}:
        return False
    return True


def create_draft_for_message(
    *,
    engine: Any,
    message: dict[str, Any],
    result: dict[str, Any],
    rules_payload: dict[str, Any],
    visible: bool,
    account: str | None,
    force: bool,
    draft_log: Path,
) -> dict[str, Any]:
    reply_address = derive_reply_address(engine, message)
    if not reply_address:
        raise TriageError(f"Unable to derive reply address from sender/reply-to: {message.get('from', '')}")
    if not should_auto_draft(reply_address=reply_address, result=result, force=force):
        return {
            "draft_created": False,
            "reason": "message should notify but is not suitable for an automatic reply draft",
            "reply_to": reply_address,
            "triage": result,
        }

    draft_body = result["draft_reply"]
    if not draft_body and force:
        draft_body = engine.build_draft(message, rules_payload, result["category"])
    if not draft_body:
        return {
            "draft_created": False,
            "reason": "message did not cross the importance threshold",
            "reply_to": reply_address,
            "triage": result,
        }

    compose_args = [
        "compose",
        "--to",
        reply_address,
        "--subject",
        reply_subject(message.get("subject", "")),
        "--body",
        draft_body,
        "--json",
    ]
    account_name = account or message.get("account", "")
    if account_name:
        compose_args.extend(["--account", account_name])
    if visible:
        compose_args.append("--visible")
    draft_payload = run_mail_cli(*compose_args)
    payload = {
        "draft_created": True,
        "draft": draft_payload,
        "reply_to": reply_address,
        "triage": result,
    }
    append_jsonl(
        draft_log,
        {
            "created_at": utc_now_iso(),
            "source_message": {
                "account": message.get("account", ""),
                "mailbox": message.get("mailbox", ""),
                "id": message.get("id", ""),
                "message_id": message.get("message_id", ""),
                "from": message.get("from", ""),
                "reply_to": message.get("reply_to", ""),
                "subject": message.get("subject", ""),
            },
            "draft": {
                "to": reply_address,
                "subject": reply_subject(message.get("subject", "")),
                "body": draft_body,
                "mail_draft_id": draft_payload.get("id", ""),
                "sender": draft_payload.get("sender", ""),
            },
            "triage": result,
        },
    )
    return payload


def command_draft_selected(args: argparse.Namespace) -> int:
    engine = load_triage_engine()
    rules_path = Path(args.rules)
    examples_path = Path(args.examples)
    rules_payload, examples_payload = load_rules_and_examples(engine, rules_path, examples_path)
    rows = selected_messages(include_body=True, limit=1)
    if not rows:
        raise TriageError("No selected message in Mail.app.")
    message = normalize_message(rows[0])
    result = engine.triage_message(message, rules_payload, examples_payload)
    payload = create_draft_for_message(
        engine=engine,
        message=message,
        result=result,
        rules_payload=rules_payload,
        visible=args.visible,
        account=args.account,
        force=args.force,
        draft_log=Path(args.draft_log),
    )
    if not payload["draft_created"]:
        payload["reason"] = "selected message did not cross the importance threshold"
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def command_draft_message(args: argparse.Namespace) -> int:
    engine = load_triage_engine()
    rules_path = Path(args.rules)
    examples_path = Path(args.examples)
    rules_payload, examples_payload = load_rules_and_examples(engine, rules_path, examples_path)
    message = load_message(args.mailbox, args.id)
    result = engine.triage_message(message, rules_payload, examples_payload)
    payload = create_draft_for_message(
        engine=engine,
        message=message,
        result=result,
        rules_payload=rules_payload,
        visible=args.visible,
        account=args.account,
        force=args.force,
        draft_log=Path(args.draft_log),
    )
    if not payload["draft_created"]:
        payload["reason"] = "message did not cross the importance threshold"
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def command_reconcile_sent(args: argparse.Namespace) -> int:
    draft_log_path = Path(args.draft_log)
    feedback_log_path = Path(args.feedback_log)
    feedback_state_path = Path(args.feedback_state)
    draft_rows = load_jsonl(draft_log_path)
    if not draft_rows:
        print(json.dumps({"ok": True, "matched": 0, "message": "no draft suggestions logged yet"}, ensure_ascii=False, indent=2))
        return 0

    state = load_state(feedback_state_path)
    processed_sent_ids = set(state.get("processed_sent_ids", []))
    listing = run_mail_cli("list", "--mailbox", args.mailbox, "--limit", str(args.limit), "--json", timeout=args.list_timeout)

    matched = []
    for row in listing.get("messages", []):
        sent_id = row.get("id", "")
        sent_key = message_key(args.mailbox, sent_id)
        if not sent_id or sent_key in processed_sent_ids:
            continue
        sent_subject = row.get("subject", "")
        candidates = [draft for draft in draft_rows if draft.get("draft", {}).get("subject", "") == sent_subject]
        if not candidates:
            continue
        try:
            sent_payload = run_mail_cli("read", "--mailbox", args.mailbox, "--id", str(sent_id), "--json", timeout=args.read_timeout)
        except TriageError:
            continue
        sent_message = normalize_message(sent_payload["message"])
        sent_body = normalize_for_compare(sent_message.get("body", ""))
        best_row = None
        best_ratio = -1.0
        for draft in candidates:
            draft_body = normalize_for_compare(draft.get("draft", {}).get("body", ""))
            ratio = difflib.SequenceMatcher(None, draft_body, sent_body).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_row = draft
        if best_row is None:
            continue
        outcome = "sent_as_is" if best_ratio >= 0.995 else "sent_modified"
        feedback = {
            "recorded_at": utc_now_iso(),
            "mailbox": args.mailbox,
            "sent_message": {
                "id": sent_id,
                "message_id": sent_message.get("message_id", ""),
                "subject": sent_subject,
                "from": sent_message.get("from", ""),
            },
            "matched_draft": {
                "created_at": best_row.get("created_at", ""),
                "source_subject": best_row.get("source_message", {}).get("subject", ""),
                "draft_subject": best_row.get("draft", {}).get("subject", ""),
            },
            "similarity": round(best_ratio, 4),
            "outcome": outcome,
        }
        append_jsonl(feedback_log_path, feedback)
        processed_sent_ids.add(sent_key)
        matched.append(feedback)

    state["processed_sent_ids"] = sorted(processed_sent_ids)
    save_state(feedback_state_path, state)
    print(json.dumps({"ok": True, "matched": len(matched), "results": matched}, ensure_ascii=False, indent=2))
    return 0


def command_poll(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    state = load_state(state_path)
    seen_ids = set(state.get("seen_ids", []))
    listing = run_mail_cli("list", "--mailbox", args.mailbox, "--limit", str(args.limit), "--json")
    results = []
    for row in listing.get("messages", []):
        if args.unread_only and row.get("read") == "true":
            continue
        row_key = message_key(args.mailbox, row["id"])
        if not args.include_seen and row_key in seen_ids:
            continue
        result = triage_one(args.mailbox, int(row["id"]), Path(args.rules), Path(args.examples))
        results.append(result)
        seen_ids.add(row_key)
        if args.notify and result["important"]:
            notify(
                "Important mail",
                row.get("sender", "")[:60],
                row.get("subject", "")[:120],
            )
    state["seen_ids"] = sorted(seen_ids)
    save_state(state_path, state)
    print(json.dumps(results, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def command_bulk_prelabel(args: argparse.Namespace) -> int:
    engine = load_triage_engine()
    rules_path = Path(args.rules)
    examples_path = Path(args.examples)
    rules_payload, examples_payload = load_rules_and_examples(engine, rules_path, examples_path)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records_written = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for mailbox in args.mailbox:
            listing = run_mail_cli(
                "list",
                "--mailbox",
                mailbox,
                "--limit",
                str(args.limit),
                "--json",
                timeout=args.list_timeout,
            )
            for row in listing.get("messages", []):
                if args.unread_only and row.get("read") == "true":
                    continue
                try:
                    message_payload = run_mail_cli(
                        "read",
                        "--mailbox",
                        mailbox,
                        "--id",
                        str(row["id"]),
                        "--json",
                        timeout=args.read_timeout,
                    )
                except TriageError as exc:
                    print(f"Skipping {mailbox} #{row.get('id')}: {exc}", file=sys.stderr)
                    continue
                message = normalize_message(message_payload["message"])
                message["mailbox"] = message_payload["mailbox"]["path"]
                result = engine.triage_message(message, rules_payload, examples_payload)
                record = {
                    "label": "important" if result["important"] else "not_important",
                    "mailbox": mailbox,
                    "source_message": message,
                    "triage": result,
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                records_written += 1

    print(
        json.dumps(
            {
                "ok": True,
                "records_written": records_written,
                "output": str(output_path),
                "mailboxes": args.mailbox,
                "limit_per_mailbox": args.limit,
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Triage Mail.app messages with the shared engine.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    message_parser = subparsers.add_parser("message", help="Triage one Mail.app message.")
    message_parser.add_argument("--mailbox", required=True)
    message_parser.add_argument("--id", required=True, type=int)
    message_parser.add_argument("--rules", default=str(DEFAULT_RULES))
    message_parser.add_argument("--examples", default=str(DEFAULT_EXAMPLES))
    message_parser.set_defaults(func=command_message)

    selected_parser = subparsers.add_parser("selected", help="Triage currently selected Mail.app messages.")
    selected_parser.add_argument("--limit", type=int, default=10)
    selected_parser.add_argument("--include-body", action="store_true")
    selected_parser.add_argument("--rules", default=str(DEFAULT_RULES))
    selected_parser.add_argument("--examples", default=str(DEFAULT_EXAMPLES))
    selected_parser.set_defaults(func=command_selected)

    draft_parser = subparsers.add_parser(
        "draft-selected",
        help="Create a Mail.app draft reply for the first selected message when it is important.",
    )
    draft_parser.add_argument("--rules", default=str(DEFAULT_RULES))
    draft_parser.add_argument("--examples", default=str(DEFAULT_EXAMPLES))
    draft_parser.add_argument("--visible", action="store_true")
    draft_parser.add_argument("--account", help="Override the sending account name.")
    draft_parser.add_argument("--force", action="store_true", help="Create a draft even if the message is low priority.")
    draft_parser.add_argument("--draft-log", default=str(DEFAULT_DRAFT_LOG))
    draft_parser.set_defaults(func=command_draft_selected)

    draft_message_parser = subparsers.add_parser(
        "draft-message",
        help="Create a Mail.app draft reply for one message by mailbox and id.",
    )
    draft_message_parser.add_argument("--mailbox", required=True)
    draft_message_parser.add_argument("--id", required=True, type=int)
    draft_message_parser.add_argument("--rules", default=str(DEFAULT_RULES))
    draft_message_parser.add_argument("--examples", default=str(DEFAULT_EXAMPLES))
    draft_message_parser.add_argument("--visible", action="store_true")
    draft_message_parser.add_argument("--account", help="Override the sending account name.")
    draft_message_parser.add_argument("--force", action="store_true", help="Create a draft even if the message is low priority.")
    draft_message_parser.add_argument("--draft-log", default=str(DEFAULT_DRAFT_LOG))
    draft_message_parser.set_defaults(func=command_draft_message)

    poll_parser = subparsers.add_parser("poll", help="Triage recent messages from one mailbox.")
    poll_parser.add_argument("--mailbox", required=True)
    poll_parser.add_argument("--limit", type=int, default=10)
    poll_parser.add_argument("--rules", default=str(DEFAULT_RULES))
    poll_parser.add_argument("--examples", default=str(DEFAULT_EXAMPLES))
    poll_parser.add_argument("--state", default=str(DEFAULT_STATE))
    poll_parser.add_argument("--notify", action="store_true")
    poll_parser.add_argument("--include-seen", action="store_true")
    poll_parser.add_argument("--unread-only", action="store_true")
    poll_parser.set_defaults(func=command_poll)

    feedback_parser = subparsers.add_parser(
        "reconcile-sent",
        help="Compare recent sent messages against logged draft suggestions.",
    )
    feedback_parser.add_argument("--mailbox", required=True)
    feedback_parser.add_argument("--limit", type=int, default=20)
    feedback_parser.add_argument("--draft-log", default=str(DEFAULT_DRAFT_LOG))
    feedback_parser.add_argument("--feedback-log", default=str(DEFAULT_FEEDBACK_LOG))
    feedback_parser.add_argument("--feedback-state", default=str(DEFAULT_FEEDBACK_STATE))
    feedback_parser.add_argument("--list-timeout", type=float, default=15.0)
    feedback_parser.add_argument("--read-timeout", type=float, default=8.0)
    feedback_parser.set_defaults(func=command_reconcile_sent)

    bulk_parser = subparsers.add_parser(
        "bulk-prelabel",
        help="Load more messages from one or more mailboxes and write prelabels to JSONL.",
    )
    bulk_parser.add_argument("--mailbox", action="append", required=True, help="Mailbox path. Repeat for multiple inboxes.")
    bulk_parser.add_argument("--limit", type=int, default=10, help="Maximum messages to load per mailbox.")
    bulk_parser.add_argument("--output", required=True, help="Output JSONL path.")
    bulk_parser.add_argument("--rules", default=str(DEFAULT_RULES))
    bulk_parser.add_argument("--examples", default=str(DEFAULT_EXAMPLES))
    bulk_parser.add_argument("--unread-only", action="store_true")
    bulk_parser.add_argument("--list-timeout", type=float, default=15.0)
    bulk_parser.add_argument("--read-timeout", type=float, default=8.0)
    bulk_parser.set_defaults(func=command_bulk_prelabel)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except TriageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
