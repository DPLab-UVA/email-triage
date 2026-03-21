#!/usr/bin/env python3
"""Infer rough reply-style patterns from captured sent messages."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def first_nonempty_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def last_nonempty_line(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line:
            return line
    return ""


def body_length_bucket(text: str) -> str:
    length = len((text or "").strip())
    if length < 120:
        return "short"
    if length < 400:
        return "medium"
    return "long"


def main() -> int:
    parser = argparse.ArgumentParser(description="Infer rough reply style from sent samples.")
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    rows = load_jsonl(Path(args.input))
    openings = Counter()
    closings = Counter()
    lengths = Counter()

    for row in rows:
        body = row.get("body", "")
        if not body:
            continue
        openings[first_nonempty_line(body)] += 1
        closings[last_nonempty_line(body)] += 1
        lengths[body_length_bucket(body)] += 1

    result = {
        "sample_count": len(rows),
        "common_openings": openings.most_common(5),
        "common_closings": closings.most_common(5),
        "length_distribution": lengths,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
