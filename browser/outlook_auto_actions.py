#!/usr/bin/env python3
"""Auto-actions for selected Outlook messages that should be handled, not replied to."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from typing import Any

from gstack_browse_bridge import send_command


def bridge_js(expr: str, *, timeout: float = 30.0) -> str:
    return send_command("js", [expr], timeout=timeout).strip()


def bridge_json(expr: str, *, timeout: float = 30.0) -> Any:
    raw = bridge_js(expr, timeout=timeout)
    return json.loads(raw or "null")


def selected_workday_notification_link() -> dict[str, Any]:
    expr = """
JSON.stringify(
  (() => {
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const links = Array.from(document.querySelectorAll('a')).map((el) => ({
      text: normalize(el.innerText || el.textContent || ''),
      href: el.href || '',
    }));
    const match = links.find((item) =>
      /myworkday\\.com/i.test(item.href) &&
      /notification details/i.test(item.text)
    );
    if (!match) {
      return { ok: false, reason: 'workday-notification-link-not-found', links };
    }
    return {
      ok: true,
      text: match.text,
      href: match.href,
    };
  })(),
  null,
  2
)
""".strip()
    return bridge_json(expr, timeout=20.0) or {}


def run_osascript(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["osascript", "-", *args],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )


def open_chrome_tab(url: str) -> dict[str, Any]:
    script = """
on run argv
  set theUrl to item 1 of argv
  tell application "Google Chrome"
    activate
    if (count of windows) = 0 then
      make new window
    end if
    tell front window
      set tabCount to count of tabs
      make new tab at end of tabs with properties {URL:theUrl}
      set active tab index to (tabCount + 1)
    end tell
    delay 5
    set currentTitle to title of active tab of front window
    set currentUrl to URL of active tab of front window
    return currentTitle & linefeed & currentUrl
  end tell
end run
""".strip()
    result = run_osascript(script, url)
    if result.returncode != 0:
        return {
            "ok": False,
            "status": "chrome-open-failed",
            "error": (result.stderr or result.stdout).strip(),
            "url": url,
        }
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    title = lines[0].strip() if lines else ""
    current_url = lines[1].strip() if len(lines) > 1 else ""
    return {
        "ok": True,
        "status": "opened",
        "title": title,
        "url": current_url or url,
    }


def chrome_execute_js(script_body: str) -> dict[str, Any]:
    script = """
on run argv
  set jsCode to item 1 of argv
  tell application "Google Chrome"
    if (count of windows) = 0 then error "NO_WINDOWS"
    tell active tab of front window
      return execute javascript jsCode
    end tell
  end tell
end run
""".strip()
    result = run_osascript(script, script_body)
    if result.returncode != 0:
        error_text = (result.stderr or result.stdout).strip()
        status = "chrome-js-failed"
        if "Allow JavaScript from Apple Events" in error_text:
            status = "chrome-js-from-apple-events-disabled"
        return {
            "ok": False,
            "status": status,
            "error": error_text,
        }
    return {
        "ok": True,
        "output": result.stdout.strip(),
    }


def chrome_inspect_active_tab() -> dict[str, Any]:
    result = chrome_execute_js(
        """
JSON.stringify({
  title: document.title || '',
  url: location.href || '',
  text: document.body ? (document.body.innerText || '').slice(0, 6000) : ''
})
""".strip()
    )
    if not result.get("ok"):
        return result
    try:
        payload = json.loads(result.get("output", "") or "{}")
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "status": "chrome-js-invalid-json",
            "error": str(exc),
            "raw": result.get("output", ""),
        }
    return {
        "ok": True,
        "status": "inspected",
        **payload,
    }


def chrome_click_button(labels: list[str]) -> dict[str, Any]:
    script = f"""
(() => {{
  const wanted = new Set({json.dumps([label.lower() for label in labels])});
  const normalize = (value) => (value || '')
    .replace(/[\\uE000-\\uF8FF]/g, ' ')
    .replace(/\\s+/g, ' ')
    .trim()
    .toLowerCase();
  const click = (el) => {{
    el.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
    el.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
    el.click();
  }};
  const candidates = Array.from(document.querySelectorAll('button, [role="button"], input[type="button"], input[type="submit"], a'));
  const target = candidates.find((el) => {{
    const label = normalize(el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.textContent || el.value || '');
    return wanted.has(label) && !el.disabled;
  }});
  if (!target) {{
    return JSON.stringify({{ ok: false, reason: 'button-not-found', labels: Array.from(wanted) }});
  }}
  click(target);
  return JSON.stringify({{ ok: true, label: normalize(target.getAttribute('aria-label') || target.getAttribute('title') || target.innerText || target.textContent || target.value || '') }});
}})()
""".strip()
    result = chrome_execute_js(script)
    if not result.get("ok"):
        return result
    try:
        payload = json.loads(result.get("output", "") or "{}")
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "status": "chrome-click-invalid-json",
            "error": str(exc),
            "raw": result.get("output", ""),
        }
    return payload


def attempt_expense_approval_from_selected() -> dict[str, Any]:
    link = selected_workday_notification_link()
    if not link.get("ok"):
        return {
            "ok": False,
            "status": "no-workday-link",
            "link": link,
            "opened": False,
        }

    opened = open_chrome_tab(str(link.get("href", "")))
    if not opened.get("ok"):
        return {
            "ok": False,
            "status": "chrome-open-failed",
            "link": link,
            "chrome": opened,
            "opened": False,
        }

    inspected = chrome_inspect_active_tab()
    payload: dict[str, Any] = {
        "ok": False,
        "opened": True,
        "status": "opened-in-chrome",
        "link": link,
        "chrome": opened,
        "inspect": inspected,
    }
    if not inspected.get("ok"):
        return payload

    current_url = str(inspected.get("url", "")).lower()
    current_text = str(inspected.get("text", "")).lower()
    current_title = str(inspected.get("title", "")).lower()

    if "shibidp.its.virginia.edu" in current_url or "netbadge" in current_text or "netbadge" in current_title:
        payload["status"] = "netbadge-login-required"
        return payload

    if "myworkday.com" not in current_url:
        payload["status"] = "unexpected-workday-landing"
        return payload

    if "approve" not in current_text:
        payload["status"] = "approve-button-not-found"
        return payload

    approve_click = chrome_click_button(["Approve"])
    payload["approve_click"] = approve_click
    if not approve_click.get("ok"):
        payload["status"] = str(approve_click.get("status") or approve_click.get("reason") or "approve-click-failed")
        return payload

    time.sleep(2)
    follow_up = chrome_click_button(["Submit", "Done", "OK"])
    payload["follow_up_click"] = follow_up
    payload["post_click"] = chrome_inspect_active_tab()
    payload["ok"] = True
    payload["status"] = "approved-clicked"
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Auto-actions for selected Outlook messages.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    approve = subparsers.add_parser("approve-selected-expense", help="Open the selected Workday expense task and attempt approval.")
    approve.set_defaults(func=lambda _: print(json.dumps(attempt_expense_approval_from_selected(), ensure_ascii=False, indent=2)) or 0)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
