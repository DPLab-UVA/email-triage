#!/usr/bin/env python3
"""Minimal local HTTP server for email triage prototypes."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from triage_engine import load_json, load_jsonl, triage_message


def normalize_capture(payload: dict) -> dict:
    view = payload.get("view", {}) if isinstance(payload, dict) else {}
    selected = payload.get("selectedMessage", {}) if isinstance(payload, dict) else {}
    selected_message = selected.get("message", {}) if isinstance(selected, dict) else {}
    sender = (
        selected.get("from")
        or selected.get("sender")
        or selected_message.get("from")
        or view.get("sender", "")
    )
    subject = (
        selected.get("subject")
        or selected_message.get("subject")
        or view.get("subject", "")
    )
    body = view.get("bodyText") or selected.get("bodyText") or ""
    return {
        "from": sender,
        "subject": subject,
        "body": body,
        "message_id": view.get("url", ""),
        "id": view.get("captureKey") or view.get("url", ""),
    }


class TriageHandler(BaseHTTPRequestHandler):
    rules = {}
    examples = []
    capture_path: Path | None = None

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._send_json(404, {"error": "not found"})
            return
        self._send_json(
            200,
            {
                "ok": True,
                "capture_path": str(self.capture_path) if self.capture_path else "",
            },
        )

    def _append_capture(self, payload: dict) -> None:
        if self.capture_path is None:
            return
        self.capture_path.parent.mkdir(parents=True, exist_ok=True)
        with self.capture_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/triage", "/capture"}:
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": f"invalid json: {exc}"})
            return

        message = normalize_capture(payload) if isinstance(payload, dict) and "view" in payload else payload
        result = triage_message(message, self.rules, self.examples)

        if self.path == "/triage":
            self._send_json(200, result)
            return

        record = {
            "captured_at": payload.get("view", {}).get("capturedAt", ""),
            "capture_key": payload.get("view", {}).get("captureKey", ""),
            "normalized_message": message,
            "triage": result,
            "report": payload,
        }
        self._append_capture(record)
        self._send_json(
            200,
            {
                "ok": True,
                "stored": True,
                "capture_path": str(self.capture_path) if self.capture_path else "",
                "triage": result,
            },
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve triage results over HTTP.")
    parser.add_argument("--rules", required=True, help="Path to rules JSON.")
    parser.add_argument("--examples", required=True, help="Path to examples JSONL.")
    parser.add_argument("--captures", default=str(Path(__file__).with_name("captured_outlook_reports.jsonl")))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    TriageHandler.rules = load_json(Path(args.rules))
    TriageHandler.examples = load_jsonl(Path(args.examples))
    TriageHandler.capture_path = Path(args.captures)
    server = HTTPServer((args.host, args.port), TriageHandler)
    print(f"Listening on http://{args.host}:{args.port}/triage")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
