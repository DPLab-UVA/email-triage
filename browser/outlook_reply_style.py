#!/usr/bin/env python3
"""Infer a lightweight reply style profile from Outlook Sent Items."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from statistics import median

from outlook_night_review import fetch_folder_messages
from outlook_recent_triage import SHARED, clean_line

DEFAULT_SAMPLES = SHARED / "outlook_reply_style_samples.json"
DEFAULT_PROFILE = SHARED / "outlook_reply_style_profile.json"

TIME_PREFIX_RE = re.compile(
    r"^(?:Today|Yesterday|Mon|Tue|Wed|Thu|Fri|Sat|Sun|\d{1,2}/\d{1,2}/\d{2,4})?\s*\d{1,2}:\d{2}\s?[AP]M\s+",
    re.I,
)


def normalize_preview(text: str) -> str:
    compact = clean_line(text or "")
    compact = TIME_PREFIX_RE.sub("", compact).strip()
    return compact


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


def infer_profile(samples: list[dict[str, str]]) -> dict[str, object]:
    cleaned = [normalize_preview(sample.get("body", "")) for sample in samples]
    cleaned = [value for value in cleaned if value]
    word_counts = [len(value.split()) for value in cleaned]
    greeting_count = sum(1 for value in cleaned if re.match(r"^(hi|hello|dear)\b", value, re.I))
    signoffs = Counter(signoff for signoff in (detect_signoff(value) for value in cleaned) if signoff)
    openers = Counter(opener for opener in (detect_opener(value) for value in cleaned) if opener)

    preferred_signoff = "Best,\nTianhao"
    if signoffs:
        preferred_signoff = signoffs.most_common(1)[0][0]

    return {
        "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(),
        "source_folder": "Sent Items",
        "sample_count": len(cleaned),
        "median_word_count": median(word_counts) if word_counts else 0,
        "greeting_ratio": round(greeting_count / len(cleaned), 2) if cleaned else 0.0,
        "signoff_counts": dict(signoffs.most_common(5)),
        "common_openers": [value for value, _ in openers.most_common(8)],
        "recommended_signoff": preferred_signoff,
        "use_greeting_default": greeting_count >= max(3, len(cleaned) // 2) if cleaned else False,
        "tone_notes": [
            "Keep replies concise and direct.",
            "Prefer concrete action sentences over generic acknowledgements.",
            "Avoid AI-style filler like 'I reviewed it and will follow up shortly.'",
            "Do not add a 'Context:' line in replies.",
        ],
        "avoid_phrases": [
            "Thanks for the message.",
            "I reviewed it and will follow up shortly.",
            "Context:",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Infer an Outlook reply style profile from Sent Items.")
    parser.add_argument("--screens", type=int, default=12)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--samples-output", default=str(DEFAULT_SAMPLES))
    parser.add_argument("--profile-output", default=str(DEFAULT_PROFILE))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows = fetch_folder_messages("Sent Items", screens=args.screens, limit=args.limit)
    samples = [
        {
            "from": row.get("from", ""),
            "subject": row.get("subject", ""),
            "body": normalize_preview(str(row.get("body", ""))),
            "received_at": row.get("received_at", ""),
        }
        for row in rows
        if normalize_preview(str(row.get("body", "")))
    ]
    profile = infer_profile(samples)

    samples_path = Path(args.samples_output)
    profile_path = Path(args.profile_output)
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    samples_path.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "sample_count": len(samples),
                "samples_output": str(samples_path),
                "profile_output": str(profile_path),
                "profile": profile,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
