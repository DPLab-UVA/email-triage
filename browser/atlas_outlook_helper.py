#!/usr/bin/env python3
"""Small Atlas helper focused on Outlook tabs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

ATLAS_CLI = os.path.expanduser("~/.codex/skills/atlas/scripts/atlas_cli.py")
OUTLOOK_PREFIXES = (
    "https://outlook.office.com/",
    "https://outlook.office365.com/",
    "https://outlook.live.com/",
)


class AtlasHelperError(RuntimeError):
    """Raised for recoverable Atlas helper failures."""


@dataclass
class AtlasTab:
    title: str
    url: str
    window_id: int
    tab_index: int
    is_active: bool

    @property
    def is_outlook(self) -> bool:
        return self.url.startswith(OUTLOOK_PREFIXES)


def run_atlas(*args: str) -> str:
    cmd = ["uv", "run", "--python", "3.12", "python", ATLAS_CLI, *args]
    env = dict(os.environ)
    env.setdefault("CODEX_HOME", os.path.expanduser("~/.codex"))
    result = subprocess.run(cmd, text=True, capture_output=True, check=False, env=env)
    if result.returncode != 0:
        raise AtlasHelperError(result.stderr.strip() or result.stdout.strip() or "Atlas command failed")
    return (result.stdout or "").strip()


def atlas_tabs() -> list[AtlasTab]:
    raw = run_atlas("tabs", "--json")
    rows = json.loads(raw)
    return [AtlasTab(**row) for row in rows]


def outlook_tabs() -> list[AtlasTab]:
    return [tab for tab in atlas_tabs() if tab.is_outlook]


def newest_outlook_tab() -> AtlasTab:
    tabs = outlook_tabs()
    if not tabs:
        raise AtlasHelperError("No Outlook tab found in Atlas.")
    return tabs[-1]


def print_json(payload: Any) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_tabs(args: argparse.Namespace) -> int:
    tabs = [tab.__dict__ | {"is_outlook": tab.is_outlook} for tab in atlas_tabs()]
    if args.json:
        return print_json(tabs)
    for tab in tabs:
        marker = "*" if tab["is_outlook"] else "-"
        print(f"{marker} window={tab['window_id']} tab={tab['tab_index']} title={tab['title']} url={tab['url']}")
    return 0


def command_focus(args: argparse.Namespace) -> int:
    tab = newest_outlook_tab()
    run_atlas("focus-tab", str(tab.window_id), str(tab.tab_index))
    payload = {
        "action": "focus",
        "window_id": tab.window_id,
        "tab_index": tab.tab_index,
        "title": tab.title,
        "url": tab.url,
    }
    return print_json(payload) if args.json else 0


def command_reload(args: argparse.Namespace) -> int:
    tab = newest_outlook_tab()
    run_atlas("reload-tab", str(tab.window_id), str(tab.tab_index))
    payload = {
        "action": "reload",
        "window_id": tab.window_id,
        "tab_index": tab.tab_index,
        "title": tab.title,
        "url": tab.url,
    }
    return print_json(payload) if args.json else 0


def command_open(args: argparse.Namespace) -> int:
    run_atlas("open-tab", args.url)
    payload = {"action": "open", "url": args.url}
    return print_json(payload) if args.json else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Atlas helper focused on Outlook tabs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tabs_parser = subparsers.add_parser("tabs", help="List Atlas tabs with Outlook flag.")
    tabs_parser.add_argument("--json", action="store_true")
    tabs_parser.set_defaults(func=command_tabs)

    focus_parser = subparsers.add_parser("focus-outlook", help="Focus the newest Outlook tab in Atlas.")
    focus_parser.add_argument("--json", action="store_true")
    focus_parser.set_defaults(func=command_focus)

    reload_parser = subparsers.add_parser("reload-outlook", help="Reload the newest Outlook tab in Atlas.")
    reload_parser.add_argument("--json", action="store_true")
    reload_parser.set_defaults(func=command_reload)

    open_parser = subparsers.add_parser("open-outlook", help="Open a new Outlook tab in Atlas.")
    open_parser.add_argument(
        "--url",
        default="https://outlook.office.com/mail/",
        help="Outlook URL to open.",
    )
    open_parser.add_argument("--json", action="store_true")
    open_parser.set_defaults(func=command_open)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except AtlasHelperError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
