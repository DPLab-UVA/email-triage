#!/usr/bin/env python3
"""Stable entrypoint for the local mail triage prototype on this Mac."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path("/Users/tianhao/Downloads/email-triage-lab")
MAIL_TRIAGE = PROJECT_ROOT / "mail-app" / "mail_app_triage.py"
CAPTURES = PROJECT_ROOT / "shared" / "captured_outlook_reports.jsonl"
QUEUE = PROJECT_ROOT / "shared" / "prelabeled_review_queue.jsonl"
RULES = PROJECT_ROOT / "shared" / "default_rules.json"
EXAMPLES = PROJECT_ROOT / "shared" / "example_labeled_emails.jsonl"
SERVER_HEALTH = "http://127.0.0.1:8765/health"
FAST_PIPELINE = PROJECT_ROOT / "shared" / "fast_header_pipeline.py"
REVIEW_INVITE_AUTO_DECLINE = Path(__file__).with_name("review_invite_auto_decline.py")
NIGHT_DIGEST = PROJECT_ROOT / "shared" / "night_digest_queue.jsonl"
AUTO_ACTION_LOG = PROJECT_ROOT / "shared" / "auto_action_log.jsonl"
COMMON_INBOXES = ["Exchange/Inbox", "Google/INBOX"]
COMMON_SENT_MAILBOXES = [
    "Exchange/Sent Messages",
    "Exchange/Sent Items",
    "Google/Sent Mail",
    "Google/[Gmail]/Sent Mail",
]
MAIL_TRIAGE_TIMEOUT = 45.0
HELPER_TIMEOUT = 45.0


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_mail_triage(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["python3", str(MAIL_TRIAGE), *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=MAIL_TRIAGE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            exc.cmd,
            124,
            exc.stdout or "",
            (exc.stderr or "") + f"\nTimed out after {MAIL_TRIAGE_TIMEOUT} seconds.",
        )


def run_mail_triage_json(*args: str) -> tuple[int, object, str]:
    result = run_mail_triage(*args)
    stdout = result.stdout.strip()
    payload: object = []
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {"raw_stdout": stdout}
    return result.returncode, payload, result.stderr


def run_json_command(cmd: list[str]) -> tuple[int, object, str]:
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=False, timeout=HELPER_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, {}, f"Timed out after {HELPER_TIMEOUT} seconds."
    stdout = result.stdout.strip()
    payload: object = {}
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {"raw_stdout": stdout}
    return result.returncode, payload, result.stderr


def command_status(_: argparse.Namespace) -> int:
    payload = {
        "project_root": str(PROJECT_ROOT),
        "mail_triage_exists": MAIL_TRIAGE.exists(),
        "captures_exists": CAPTURES.exists(),
        "queue_exists": QUEUE.exists(),
        "rules_exists": RULES.exists(),
        "capture_count": len(load_jsonl(CAPTURES)),
        "queue_count": len(load_jsonl(QUEUE)),
    }
    try:
        with urllib.request.urlopen(SERVER_HEALTH, timeout=1.5) as response:
            payload["server_health"] = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        payload["server_health"] = {"ok": False, "error": str(exc)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_queue_summary(args: argparse.Namespace) -> int:
    rows = load_jsonl(QUEUE)
    if not rows:
        print("No review queue found.")
        return 0
    limit = args.limit
    important = [row for row in rows if row.get("tentative_label") == "important"]
    not_important = [row for row in rows if row.get("tentative_label") == "not_important"]
    summary = {
        "total": len(rows),
        "important": len(important),
        "not_important": len(not_important),
        "sample": rows[:limit],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def command_review_list(args: argparse.Namespace) -> int:
    rows = load_jsonl(QUEUE)
    if args.label:
        rows = [row for row in rows if row.get("tentative_label") == args.label]
    print(json.dumps(rows[: args.limit], ensure_ascii=False, indent=2))
    return 0


def find_queue_matches(subject: str, sender: str | None = None) -> list[tuple[int, dict]]:
    rows = load_jsonl(QUEUE)
    subject_lower = subject.lower()
    sender_lower = sender.lower() if sender else None
    matches: list[tuple[int, dict]] = []
    for index, row in enumerate(rows):
        row_subject = str(row.get("subject_guess", ""))
        row_sender = str(row.get("sender_guess", ""))
        if subject_lower not in row_subject.lower():
            continue
        if sender_lower and sender_lower not in row_sender.lower():
            continue
        matches.append((index, row))
    return matches


def command_correct_label(args: argparse.Namespace) -> int:
    rows = load_jsonl(QUEUE)
    matches = find_queue_matches(args.subject, args.sender)
    if not matches:
        print(json.dumps({"ok": False, "error": "no matching queue item"}, ensure_ascii=False, indent=2))
        return 1
    if len(matches) > 1:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "multiple matches",
                    "matches": [
                        {
                            "subject_guess": row.get("subject_guess", ""),
                            "sender_guess": row.get("sender_guess", ""),
                            "tentative_label": row.get("tentative_label", ""),
                        }
                        for _, row in matches
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    index, row = matches[0]
    row["tentative_label"] = args.label
    row["needs_user_review"] = False
    row["corrected_by_user"] = True
    if args.note:
        row["correction_note"] = args.note
    rows[index] = row
    write_jsonl(QUEUE, rows)
    print(json.dumps({"ok": True, "updated": row}, ensure_ascii=False, indent=2))
    return 0


def command_promote_example(args: argparse.Namespace) -> int:
    matches = find_queue_matches(args.subject, args.sender)
    if not matches:
        print(json.dumps({"ok": False, "error": "no matching queue item"}, ensure_ascii=False, indent=2))
        return 1
    if len(matches) > 1:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "multiple matches",
                    "matches": [
                        {
                            "subject_guess": row.get("subject_guess", ""),
                            "sender_guess": row.get("sender_guess", ""),
                            "tentative_label": row.get("tentative_label", ""),
                        }
                        for _, row in matches
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    _, row = matches[0]
    label = args.label or row.get("tentative_label") or "important"
    record = {
        "label": label,
        "from": row.get("sender_guess", ""),
        "subject": row.get("subject_guess", ""),
        "body": row.get("body_guess", ""),
        "notes": args.note or row.get("reason", "Promoted from tentative review queue."),
    }
    existing = load_jsonl(EXAMPLES)
    existing.append(record)
    write_jsonl(EXAMPLES, existing)
    print(json.dumps({"ok": True, "appended": record}, ensure_ascii=False, indent=2))
    return 0


def command_captures_tail(args: argparse.Namespace) -> int:
    rows = load_jsonl(CAPTURES)
    sample = rows[-args.limit :]
    normalized = []
    for row in sample:
        msg = row.get("normalized_message", {})
        triage = row.get("triage", {})
        normalized.append(
            {
                "captured_at": row.get("captured_at", ""),
                "subject": msg.get("subject", ""),
                "from": msg.get("from", ""),
                "important": triage.get("important", False),
                "category": triage.get("category", ""),
                "action": triage.get("action", ""),
            }
        )
    print(json.dumps(normalized, ensure_ascii=False, indent=2))
    return 0


def command_poll_mail(args: argparse.Namespace) -> int:
    cmd = ["poll", "--mailbox", args.mailbox, "--limit", str(args.limit)]
    if args.include_seen:
        cmd.append("--include-seen")
    result = run_mail_triage(*cmd)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def command_draft_selected(args: argparse.Namespace) -> int:
    cmd = ["draft-selected"]
    if args.visible:
        cmd.append("--visible")
    result = run_mail_triage(*cmd)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def command_reconcile_sent(args: argparse.Namespace) -> int:
    result = run_mail_triage("reconcile-sent", "--mailbox", args.mailbox, "--limit", str(args.limit))
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def command_draft_message(args: argparse.Namespace) -> int:
    cmd = ["draft-message", "--mailbox", args.mailbox, "--id", str(args.id)]
    if args.visible:
        cmd.append("--visible")
    if args.force:
        cmd.append("--force")
    result = run_mail_triage(*cmd)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def command_fast_pipeline(_: argparse.Namespace) -> int:
    result = subprocess.run(
        ["python3", str(FAST_PIPELINE)],
        text=True,
        capture_output=True,
        check=False,
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def command_auto_decline_selected(args: argparse.Namespace) -> int:
    cmd = ["python3", str(REVIEW_INVITE_AUTO_DECLINE)]
    if args.open:
        cmd.append("--open")
    if args.json:
        cmd.append("--json")
    if args.message_id is not None:
        cmd.extend(["--message-id", str(args.message_id)])
    if args.subject_query:
        cmd.extend(["--subject-query", args.subject_query])
    for mailbox in args.mailbox:
        cmd.extend(["--mailbox", mailbox])
    returncode, payload, stderr = run_json_command(cmd)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif isinstance(payload, dict) and payload:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stderr.write(stderr)
    return returncode


def command_auto_run_once(args: argparse.Namespace) -> int:
    mailboxes = args.mailbox or COMMON_INBOXES
    sent_mailboxes = args.sent_mailbox or COMMON_SENT_MAILBOXES
    summary = {
        "started_at": utc_now_iso(),
        "mailboxes": [],
        "drafts_created": [],
        "auto_declined": [],
        "digest_added": 0,
        "sent_feedback": [],
        "errors": [],
    }

    for mailbox in mailboxes:
        cmd = ["poll", "--mailbox", mailbox, "--limit", str(args.limit), "--unread-only"]
        if args.include_seen:
            cmd.append("--include-seen")
        if args.notify:
            cmd.append("--notify")
        returncode, payload, stderr = run_mail_triage_json(*cmd)
        if returncode != 0:
            summary["errors"].append({"stage": "poll", "mailbox": mailbox, "error": stderr.strip() or "poll failed"})
            continue
        rows = payload if isinstance(payload, list) else []
        mailbox_summary = {
            "mailbox": mailbox,
            "triaged": len(rows),
            "important": sum(1 for row in rows if row.get("important")),
            "digest_later": sum(1 for row in rows if row.get("action") == "digest-later"),
            "review_invites": sum(1 for row in rows if row.get("action") == "queue-auto-decline-review-invite"),
        }
        summary["mailboxes"].append(mailbox_summary)

        for row in rows:
            message = row.get("message", {})
            mailbox_id = message.get("mailbox_id")
            if not mailbox_id:
                continue

            if row.get("action") == "digest-later":
                append_jsonl(
                    NIGHT_DIGEST,
                    {
                        "queued_at": utc_now_iso(),
                        "mailbox": mailbox,
                        "message": message,
                        "triage": row,
                    },
                )
                summary["digest_added"] += 1

            if args.auto_decline_review_invites and row.get("action") == "queue-auto-decline-review-invite":
                cmd = [
                    "python3",
                    str(REVIEW_INVITE_AUTO_DECLINE),
                    "--mailbox",
                    mailbox,
                    "--message-id",
                    str(mailbox_id),
                    "--json",
                ]
                if args.open_auto_decline:
                    cmd.append("--open")
                returncode, decline_payload, stderr = run_json_command(cmd)
                if returncode == 0:
                    append_jsonl(
                        AUTO_ACTION_LOG,
                        {
                            "recorded_at": utc_now_iso(),
                            "action": "auto_decline_review_invite",
                            "mailbox": mailbox,
                            "mailbox_id": mailbox_id,
                            "payload": decline_payload,
                        },
                    )
                    summary["auto_declined"].append(decline_payload)
                else:
                    summary["errors"].append(
                        {
                            "stage": "auto-decline",
                            "mailbox": mailbox,
                            "mailbox_id": mailbox_id,
                            "error": stderr.strip() or "auto-decline failed",
                        }
                    )

            if args.draft_important and row.get("important") and row.get("draft_reply"):
                draft_cmd = ["draft-message", "--mailbox", mailbox, "--id", str(mailbox_id)]
                if args.visible_drafts:
                    draft_cmd.append("--visible")
                returncode, draft_payload, stderr = run_mail_triage_json(*draft_cmd)
                if returncode == 0:
                    append_jsonl(
                        AUTO_ACTION_LOG,
                        {
                            "recorded_at": utc_now_iso(),
                            "action": "create_draft",
                            "mailbox": mailbox,
                            "mailbox_id": mailbox_id,
                            "payload": draft_payload,
                        },
                    )
                    summary["drafts_created"].append(draft_payload)
                else:
                    summary["errors"].append(
                        {
                            "stage": "draft",
                            "mailbox": mailbox,
                            "mailbox_id": mailbox_id,
                            "error": stderr.strip() or "draft creation failed",
                        }
                    )

    for sent_mailbox in sent_mailboxes:
        returncode, payload, stderr = run_mail_triage_json("reconcile-sent", "--mailbox", sent_mailbox, "--limit", str(args.sent_limit))
        if returncode == 0:
            result_rows = payload.get("results", []) if isinstance(payload, dict) else []
            if result_rows:
                summary["sent_feedback"].extend(result_rows)
        else:
            summary["errors"].append({"stage": "reconcile-sent", "mailbox": sent_mailbox, "error": stderr.strip() or "reconcile failed"})

    append_jsonl(AUTO_ACTION_LOG, {"recorded_at": utc_now_iso(), "action": "auto_run_once_summary", "summary": summary})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate the local mail triage prototype.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Summarize local triage state.")
    status.set_defaults(func=command_status)

    queue_summary = subparsers.add_parser("queue-summary", help="Summarize the tentative review queue.")
    queue_summary.add_argument("--limit", type=int, default=10)
    queue_summary.set_defaults(func=command_queue_summary)

    review_list = subparsers.add_parser("review-list", help="List tentative review items.")
    review_list.add_argument("--limit", type=int, default=20)
    review_list.add_argument("--label", choices=["important", "not_important"])
    review_list.set_defaults(func=command_review_list)

    captures_tail = subparsers.add_parser("captures-tail", help="Show recent Outlook Web captures.")
    captures_tail.add_argument("--limit", type=int, default=10)
    captures_tail.set_defaults(func=command_captures_tail)

    poll_mail = subparsers.add_parser("poll-mail", help="Run Mail.app triage polling for one mailbox.")
    poll_mail.add_argument("--mailbox", required=True)
    poll_mail.add_argument("--limit", type=int, default=10)
    poll_mail.add_argument("--include-seen", action="store_true")
    poll_mail.set_defaults(func=command_poll_mail)

    draft_selected = subparsers.add_parser("draft-selected", help="Draft a reply for the selected Mail.app message.")
    draft_selected.add_argument("--visible", action="store_true")
    draft_selected.set_defaults(func=command_draft_selected)

    draft_message = subparsers.add_parser("draft-message", help="Draft a reply for one Mail.app message by mailbox and id.")
    draft_message.add_argument("--mailbox", required=True)
    draft_message.add_argument("--id", required=True, type=int)
    draft_message.add_argument("--visible", action="store_true")
    draft_message.add_argument("--force", action="store_true")
    draft_message.set_defaults(func=command_draft_message)

    reconcile_sent = subparsers.add_parser(
        "reconcile-sent",
        help="Compare recent sent messages against logged draft suggestions.",
    )
    reconcile_sent.add_argument("--mailbox", required=True)
    reconcile_sent.add_argument("--limit", type=int, default=20)
    reconcile_sent.set_defaults(func=command_reconcile_sent)

    fast_pipeline = subparsers.add_parser("fast-pipeline", help="Build a fast header-first review queue and summary.")
    fast_pipeline.set_defaults(func=command_fast_pipeline)

    auto_decline = subparsers.add_parser(
        "auto-decline-selected",
        help="Open the best unavailable/decline URL from the selected or specified Mail.app review invitation.",
    )
    auto_decline.add_argument("--open", action="store_true", help="Actually open the best URL.")
    auto_decline.add_argument("--json", action="store_true", help="Emit JSON output.")
    auto_decline.add_argument("--message-id", type=int, help="Mail.app internal id of the target message.")
    auto_decline.add_argument("--subject-query", help="Find a message by subject substring.")
    auto_decline.add_argument("--mailbox", action="append", default=[], help="Mailbox path. Repeatable.")
    auto_decline.set_defaults(func=command_auto_decline_selected)

    auto_run = subparsers.add_parser(
        "auto-run-once",
        help="Poll inboxes once, auto-decline review invitations, create important drafts, and reconcile sent feedback.",
    )
    auto_run.add_argument("--mailbox", action="append", help="Inbox mailbox path. Repeat for multiple inboxes.")
    auto_run.add_argument("--sent-mailbox", action="append", help="Sent mailbox path. Repeat for multiple mailboxes.")
    auto_run.add_argument("--limit", type=int, default=10)
    auto_run.add_argument("--sent-limit", type=int, default=20)
    auto_run.add_argument("--include-seen", action="store_true")
    auto_run.add_argument("--notify", action="store_true")
    auto_run.add_argument("--draft-important", action="store_true", default=True)
    auto_run.add_argument("--auto-decline-review-invites", action="store_true", default=True)
    auto_run.add_argument("--visible-drafts", action="store_true", help="Open draft windows visibly.")
    auto_run.add_argument("--open-auto-decline", action="store_true", default=True, help="Open decline URLs in the browser.")
    auto_run.set_defaults(func=command_auto_run_once)

    correct_label = subparsers.add_parser("correct-label", help="Correct one tentative label in the review queue.")
    correct_label.add_argument("--subject", required=True, help="Substring match against subject_guess.")
    correct_label.add_argument("--sender", help="Optional substring match against sender_guess.")
    correct_label.add_argument("--label", required=True, choices=["important", "not_important"])
    correct_label.add_argument("--note")
    correct_label.set_defaults(func=command_correct_label)

    promote_example = subparsers.add_parser("promote-example", help="Append one reviewed item to the example dataset.")
    promote_example.add_argument("--subject", required=True, help="Substring match against subject_guess.")
    promote_example.add_argument("--sender", help="Optional substring match against sender_guess.")
    promote_example.add_argument("--label", choices=["important", "not_important"])
    promote_example.add_argument("--note")
    promote_example.set_defaults(func=command_promote_example)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
