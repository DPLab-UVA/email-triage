#!/usr/bin/env python3
"""Local wake server and page-side Outlook observer for event-driven monitor wakeups."""

from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from gstack_browse_bridge import BridgeError, send_command
from outlook_recent_triage import SHARED
from outlook_web_workflow import (
    DEFAULT_BROWSER,
    DEFAULT_COOKIE_DOMAINS,
    DEFAULT_PROFILE,
    ensure_outlook_session,
)

import sys

sys.path.append(str(SHARED))
from sqlite_store import append_event  # noqa: E402

DEFAULT_WAKE_EVENT_LOG = "outlook_wake_events"
DEFAULT_WAKE_HOST = "127.0.0.1"
DEFAULT_WAKE_PORT = 8766


def bridge_cmd(command: str, *args: str, timeout: float = 30.0) -> str:
    return send_command(command, list(args), timeout=timeout).strip()


def bridge_js(expr: str, *, timeout: float = 30.0) -> str:
    return bridge_cmd("js", expr, timeout=timeout)


def now_iso() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat()


@dataclass
class WakeSignal:
    timestamp: str
    reason: str
    fingerprint: str
    source: str
    path: str
    method: str

    def as_dict(self) -> dict[str, str]:
        return {
            "timestamp": self.timestamp,
            "reason": self.reason,
            "fingerprint": self.fingerprint,
            "source": self.source,
            "path": self.path,
            "method": self.method,
        }


class WakeSignalServer:
    def __init__(
        self,
        *,
        host: str = DEFAULT_WAKE_HOST,
        port: int = DEFAULT_WAKE_PORT,
        event_log: Path = DEFAULT_WAKE_EVENT_LOG,
        dedupe_window_seconds: float = 2.0,
    ) -> None:
        self.host = host
        self.port = port
        self.event_log = event_log
        self.dedupe_window_seconds = dedupe_window_seconds
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._latest: WakeSignal | None = None
        self._last_fingerprint = ""
        self._last_signal_at = 0.0

    def _accept(self, payload: dict[str, str]) -> bool:
        fingerprint = payload.get("fingerprint", "").strip()
        now = time.time()
        with self._lock:
            if (
                fingerprint
                and fingerprint == self._last_fingerprint
                and (now - self._last_signal_at) < self.dedupe_window_seconds
            ):
                return False
            self._last_fingerprint = fingerprint
            self._last_signal_at = now
            self._latest = WakeSignal(
                timestamp=payload.get("timestamp") or now_iso(),
                reason=payload.get("reason", ""),
                fingerprint=fingerprint,
                source=payload.get("source", "outlook-dom"),
                path=payload.get("path", "/wake"),
                method=payload.get("method", "GET"),
            )
            self._event.set()
        append_event(self.event_log, self._latest.as_dict())
        return True

    def start(self) -> None:
        if self._httpd is not None:
            return

        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
                return

            def _send(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    self._send(200, {"ok": True, "host": server.host, "port": server.port})
                    return
                if parsed.path != "/wake":
                    self._send(404, {"ok": False, "error": "not found"})
                    return
                query = parse_qs(parsed.query)
                payload = {
                    "timestamp": now_iso(),
                    "reason": query.get("reason", ["mutation"])[0],
                    "fingerprint": query.get("fingerprint", [""])[0],
                    "source": query.get("source", ["outlook-dom"])[0],
                    "path": parsed.path,
                    "method": "GET",
                }
                accepted = server._accept(payload)
                self._send(200, {"ok": True, "accepted": accepted})

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != "/wake":
                    self._send(404, {"ok": False, "error": "not found"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b""
                payload: dict[str, Any]
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    payload = {}
                accepted = server._accept(
                    {
                        "timestamp": now_iso(),
                        "reason": str(payload.get("reason", "mutation")),
                        "fingerprint": str(payload.get("fingerprint", "")),
                        "source": str(payload.get("source", "outlook-dom")),
                        "path": parsed.path,
                        "method": "POST",
                    }
                )
                self._send(200, {"ok": True, "accepted": accepted})

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        self._thread = None

    def wait(self, timeout: float) -> WakeSignal | None:
        triggered = self._event.wait(timeout=max(0.0, timeout))
        if not triggered:
            return None
        with self._lock:
            latest = self._latest
            self._latest = None
            self._event.clear()
        return latest


def install_outlook_wake_hook(
    *,
    host: str = DEFAULT_WAKE_HOST,
    port: int = DEFAULT_WAKE_PORT,
) -> dict[str, Any]:
    ensure_outlook_session(DEFAULT_BROWSER, DEFAULT_PROFILE, DEFAULT_COOKIE_DOMAINS)
    endpoint = f"http://{host}:{port}/wake"
    expr = f"""
JSON.stringify(
  (() => {{
    const endpoint = {json.dumps(endpoint)};
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const fingerprint = () => {{
      const rows = Array.from(document.querySelectorAll('[role="option"]')).slice(0, 8);
      return rows.map((el) => {{
        const sender = normalize(el.querySelector('[title], [aria-label]')?.getAttribute?.('title') || '');
        const label = normalize(el.getAttribute('aria-label') || '');
        const text = normalize(el.innerText || el.textContent || '').slice(0, 240);
        return [el.id || '', el.getAttribute('data-convid') || '', sender, label, text].join('|');
      }}).join('\\n');
    }};
    const sendWake = (reason) => {{
      const fp = fingerprint();
      if (!fp) return false;
      const state = window.__emailTriageWakeHook || {{}};
      const now = Date.now();
      if (state.lastFingerprint === fp && state.lastSentAt && now - state.lastSentAt < 4000) {{
        return false;
      }}
      state.seq = Number(state.seq || 0) + 1;
      state.lastFingerprint = fp;
      state.lastSentAt = now;
      state.lastReason = reason;
      const payload = {{
        source: 'outlook-dom',
        reason,
        fingerprint: fp.slice(0, 800),
        nonce: String(now) + '-' + Math.random().toString(36).slice(2)
      }};
      const query = new URLSearchParams(payload).toString();
      const body = JSON.stringify(payload);
      try {{
        if (navigator.sendBeacon) {{
          navigator.sendBeacon(endpoint, new Blob([body], {{ type: 'text/plain;charset=UTF-8' }}));
        }}
      }} catch (e) {{}}
      try {{
        fetch(endpoint, {{
          method: 'POST',
          mode: 'no-cors',
          keepalive: true,
          headers: {{ 'Content-Type': 'text/plain;charset=UTF-8' }},
          body,
        }}).catch(() => {{}});
      }} catch (e) {{}}
      try {{
        const img = new Image();
        img.referrerPolicy = 'no-referrer';
        img.src = endpoint + '?' + query;
      }} catch (e) {{}}
      window.__emailTriageWakeHook = state;
      return true;
    }};
    const previous = window.__emailTriageWakeHook;
    if (previous?.observer) {{
      try {{ previous.observer.disconnect(); }} catch (e) {{}}
    }}
    let timer = null;
    const schedule = (reason) => {{
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => sendWake(reason), 700);
    }};
    const observer = new MutationObserver(() => schedule('mutation'));
    observer.observe(document.body, {{
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['aria-label', 'aria-selected', 'title', 'data-convid', 'id']
    }});
    window.__emailTriageWakeHook = {{
      endpoint,
      observer,
      seq: Number(previous?.seq || 0),
      lastFingerprint: previous?.lastFingerprint || '',
      lastSentAt: previous?.lastSentAt || 0,
      lastReason: previous?.lastReason || '',
      sendNow: (reason = 'manual') => sendWake(reason),
      installedAt: new Date().toISOString()
    }};
    if (!previous) {{
      sendWake('installed');
    }}
    const current = window.__emailTriageWakeHook;
    return {{
      ok: true,
      endpoint,
      status: previous ? 'reinstalled' : 'installed',
      seq: Number(current?.seq || 0),
      lastSentAt: Number(current?.lastSentAt || 0),
      lastReason: current?.lastReason || ''
    }};
  }})(),
  null,
  2
)
""".strip()
    raw = bridge_js(expr, timeout=20.0)
    return json.loads(raw or "{}")


def trigger_manual_wake(*, reason: str = "manual") -> dict[str, Any]:
    expr = f"""
JSON.stringify(
  (() => {{
    const hook = window.__emailTriageWakeHook;
    if (!hook || typeof hook.sendNow !== 'function') {{
      return {{ ok: false, reason: 'wake-hook-not-installed' }};
    }}
    return {{ ok: !!hook.sendNow({json.dumps(reason)}), endpoint: hook.endpoint || '' }};
  }})(),
  null,
  2
)
""".strip()
    raw = bridge_js(expr, timeout=15.0)
    return json.loads(raw or "{}")


def read_wake_hook_state() -> dict[str, Any]:
    expr = """
JSON.stringify(
  (() => {
    const hook = window.__emailTriageWakeHook;
    if (!hook) {
      return { ok: false, installed: false };
    }
    return {
      ok: true,
      installed: true,
      endpoint: hook.endpoint || '',
      seq: Number(hook.seq || 0),
      lastSentAt: Number(hook.lastSentAt || 0),
      lastReason: hook.lastReason || '',
      installedAt: hook.installedAt || '',
      lastFingerprintPreview: String(hook.lastFingerprint || '').slice(0, 200)
    };
  })(),
  null,
  2
)
""".strip()
    raw = bridge_js(expr, timeout=10.0)
    return json.loads(raw or "{}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install and serve an Outlook wake hook.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser("install", help="Install the page-side wake observer.")
    install_parser.add_argument("--host", default=DEFAULT_WAKE_HOST)
    install_parser.add_argument("--port", type=int, default=DEFAULT_WAKE_PORT)

    manual_parser = subparsers.add_parser("manual-wake", help="Ask the page-side hook to fire one wake event.")
    manual_parser.add_argument("--reason", default="manual")

    status_parser = subparsers.add_parser("status", help="Read the page-side wake hook state.")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "install":
        print(json.dumps(install_outlook_wake_hook(host=args.host, port=args.port), ensure_ascii=False, indent=2))
        return 0
    if args.command == "manual-wake":
        print(json.dumps(trigger_manual_wake(reason=args.reason), ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        print(json.dumps(read_wake_hook_state(), ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
