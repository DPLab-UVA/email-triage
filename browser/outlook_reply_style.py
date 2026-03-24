#!/usr/bin/env python3
"""Infer a lightweight reply style profile from Outlook Sent Items."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import median

from outlook_night_review import fetch_folder_messages
from outlook_recent_triage import SHARED, clean_line
sys.path.append(str(SHARED))
from sqlite_store import load_event_rows, save_state_snapshot

DEFAULT_SAMPLES = "outlook_reply_style_samples"
DEFAULT_PROFILE = "outlook_reply_style_profile"
DEFAULT_FEEDBACK = "outlook_draft_feedback"

TIME_PREFIX_RE = re.compile(
    r"^(?:Today|Yesterday|Mon|Tue|Wed|Thu|Fri|Sat|Sun|\d{1,2}/\d{1,2}/\d{2,4})?\s*\d{1,2}:\d{2}\s?[AP]M\s+",
    re.I,
)


def normalize_preview(text: str) -> str:
    compact = clean_line(text or "")
    compact = TIME_PREFIX_RE.sub("", compact).strip()
    return compact


def normalize_reply_body(text: str) -> str:
    value = (text or "").replace("\r\n", "\n").replace("\ufeff", "")
    lines = [clean_line(line) for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def detect_signoff(text: str) -> str:
    lower = text.lower().strip()
    if lower.endswith("best, tianhao"):
        return "Best,\nTianhao"
    if lower.endswith("best, tianhao."):
        return "Best,\nTianhao"
    if lower.endswith("tianhao"):
        return "Tianhao"
    return ""


def detect_opener(text: str) -> str:
    compact = text.strip()
    if not compact:
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s+", compact, maxsplit=1)[0]
    return first_sentence[:80]


def detect_follow_up(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    if re.match(r"^(hi|hello|dear)\b", lines[0], re.I) and len(lines) > 1:
        lines = lines[1:]
    if lines and lines[-1].lower() == "tianhao":
        lines = lines[:-1]
    if lines and lines[-1].lower() == "best,":
        lines = lines[:-1]
    if len(lines) >= 2:
        return lines[1][:120]
    return ""


def load_feedback_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in load_event_rows(path):
        rows.append(row)
    return rows


def feedback_positive_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    keep = {"sent_as_is", "sent_modified", "approved", "edited"}
    result: list[dict[str, str]] = []
    for row in rows:
        if str(row.get("status", "")).strip() not in keep:
            continue
        final_body = normalize_reply_body(str(row.get("final_compose_body", "")))
        if not final_body:
            continue
        result.append({**row, "final_compose_body": final_body})
    return result


def feedback_negative_phrases(rows: list[dict[str, str]]) -> list[str]:
    phrases: Counter[str] = Counter()
    for row in rows:
        status = str(row.get("status", "")).strip()
        suggested = normalize_reply_body(str(row.get("draft_reply", "")))
        final_body = normalize_reply_body(str(row.get("final_compose_body", "")))
        if status == "rejected" and suggested:
            phrases[detect_opener(suggested)] += 1
            follow = detect_follow_up(suggested)
            if follow:
                phrases[follow] += 1
        elif status == "sent_modified" and suggested and final_body and suggested != final_body:
            suggested_opener = detect_opener(suggested)
            final_opener = detect_opener(final_body)
            if suggested_opener and suggested_opener != final_opener:
                phrases[suggested_opener] += 1
            suggested_follow = detect_follow_up(suggested)
            final_follow = detect_follow_up(final_body)
            if suggested_follow and suggested_follow != final_follow:
                phrases[suggested_follow] += 1
    return [value for value, _ in phrases.most_common(8) if value]


def infer_profile(samples: list[dict[str, str]], feedback_rows: list[dict[str, str]]) -> dict[str, object]:
    positive_feedback = feedback_positive_rows(feedback_rows)
    combined = [normalize_preview(sample.get("body", "")) for sample in samples]
    combined.extend(row.get("final_compose_body", "") for row in positive_feedback)
    cleaned = [value for value in combined if value]
    word_counts = [len(value.split()) for value in cleaned]
    greeting_count = sum(1 for value in cleaned if re.match(r"^(hi|hello|dear)\b", value, re.I))
    signoffs = Counter(signoff for signoff in (detect_signoff(value) for value in cleaned) if signoff)
    openers = Counter(opener for opener in (detect_opener(value) for value in cleaned) if opener)
    follow_ups = Counter(follow for follow in (detect_follow_up(value) for value in cleaned) if follow)
    category_openers: dict[str, Counter[str]] = {}
    category_follow_ups: dict[str, Counter[str]] = {}
    for row in positive_feedback:
        category = str(row.get("category", "")).strip().lower()
        if not category:
            continue
        opener = detect_opener(str(row.get("final_compose_body", "")))
        follow = detect_follow_up(str(row.get("final_compose_body", "")))
        if opener:
            category_openers.setdefault(category, Counter())[opener] += 1
        if follow:
            category_follow_ups.setdefault(category, Counter())[follow] += 1

    preferred_signoff = "Best,\nTianhao"
    if signoffs:
        preferred_signoff = signoffs.most_common(1)[0][0]

    avoid_phrases = [
        "Thanks for the message.",
        "I reviewed it and will follow up shortly.",
        "Context:",
    ]
    for phrase in feedback_negative_phrases(feedback_rows):
        if phrase and phrase not in avoid_phrases:
            avoid_phrases.append(phrase)

    return {
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(),
        "source_folder": "Sent Items",
        "sample_count": len(cleaned),
        "sent_sample_count": len([normalize_preview(sample.get("body", "")) for sample in samples if normalize_preview(sample.get("body", ""))]),
        "feedback_positive_count": len(positive_feedback),
        "feedback_total_count": len(feedback_rows),
        "median_word_count": median(word_counts) if word_counts else 0,
        "greeting_ratio": round(greeting_count / len(cleaned), 2) if cleaned else 0.0,
        "signoff_counts": dict(signoffs.most_common(5)),
        "common_openers": [value for value, _ in openers.most_common(8)],
        "common_follow_ups": [value for value, _ in follow_ups.most_common(8)],
        "category_openers": {
            key: counter.most_common(1)[0][0]
            for key, counter in category_openers.items()
            if counter
        },
        "category_follow_ups": {
            key: counter.most_common(1)[0][0]
            for key, counter in category_follow_ups.items()
            if counter
        },
        "recommended_signoff": preferred_signoff,
        "use_greeting_default": greeting_count >= max(3, len(cleaned) // 2) if cleaned else False,
        "tone_notes": [
            "Keep replies concise and direct.",
            "Prefer concrete action sentences over generic acknowledgements.",
            "Avoid AI-style filler like 'I reviewed it and will follow up shortly.'",
            "Do not add a 'Context:' line in replies.",
        ],
        "avoid_phrases": avoid_phrases,
    }


def sent_samples(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "from": row.get("from", ""),
            "subject": row.get("subject", ""),
            "body": normalize_preview(str(row.get("body", ""))),
            "received_at": row.get("received_at", ""),
        }
        for row in rows
        if normalize_preview(str(row.get("body", "")))
    ]


def refresh_style_profile(
    *,
    screens: int,
    limit: int,
    feedback_path: Path,
    samples_output: Path,
    profile_output: Path,
) -> dict[str, object]:
    rows = fetch_folder_messages("Sent Items", screens=screens, limit=limit)
    samples = sent_samples(rows)
    feedback_rows = load_feedback_rows(feedback_path)
    profile = infer_profile(samples, feedback_rows)

    save_state_snapshot(samples_output, {"updated_at": profile["generated_at"], "samples": samples})
    save_state_snapshot(profile_output, profile)

    return {
        "sample_count": len(samples),
        "feedback_count": len(feedback_rows),
        "samples_output": str(samples_output),
        "profile_output": str(profile_output),
        "profile": profile,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Infer an Outlook reply style profile from Sent Items.")
    parser.add_argument("--screens", type=int, default=12)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--samples-output", default=str(DEFAULT_SAMPLES))
    parser.add_argument("--profile-output", default=str(DEFAULT_PROFILE))
    parser.add_argument("--feedback", default=str(DEFAULT_FEEDBACK))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = refresh_style_profile(
        screens=args.screens,
        limit=args.limit,
        feedback_path=Path(args.feedback),
        samples_output=Path(args.samples_output),
        profile_output=Path(args.profile_output),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
