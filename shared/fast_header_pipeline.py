#!/usr/bin/env python3
"""Fast header-first review queue builder."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from triage_engine import load_json, load_jsonl, triage_message

ROOT = Path("/Users/tianhao/Downloads/email-triage-lab")
SHARED = ROOT / "shared"


def load_mail_snapshot(path: Path, source: str) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for item in payload.get("messages", []):
        rows.append(
            {
                "source": source,
                "from": item.get("sender", ""),
                "subject": item.get("subject", ""),
                "body": "",
                "message_id": item.get("message_id", ""),
                "id": item.get("id", ""),
            }
        )
    return rows


def load_web_visible_rows() -> list[dict]:
    start_pat = re.compile(r"[\ue000-\uf8ff]{1,4}[A-Z]{1,3}\ue73e")
    noise_pat = re.compile(
        r"(quick steps|report message|navigation pane|create a new email message|move this message to your archive folder|mark this message as read or unread)",
        re.I,
    )
    rows = []
    seen = set()
    for path in sorted(ROOT.glob("outlook-capture-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for snippet in payload.get("view", {}).get("snippets", []) or []:
            if not isinstance(snippet, str) or len(snippet) < 1000:
                continue
            starts = [match.start() for match in start_pat.finditer(snippet)]
            for index, start in enumerate(starts):
                end = starts[index + 1] if index + 1 < len(starts) else len(snippet)
                segment = snippet[start:end].strip()
                if len(segment) < 60 or noise_pat.search(segment):
                    continue
                key = re.sub(r"^[\ue000-\uf8ff]+", "", segment)
                key = re.sub(r"\s+", " ", key)
                key = re.sub(
                    r"\b(?:\d{1,2}:\d{2}\s?[AP]M|Today|Yesterday|Mon|Tue|Wed|Thu|Fri|Sat|Sun|\d{1,2}/\d{1,2}/\d{4})\b.*$",
                    "",
                    key,
                )
                key = key[:280]
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "source": "outlook_web_visible_list",
                        "from": "",
                        "subject": key,
                        "body": "",
                        "message_id": "",
                        "id": "",
                    }
                )
    return rows


def dedupe_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    output = []
    for row in rows:
        key = (row.get("from", "").strip().lower(), row.get("subject", "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def build_summary(records: list[dict]) -> dict:
    summary = {
        "total": len(records),
        "important": 0,
        "not_important": 0,
        "by_source": {},
        "by_action": {},
        "examples": {"important": [], "not_important": []},
    }
    for record in records:
        label = record["tentative_label"]
        if label == "important":
            summary["important"] += 1
        else:
            summary["not_important"] += 1
        source = record["source"]
        summary["by_source"][source] = summary["by_source"].get(source, 0) + 1
        action = record.get("triage", {}).get("action", "")
        summary["by_action"][action] = summary["by_action"].get(action, 0) + 1
        bucket = summary["examples"][label]
        if len(bucket) < 8:
            bucket.append(
                {
                    "from": record["from"],
                    "subject": record["subject"],
                    "reason": record["reason"],
                }
            )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a fast header-first review queue.")
    parser.add_argument("--rules", default=str(SHARED / "default_rules.json"))
    parser.add_argument("--examples", default=str(SHARED / "example_labeled_emails.jsonl"))
    parser.add_argument("--exchange", default=str(SHARED / "exchange_inbox_top20.json"))
    parser.add_argument("--google", default=str(SHARED / "google_inbox_top20.json"))
    parser.add_argument("--output", default=str(SHARED / "fast_review_queue.jsonl"))
    parser.add_argument("--summary-output", default=str(SHARED / "fast_rule_summary.json"))
    parser.add_argument("--digest-output", default=str(SHARED / "night_digest_queue.jsonl"))
    parser.add_argument("--auto-action-output", default=str(SHARED / "auto_action_queue.jsonl"))
    args = parser.parse_args()

    rules = load_json(Path(args.rules))
    examples = load_jsonl(Path(args.examples))
    rows = []
    rows.extend(load_mail_snapshot(Path(args.exchange), "mail_exchange_top20"))
    rows.extend(load_mail_snapshot(Path(args.google), "mail_google_top20"))
    rows.extend(load_web_visible_rows())
    rows = dedupe_rows(rows)

    output_records = []
    digest_records = []
    auto_action_records = []
    for row in rows:
        triage = triage_message(row, rules, examples)
        record = {
            "source": row["source"],
            "from": row["from"],
            "subject": row["subject"],
            "tentative_label": "important" if triage["important"] else "not_important",
            "reason": "; ".join(triage["reasons"]) or triage["category"],
            "triage": triage,
        }
        output_records.append(record)
        if triage.get("action") == "digest-later":
            digest_records.append(record)
        if triage.get("action") == "queue-auto-decline-review-invite":
            auto_action_records.append(record)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in output_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    digest_path = Path(args.digest_output)
    with digest_path.open("w", encoding="utf-8") as handle:
        for record in digest_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    auto_action_path = Path(args.auto_action_output)
    with auto_action_path.open("w", encoding="utf-8") as handle:
        for record in auto_action_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    summary = build_summary(output_records)
    summary["nightly_digest_hour_local"] = rules.get("nightly_digest_hour_local", 21)
    summary["digest_count"] = len(digest_records)
    summary["auto_action_count"] = len(auto_action_records)
    summary_path = Path(args.summary_output)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "queue": str(output_path),
                "summary": str(summary_path),
                "digest_queue": str(digest_path),
                "auto_action_queue": str(auto_action_path),
                **summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
