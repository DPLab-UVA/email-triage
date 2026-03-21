#!/usr/bin/env python3
"""Stable bridge for gstack-browse using a tmux-hosted server and direct HTTP commands."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path("/Users/tianhao/Downloads/email-triage-lab")
GSTACK_ROOT = Path("/Users/tianhao/gstack")
STATE_DIR = PROJECT_ROOT / ".gstack"
STATE_FILE = STATE_DIR / "bridge-browse.json"
TMUX_SESSION = "email-triage-browse"
DEFAULT_SERVER_LOG = STATE_DIR / "bridge-browse-server.log"


class BridgeError(RuntimeError):
    """Raised for recoverable bridge failures."""


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def run_cmd(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise BridgeError(result.stderr.strip() or result.stdout.strip() or f"Command failed: {' '.join(args)}")
    return result


def tmux_session_exists() -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", TMUX_SESSION],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def load_state() -> dict[str, Any] | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def server_health(state: dict[str, Any], timeout: float = 2.0) -> dict[str, Any] | None:
    port = state.get("port")
    if not port:
        return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def ensure_tmux_server(timeout: float = 15.0) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    existing = load_state()
    if existing:
        health = server_health(existing)
        if health and health.get("status") == "healthy":
            return existing

    if tmux_session_exists():
        subprocess.run(["tmux", "kill-session", "-t", TMUX_SESSION], check=False)
        time.sleep(0.2)

    command = (
        f"cd {shell_quote(str(PROJECT_ROOT))} && "
        f"mkdir -p {shell_quote(str(STATE_DIR))} && "
        f"env BROWSE_STATE_FILE={shell_quote(str(STATE_FILE))} "
        f"{shell_quote(str(Path.home() / '.bun' / 'bin' / 'bun'))} run "
        f"{shell_quote(str(GSTACK_ROOT / 'browse' / 'src' / 'server.ts'))} "
        f">> {shell_quote(str(DEFAULT_SERVER_LOG))} 2>&1"
    )
    result = subprocess.run(
        ["tmux", "new-session", "-d", "-s", TMUX_SESSION, command],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 and "duplicate session" not in (result.stderr or "").lower():
        raise BridgeError(result.stderr.strip() or result.stdout.strip() or "tmux new-session failed")

    deadline = time.time() + timeout
    last_state: dict[str, Any] | None = None
    while time.time() < deadline:
        last_state = load_state()
        if last_state:
            health = server_health(last_state, timeout=1.0)
            if health and health.get("status") == "healthy":
                return last_state
        time.sleep(0.2)

    log_tail = ""
    if DEFAULT_SERVER_LOG.exists():
        log_tail = DEFAULT_SERVER_LOG.read_text(encoding="utf-8", errors="ignore")[-2000:]
    raise BridgeError(f"Timed out waiting for gstack browse server.\n{log_tail}".strip())


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def send_command(command: str, args: list[str], *, timeout: float = 30.0) -> str:
    state = ensure_tmux_server()
    req = urllib.request.Request(
        f"http://127.0.0.1:{state['port']}/command",
        data=json.dumps({"command": command, "args": args}).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {state['token']}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise BridgeError(f"HTTP {exc.code}: {body or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise BridgeError(str(exc.reason)) from exc


def command_ensure_server(_: argparse.Namespace) -> int:
    state = ensure_tmux_server()
    payload = {
        "ok": True,
        "tmux_session": TMUX_SESSION,
        "state_file": str(STATE_FILE),
        "server": state,
        "health": server_health(state),
    }
    print_json(payload)
    return 0


def command_status(_: argparse.Namespace) -> int:
    state = load_state()
    payload = {
        "tmux_session_exists": tmux_session_exists(),
        "state_file": str(STATE_FILE),
        "state_exists": bool(state),
        "state": state or {},
        "health": server_health(state) if state else None,
    }
    print_json(payload)
    return 0


def command_cmd(args: argparse.Namespace) -> int:
    output = send_command(args.command_name, args.args, timeout=args.timeout)
    if args.json:
        print_json({"command": args.command_name, "args": args.args, "output": output})
    else:
        sys.stdout.write(output)
        if output and not output.endswith("\n"):
            sys.stdout.write("\n")
    return 0


def command_kill(_: argparse.Namespace) -> int:
    if tmux_session_exists():
        subprocess.run(["tmux", "kill-session", "-t", TMUX_SESSION], check=False)
    print_json({"ok": True, "tmux_session": TMUX_SESSION, "killed": True})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stable bridge for gstack-browse.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ensure_server_parser = subparsers.add_parser("ensure-server", help="Start or reuse the tmux-hosted gstack browse server.")
    ensure_server_parser.set_defaults(func=command_ensure_server)

    status_parser = subparsers.add_parser("status", help="Show bridge and server status.")
    status_parser.set_defaults(func=command_status)

    cmd_parser = subparsers.add_parser("cmd", help="Send one raw command to gstack browse.")
    cmd_parser.add_argument("command_name", help="The gstack browse command name.")
    cmd_parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for the command.")
    cmd_parser.add_argument("--timeout", type=float, default=30.0)
    cmd_parser.add_argument("--json", action="store_true")
    cmd_parser.set_defaults(func=command_cmd)

    kill_parser = subparsers.add_parser("kill-server", help="Kill the tmux-hosted gstack browse server.")
    kill_parser.set_defaults(func=command_kill)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except BridgeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
