#!/usr/bin/env python3
"""Visible Atlas helper for social-post drafting."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

ATLAS_CLI = os.path.expanduser("~/.codex/skills/atlas/scripts/atlas_cli.py")

PLATFORM_URLS = {
    "x": "https://x.com/compose/post",
    "linkedin": "https://www.linkedin.com/feed/?shareActive=true",
    "xiaohongshu": "https://creator.xiaohongshu.com/publish/publish",
}


class AtlasSocialError(RuntimeError):
    """Raised for recoverable Atlas social workflow failures."""


@dataclass
class AtlasTab:
    title: str
    url: str
    window_id: int
    tab_index: int
    is_active: bool

    @property
    def platform(self) -> str | None:
        url = self.url.lower()
        if "x.com/" in url or "twitter.com/" in url:
            return "x"
        if "linkedin.com/" in url:
            return "linkedin"
        if "xiaohongshu.com/" in url:
            return "xiaohongshu"
        return None

    @property
    def is_compose(self) -> bool:
        url = self.url.lower()
        title = self.title.lower()
        if self.platform == "x":
            return "/compose/post" in url or "compose new post" in title
        if self.platform == "linkedin":
            return "shareactive=true" in url
        if self.platform == "xiaohongshu":
            return "/publish/publish" in url and "/login" not in url
        return False


def run_atlas(*args: str) -> str:
    cmd = ["uv", "run", "--python", "3.12", "python", ATLAS_CLI, *args]
    env = dict(os.environ)
    env.setdefault("CODEX_HOME", os.path.expanduser("~/.codex"))
    result = subprocess.run(cmd, text=True, capture_output=True, check=False, env=env)
    if result.returncode != 0:
        raise AtlasSocialError(result.stderr.strip() or result.stdout.strip() or "Atlas command failed")
    return (result.stdout or "").strip()


def atlas_tabs() -> list[AtlasTab]:
    raw = run_atlas("tabs", "--json")
    rows = json.loads(raw)
    return [AtlasTab(**row) for row in rows]


def social_tabs(platform: str | None = None) -> list[AtlasTab]:
    tabs = [tab for tab in atlas_tabs() if tab.platform]
    if platform:
        tabs = [tab for tab in tabs if tab.platform == platform]
    return tabs


def newest_social_tab(platform: str) -> AtlasTab:
    tabs = social_tabs(platform)
    if not tabs:
        raise AtlasSocialError(f"No {platform} tab found in Atlas.")
    return tabs[-1]


def newest_compose_tab(platform: str) -> AtlasTab | None:
    for tab in reversed(social_tabs(platform)):
        if tab.is_compose:
            return tab
    return None


def focus_tab(tab: AtlasTab) -> None:
    run_atlas("focus-tab", str(tab.window_id), str(tab.tab_index))


def open_compose_tab(platform: str) -> AtlasTab:
    url = PLATFORM_URLS[platform]
    run_atlas("open-tab", url)
    time.sleep(0.7)
    tab = newest_social_tab(platform)
    focus_tab(tab)
    time.sleep(0.3)
    return tab


def ensure_compose_tab(platform: str, *, fresh: bool = False) -> AtlasTab:
    tab = None if fresh else newest_compose_tab(platform)
    if tab is None:
        tab = open_compose_tab(platform)
    else:
        focus_tab(tab)
        time.sleep(0.3)
    return tab


def read_clipboard() -> str:
    result = subprocess.run(["pbpaste"], text=True, capture_output=True, check=False)
    return result.stdout


def write_clipboard(text: str) -> None:
    subprocess.run(["pbcopy"], input=text, text=True, check=True)


def osascript(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["osascript", "-e", script], text=True, capture_output=True, check=False)


def atlas_front_state() -> dict[str, str]:
    script = """
tell application "System Events"
  set frontProc to first application process whose frontmost is true
  set frontName to name of frontProc
  try
    set win1 to front window of frontProc
    set titleText to name of win1
  on error
    set titleText to ""
  end try
end tell
return frontName & "\\n" & titleText
""".strip()
    result = osascript(script)
    if result.returncode != 0:
        raise AtlasSocialError(result.stderr.strip() or "Failed to inspect frontmost app")
    lines = (result.stdout or "").splitlines()
    return {
        "app_name": lines[0].strip() if lines else "",
        "window_title": lines[1].strip() if len(lines) > 1 else "",
    }


def activate_atlas() -> dict[str, str]:
    script = """
tell application id "com.openai.atlas" to activate
delay 0.8
tell application "System Events"
  tell process "ChatGPT Atlas"
    set frontmost to true
  end tell
end tell
delay 0.2
tell application "System Events"
  set frontProc to first application process whose frontmost is true
  set frontName to name of frontProc
  try
    set win1 to front window of frontProc
    set titleText to name of win1
  on error
    set titleText to ""
  end try
end tell
return frontName & "\\n" & titleText
""".strip()
    result = osascript(script)
    if result.returncode != 0:
        raise AtlasSocialError(result.stderr.strip() or "Failed to activate Atlas")
    lines = (result.stdout or "").splitlines()
    state = {
        "app_name": lines[0].strip() if lines else "",
        "window_title": lines[1].strip() if len(lines) > 1 else "",
    }
    if state["app_name"] != "ChatGPT Atlas":
        raise AtlasSocialError(f"Atlas did not become frontmost. Front app is '{state['app_name']}'.")
    return state


def paste_and_verify(text: str) -> dict[str, Any]:
    original_clipboard = read_clipboard()
    try:
        write_clipboard(text)
        before = activate_atlas()
        script = """
tell application "System Events"
  keystroke "v" using command down
  delay 0.4
  keystroke "a" using command down
  delay 0.2
  keystroke "c" using command down
end tell
""".strip()
        result = osascript(script)
        if result.returncode != 0:
            raise AtlasSocialError(result.stderr.strip() or "Failed to paste into Atlas")
        echoed = read_clipboard()
        after = atlas_front_state()
        return {
            "ok": echoed == text or text in echoed,
            "exact_match": echoed == text,
            "contained_match": text in echoed,
            "echoed_text": echoed,
            "expected_text": text,
            "front_state_before": before,
            "front_state_after": after,
        }
    finally:
        write_clipboard(original_clipboard)


def logged_out(tab: AtlasTab) -> bool:
    url = tab.url.lower()
    title = tab.title.lower()
    if tab.platform == "xiaohongshu":
        return "/login" in url or "登录" in tab.title
    if tab.platform == "linkedin":
        return "/uas/login" in url or "sign in" in title
    if tab.platform == "x":
        return "/i/flow/login" in url or "log in" in title
    return False


def print_json(payload: Any) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_tabs(args: argparse.Namespace) -> int:
    rows = []
    for tab in social_tabs(args.platform):
        rows.append(
            {
                **tab.__dict__,
                "platform": tab.platform,
                "is_compose": tab.is_compose,
                "logged_out": logged_out(tab),
            }
        )
    return print_json(rows) if args.json else 0


def command_open_compose(args: argparse.Namespace) -> int:
    tab = ensure_compose_tab(args.platform, fresh=args.fresh)
    payload = {
        "action": "open-compose",
        "platform": args.platform,
        "tab": {**tab.__dict__, "platform": tab.platform, "is_compose": tab.is_compose, "logged_out": logged_out(tab)},
    }
    return print_json(payload) if args.json else 0


def command_focus_compose(args: argparse.Namespace) -> int:
    tab = ensure_compose_tab(args.platform, fresh=args.fresh)
    payload = {
        "action": "focus-compose",
        "platform": args.platform,
        "tab": {**tab.__dict__, "platform": tab.platform, "is_compose": tab.is_compose, "logged_out": logged_out(tab)},
    }
    return print_json(payload) if args.json else 0


def command_draft(args: argparse.Namespace) -> int:
    tab = ensure_compose_tab(args.platform, fresh=args.fresh)
    if logged_out(tab):
        raise AtlasSocialError(f"{args.platform} compose tab is not logged in inside Atlas.")
    result = paste_and_verify(args.text)
    payload = {
        "action": "draft",
        "mode": "editor_prepared",
        "platform": args.platform,
        "tab": {**tab.__dict__, "platform": tab.platform, "is_compose": tab.is_compose, "logged_out": logged_out(tab)},
        "result": result,
        "persistence_verified": False,
        "note": "This verifies text in the live compose editor only. It does not verify that the platform saved a server-side draft entry.",
    }
    return print_json(payload) if args.json else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Visible Atlas helper for social-post drafting.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tabs_parser = subparsers.add_parser("tabs", help="List Atlas social tabs.")
    tabs_parser.add_argument("--platform", choices=sorted(PLATFORM_URLS))
    tabs_parser.add_argument("--json", action="store_true")
    tabs_parser.set_defaults(func=command_tabs)

    open_parser = subparsers.add_parser("open-compose", help="Open a social compose tab in Atlas.")
    open_parser.add_argument("platform", choices=sorted(PLATFORM_URLS))
    open_parser.add_argument("--fresh", action="store_true")
    open_parser.add_argument("--json", action="store_true")
    open_parser.set_defaults(func=command_open_compose)

    focus_parser = subparsers.add_parser("focus-compose", help="Focus the newest social compose tab in Atlas.")
    focus_parser.add_argument("platform", choices=sorted(PLATFORM_URLS))
    focus_parser.add_argument("--fresh", action="store_true")
    focus_parser.add_argument("--json", action="store_true")
    focus_parser.set_defaults(func=command_focus_compose)

    draft_parser = subparsers.add_parser("draft", help="Write a draft into an Atlas social compose tab.")
    draft_parser.add_argument("platform", choices=sorted(PLATFORM_URLS))
    draft_parser.add_argument("--text", required=True)
    draft_parser.add_argument("--fresh", action="store_true")
    draft_parser.add_argument("--json", action="store_true")
    draft_parser.set_defaults(func=command_draft)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except AtlasSocialError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
