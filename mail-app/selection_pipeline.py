#!/usr/bin/env python3
"""Capture selected Mail.app messages and prelabel them."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
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


def load_triage_engine() -> Any:
    module_path = SHARED_DIR / "triage_engine.py"
    spec = importlib.util.spec_from_file_location("triage_engine", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load triage engine from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_mail_cli(*args: str) -> Any:
    process = subprocess.run(
        ["python3", str(MAIL_APP_CLI), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip() or "Mail CLI failed.")
    output = process.stdout.strip()
    return json.loads(output) if output else {}


def command_capture(args: argparse.Namespace) -> int:
    cli_args = ["selected", "--limit", str(args.limit), "--json"]
    if args.include_body:
        cli_args.append("--include-body")
    payload = run_mail_cli(*cli_args)
    rows = payload.get("messages", [])
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Captured {len(rows)} selected messages to {output_path}")
    return 0


def command_prelabel(args: argparse.Namespace) -> int:
    engine = load_triage_engine()
    rules = engine.load_json(Path(args.rules))
    examples = engine.load_jsonl(Path(args.examples))
    input_rows = engine.load_jsonl(Path(args.input))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in input_rows:
            result = engine.triage_message(row, rules, examples)
            result["source_message"] = row
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
    print(f"Prelabeled {len(input_rows)} messages to {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture selected Mail.app messages and prelabel them.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture", help="Capture currently selected messages in Mail.app.")
    capture_parser.add_argument("--output", required=True)
    capture_parser.add_argument("--limit", type=int, default=20)
    capture_parser.add_argument(
        "--include-body",
        action="store_true",
        help="Also capture message body text. Slower on large remote mailboxes.",
    )
    capture_parser.set_defaults(func=command_capture)

    prelabel_parser = subparsers.add_parser("prelabel", help="Prelabel captured messages with the triage engine.")
    prelabel_parser.add_argument("--input", required=True)
    prelabel_parser.add_argument("--output", required=True)
    prelabel_parser.add_argument("--rules", default=str(SHARED_DIR / "default_rules.json"))
    prelabel_parser.add_argument("--examples", default=str(SHARED_DIR / "example_labeled_emails.jsonl"))
    prelabel_parser.set_defaults(func=command_prelabel)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
