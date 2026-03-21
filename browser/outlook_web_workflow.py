#!/usr/bin/env python3
"""High-level Outlook Web workflow on top of the stable gstack bridge."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from gstack_browse_bridge import BridgeError, ensure_tmux_server, send_command

DEFAULT_BROWSER = "Chrome"
DEFAULT_PROFILE = "Profile 1"
DEFAULT_OUTLOOK_URL = "https://outlook.office.com/mail/"
DEFAULT_COOKIE_DOMAINS = [
    "outlook.office.com",
    ".login.microsoftonline.com",
    "login.microsoftonline.com",
    ".microsoftonline.com",
    ".office.com",
    ".microsoft.com",
]
DEFAULT_CAPTURE_DIR = Path("/Users/tianhao/Downloads/email-triage-lab/shared/outlook-browser-captures")


def bridge_cmd(command: str, *args: str, timeout: float = 30.0) -> str:
    return send_command(command, list(args), timeout=timeout).rstrip()


def is_logged_in(url: str, page_text: str) -> bool:
    lower_url = url.lower()
    if "login.microsoftonline.com" in lower_url:
        return False
    lowered = page_text.lower()
    if lowered.startswith("sign in\n") or lowered.startswith("sign in\r\n"):
        return False
    return "outlook" in lowered or "inbox" in lowered


def read_page_state(*, attempts: int = 6, delay_seconds: float = 1.0) -> tuple[str, str, str]:
    last_url = ""
    last_tabs = ""
    last_text = ""
    for attempt in range(attempts):
        last_url = bridge_cmd("url")
        last_tabs = bridge_cmd("tabs")
        last_text = bridge_cmd("text", timeout=45.0)
        if is_logged_in(last_url, last_text):
            return last_url, last_tabs, last_text
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    return last_url, last_tabs, last_text


def import_profile_cookies(browser: str, profile: str, domains: list[str]) -> list[str]:
    results = []
    for domain in domains:
        results.append(
            bridge_cmd(
                "cookie-import-browser",
                browser,
                "--domain",
                domain,
                "--profile",
                profile,
                timeout=45.0,
            )
        )
    return results


def ensure_outlook_session(browser: str, profile: str, domains: list[str]) -> dict[str, Any]:
    server = ensure_tmux_server()
    current_url = ""
    try:
        current_url = bridge_cmd("url")
    except Exception:
        current_url = ""
    if "outlook.office.com" in current_url and "login.microsoftonline.com" not in current_url:
        tabs = bridge_cmd("tabs")
        page_text = bridge_cmd("text", timeout=45.0)
        if is_logged_in(current_url, page_text):
            return {
                "server": server,
                "browser": browser,
                "profile": profile,
                "cookie_domains": domains,
                "import_results": [],
                "url": current_url,
                "tabs": tabs,
                "logged_in": True,
                "page_excerpt": page_text[:2000],
            }
    imports = import_profile_cookies(browser, profile, domains)
    bridge_cmd("goto", DEFAULT_OUTLOOK_URL, timeout=45.0)
    bridge_cmd("wait", "--load", timeout=45.0)
    url, tabs, page_text = read_page_state()
    return {
        "server": server,
        "browser": browser,
        "profile": profile,
        "cookie_domains": domains,
        "import_results": imports,
        "url": url,
        "tabs": tabs,
        "logged_in": is_logged_in(url, page_text),
        "page_excerpt": page_text[:2000],
    }


def capture_current_view(output_dir: Path, text_limit: int) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "captured_at": datetime.now().astimezone().isoformat(),
        "url": bridge_cmd("url"),
        "tabs": bridge_cmd("tabs"),
        "text": bridge_cmd("text", timeout=45.0)[:text_limit],
        "snapshot": bridge_cmd("snapshot", "-i", timeout=45.0),
    }
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_path = output_dir / f"outlook-view-{timestamp}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["output_path"] = str(output_path)
    return payload


def print_payload(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            print(f"{key}:")
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            print(f"{key}: {value}")
    return 0


def command_bootstrap(args: argparse.Namespace) -> int:
    payload = ensure_outlook_session(args.browser, args.profile, args.domain or DEFAULT_COOKIE_DOMAINS)
    return print_payload(payload, args.json)


def command_status(args: argparse.Namespace) -> int:
    ensure_tmux_server()
    url, tabs, page_text = read_page_state()
    payload = {
        "url": url,
        "tabs": tabs,
        "logged_in": is_logged_in(url, page_text),
        "page_excerpt": page_text[:2000],
    }
    return print_payload(payload, args.json)


def command_current_view(args: argparse.Namespace) -> int:
    ensure_tmux_server()
    payload = {
        "url": bridge_cmd("url"),
        "tabs": bridge_cmd("tabs"),
        "text": bridge_cmd("text", timeout=45.0)[: args.text_limit],
        "snapshot": bridge_cmd("snapshot", "-i", timeout=45.0),
    }
    return print_payload(payload, args.json)


def command_capture_current(args: argparse.Namespace) -> int:
    ensure_tmux_server()
    payload = capture_current_view(Path(args.output_dir), args.text_limit)
    return print_payload(payload, args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Outlook Web workflow on top of the gstack bridge.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser("bootstrap", help="Import browser cookies and land on Outlook Web.")
    bootstrap_parser.add_argument("--browser", default=DEFAULT_BROWSER)
    bootstrap_parser.add_argument("--profile", default=DEFAULT_PROFILE)
    bootstrap_parser.add_argument("--domain", action="append", help="Cookie domain to import. May be repeated.")
    bootstrap_parser.add_argument("--json", action="store_true")
    bootstrap_parser.set_defaults(func=command_bootstrap)

    status_parser = subparsers.add_parser("status", help="Show current Outlook browser state.")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=command_status)

    current_parser = subparsers.add_parser("current-view", help="Dump the current Outlook page text and interactive snapshot.")
    current_parser.add_argument("--text-limit", type=int, default=12000)
    current_parser.add_argument("--json", action="store_true")
    current_parser.set_defaults(func=command_current_view)

    capture_parser = subparsers.add_parser("capture-current", help="Save the current Outlook page capture to disk.")
    capture_parser.add_argument("--output-dir", default=str(DEFAULT_CAPTURE_DIR))
    capture_parser.add_argument("--text-limit", type=int, default=12000)
    capture_parser.add_argument("--json", action="store_true")
    capture_parser.set_defaults(func=command_capture_current)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except BridgeError as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
