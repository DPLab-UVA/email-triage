#!/usr/bin/env python3
"""Fetch recent visible Outlook Web messages and triage them."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from gstack_browse_bridge import BridgeError, send_command
from outlook_web_workflow import (
    DEFAULT_BROWSER,
    DEFAULT_COOKIE_DOMAINS,
    DEFAULT_PROFILE,
    ensure_outlook_session,
)

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
sys.path.append(str(SHARED))

from triage_engine import load_json, load_jsonl, triage_message  # noqa: E402

TIME_LINE_RE = re.compile(
    r"^(?:\d{1,2}:\d{2}\s?[AP]M|Today|Yesterday|Mon|Tue|Wed|Thu|Fri|Sat|Sun|"
    r"\d{1,2}/\d{1,2}/\d{2,4}|\w{3}\s+\d{1,2}/\d{1,2}/\d{2,4})$",
    re.I,
)
PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")


def bridge_js(expr: str, *, timeout: float = 30.0) -> str:
    return send_command("js", [expr], timeout=timeout).strip()


def bridge_json(expr: str, *, timeout: float = 30.0) -> Any:
    raw = bridge_js(expr, timeout=timeout)
    return json.loads(raw or "null")


def clean_line(value: str) -> str:
    compact = PRIVATE_USE_RE.sub("", value or "")
    compact = re.sub(r"\s+", " ", compact).strip()
    return compact


def useful_lines(text: str) -> list[str]:
    lines = [clean_line(line) for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    if len(lines) >= 2 and len(lines[0]) <= 3 and len(lines[1]) > len(lines[0]):
        lines = lines[1:]
    return lines


def parse_option(row: dict[str, Any]) -> dict[str, Any] | None:
    lines = useful_lines(row.get("raw_text", ""))
    if len(lines) < 2:
        return None

    sender = lines[0]
    subject = lines[1]
    received_at = ""
    body_preview = ""
    if len(lines) >= 3 and TIME_LINE_RE.match(lines[2]):
        received_at = lines[2]
        body_preview = " ".join(lines[3:]).strip()
    else:
        body_preview = " ".join(lines[2:]).strip()

    return {
        "source": "outlook_web_recent",
        "dom_id": row.get("dom_id", ""),
        "conversation_id": row.get("conversation_id", ""),
        "selected": bool(row.get("selected")),
        "group_header": row.get("group_header", ""),
        "pinned": bool(row.get("pinned")),
        "unread": bool(row.get("unread")),
        "mark_action": row.get("mark_action", ""),
        "aria_label": row.get("aria_label", ""),
        "from": sender,
        "subject": subject,
        "received_at": received_at,
        "body": body_preview,
        "raw_text": row.get("raw_text", ""),
    }


def current_visible_options() -> list[dict[str, Any]]:
    expr = """
JSON.stringify(
  (() => {
    const itemList = document.querySelector('[data-testid="virtuoso-item-list"]');
    const wrappers = itemList ? Array.from(itemList.querySelectorAll(':scope > div[data-index]')) : [];
    let currentHeader = '';
    const normalize = (value) => (value || '').replace(/[\\uE000-\\uF8FF]/g, ' ').replace(/\\s+/g, ' ').trim();
    const rows = [];
    for (const wrapper of wrappers) {
      const header = wrapper.querySelector('[id^="groupHeader"] .PukTV');
      if (header) {
        currentHeader = (header.innerText || header.textContent || '').trim();
      }
      const el = wrapper.querySelector('[role="option"]');
      if (!el) continue;
      const markTarget = Array.from(el.querySelectorAll('[title],[aria-label]')).find((candidate) => {
        const label = normalize(candidate.getAttribute('title') || candidate.getAttribute('aria-label') || '');
        return /^Mark as (read|unread)$/i.test(label);
      });
      const markAction = normalize(markTarget ? (markTarget.getAttribute('title') || markTarget.getAttribute('aria-label') || '') : '');
      rows.push({
        index: rows.length,
        dom_id: el.id || '',
        conversation_id: el.getAttribute('data-convid') || '',
        selected: el.getAttribute('aria-selected') === 'true',
        group_header: currentHeader,
        pinned: currentHeader === 'Pinned',
        unread: /^Mark as read$/i.test(markAction),
        mark_action: markAction,
        aria_label: normalize(el.getAttribute('aria-label') || ''),
        raw_text: el.innerText || el.textContent || ''
      });
    }
    return rows;
  })(),
  null,
  2
)
""".strip()
    return bridge_json(expr, timeout=45.0) or []


def scroll_message_list() -> dict[str, Any]:
    expr = """
(() => {
  const box =
    document.querySelector('[data-testid="virtuoso-scroller"]') ||
    document.querySelector('[role="listbox"]');
  if (!box) return JSON.stringify({ ok: false, reason: 'no-scroll-container' });
  const before = box.scrollTop;
  box.scrollTop = Math.min(box.scrollTop + Math.max(box.clientHeight - 80, 200), box.scrollHeight);
  return JSON.stringify({
    ok: true,
    before,
    after: box.scrollTop,
    clientHeight: box.clientHeight,
    scrollHeight: box.scrollHeight
  });
})()
""".strip()
    return json.loads(bridge_js(expr, timeout=20.0))


def reset_message_list_scroll() -> None:
    expr = """
(() => {
  const box =
    document.querySelector('[data-testid="virtuoso-scroller"]') ||
    document.querySelector('[role="listbox"]');
  if (box) box.scrollTop = 0;
  return true;
})()
""".strip()
    bridge_js(expr, timeout=10.0)


def fetch_recent_messages(*, screens: int, limit: int, recent_only: bool) -> list[dict[str, Any]]:
    ensure_outlook_session(DEFAULT_BROWSER, DEFAULT_PROFILE, DEFAULT_COOKIE_DOMAINS)
    collected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for _ in range(max(1, screens)):
        for row in current_visible_options():
            parsed = parse_option(row)
            if not parsed:
                continue
            if recent_only and not parsed.get("received_at"):
                continue
            key = (parsed.get("conversation_id", ""), parsed.get("subject", ""))
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


def triage_recent_messages(
    rows: list[dict[str, Any]],
    *,
    rules_path: Path | None = None,
    examples_path: Path | None = None,
    rules: dict[str, Any] | None = None,
    examples: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if rules is None:
        if rules_path is None:
            raise ValueError("rules or rules_path is required")
        rules = load_json(rules_path)
    if examples is None:
        if examples_path is None:
            raise ValueError("examples or examples_path is required")
        examples = load_jsonl(examples_path)
    digest_folder = str(rules.get("nightly_digest_folder", "Night Review"))
    records: list[dict[str, Any]] = []
    summary = {
        "total": 0,
        "useful": 0,
        "not_useful": 0,
        "important_notify": 0,
        "night_digest": 0,
        "auto_action": 0,
        "pinned_hold": 0,
        "nightly_digest_folder": digest_folder,
        "examples": {"useful": [], "not_useful": []},
    }

    for row in rows:
        triage = triage_message(row, rules, examples)
        if row.get("pinned"):
            bucket = "pinned_hold"
            useful = True
        elif triage.get("action") == "notify-and-draft":
            bucket = "important_notify"
            useful = True
        elif str(triage.get("action", "")).startswith(("queue-auto-decline", "queue-auto-approve")):
            bucket = "auto_action"
            useful = False
        else:
            bucket = "night_digest"
            useful = False

        reason = "; ".join(triage.get("reasons", [])) or triage.get("category", "")
        if row.get("pinned"):
            reason = "pinned by user; keep in inbox for later review/reply"

        record = {
            **row,
            "useful": useful,
            "bucket": bucket,
            "target_folder": digest_folder
            if (bucket == "night_digest" or (bucket == "auto_action" and str(triage.get("action", "")) != "queue-auto-approve-expense"))
            else "",
            "reason": reason,
            "triage": triage,
        }
        records.append(record)

        summary["total"] += 1
        summary["useful" if useful else "not_useful"] += 1
        summary[bucket] += 1
        example_bucket = summary["examples"]["useful" if useful else "not_useful"]
        if len(example_bucket) < 6:
            example_bucket.append(
                {
                    "from": row.get("from", ""),
                    "subject": row.get("subject", ""),
                    "received_at": row.get("received_at", ""),
                    "bucket": bucket,
                    "reason": record["reason"],
                }
            )

    return records, summary


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch recent Outlook Web messages and triage them.")
    parser.add_argument("--screens", type=int, default=4)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--include-pinned", action="store_true", help="Keep items without a visible time/date line.")
    parser.add_argument("--rules", default=str(SHARED / "default_rules.json"))
    parser.add_argument("--examples", default=str(SHARED / "example_labeled_emails.jsonl"))
    parser.add_argument("--raw-output", default=str(SHARED / "outlook_recent_messages.json"))
    parser.add_argument("--triage-output", default=str(SHARED / "outlook_recent_triage.jsonl"))
    parser.add_argument("--digest-output", default=str(SHARED / "outlook_recent_digest.jsonl"))
    parser.add_argument("--summary-output", default=str(SHARED / "outlook_recent_summary.json"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    recent_only = not args.include_pinned
    rows = fetch_recent_messages(screens=args.screens, limit=args.limit, recent_only=recent_only)
    triaged, summary = triage_recent_messages(
        rows,
        rules_path=Path(args.rules),
        examples_path=Path(args.examples),
    )

    write_json(Path(args.raw_output), rows)
    write_jsonl(Path(args.triage_output), triaged)
    write_jsonl(
        Path(args.digest_output),
        [row for row in triaged if row.get("bucket") in {"night_digest", "auto_action"}],
    )
    write_json(Path(args.summary_output), summary)

    print(
        json.dumps(
            {
                "raw_output": args.raw_output,
                "triage_output": args.triage_output,
                "digest_output": args.digest_output,
                "summary_output": args.summary_output,
                **summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BridgeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
