#!/usr/bin/env python3
"""Control Gmail through the official Gmail API."""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SKILL_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = SKILL_ROOT / "state"
DEFAULT_CREDENTIALS = STATE_DIR / "credentials.json"
DEFAULT_TOKEN = STATE_DIR / "gmail_token.json"

SCOPES_BY_MODE = {
    "readonly": ["https://www.googleapis.com/auth/gmail.readonly"],
    "triage": ["https://www.googleapis.com/auth/gmail.modify"],
    "send": ["https://www.googleapis.com/auth/gmail.send"],
}

READ_SCOPES = {
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://mail.google.com/",
}
WRITE_SCOPES = {
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://mail.google.com/",
}


class GmailApiError(RuntimeError):
    """Raised for recoverable Gmail API workflow errors."""


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def load_token(token_path: Path) -> Credentials | None:
    if not token_path.exists():
        return None
    return Credentials.from_authorized_user_file(str(token_path))


def save_token(token_path: Path, creds: Credentials) -> None:
    ensure_parent(token_path)
    token_path.write_text(creds.to_json(), encoding="utf-8")


def ensure_scopes(creds: Credentials, required_scopes: set[str]) -> None:
    granted = set(creds.scopes or [])
    if not granted:
        raise GmailApiError("Token has no recorded scopes. Re-run auth.")
    if granted & required_scopes:
        return
    raise GmailApiError(
        "Token does not include the required Gmail scopes. Re-run auth with a broader mode."
    )


def auth(credentials_path: Path, token_path: Path, mode: str) -> Credentials:
    scopes = SCOPES_BY_MODE[mode]
    if not credentials_path.exists():
        raise GmailApiError(f"Credentials file not found: {credentials_path}")

    creds = load_token(token_path)
    requested_scopes = set(scopes)
    existing_scopes = set(creds.scopes or []) if creds else set()
    if creds and creds.valid and requested_scopes.issubset(existing_scopes):
        return creds
    if creds and creds.expired and creds.refresh_token and requested_scopes.issubset(existing_scopes):
        creds.refresh(Request())
        save_token(token_path, creds)
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), scopes)
    creds = flow.run_local_server(port=0)
    save_token(token_path, creds)
    return creds


def get_service(token_path: Path, *, require: str | None = None) -> Any:
    creds = load_token(token_path)
    if creds is None:
        raise GmailApiError("No Gmail token found. Run `auth` first.")
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_token(token_path, creds)
    if not creds.valid:
        raise GmailApiError("Gmail token is invalid. Re-run `auth`.")
    if require == "read":
        ensure_scopes(creds, READ_SCOPES)
    elif require == "write":
        ensure_scopes(creds, WRITE_SCOPES)
    return build("gmail", "v1", credentials=creds)


def header_map(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers", [])
    return {item.get("name", "").lower(): item.get("value", "") for item in headers}


def decode_b64url(data: str) -> str:
    if not data:
        return ""
    padding = "=" * (-len(data) % 4)
    decoded = base64.urlsafe_b64decode((data + padding).encode("utf-8"))
    return decoded.decode("utf-8", errors="ignore")


def strip_html(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def extract_body(payload: dict[str, Any]) -> str:
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")
    if mime_type == "text/plain" and body_data:
        return decode_b64url(body_data)
    if mime_type == "text/html" and body_data:
        return strip_html(decode_b64url(body_data))
    for part in payload.get("parts", []) or []:
        body = extract_body(part)
        if body:
            return body
    if body_data:
        return decode_b64url(body_data)
    return ""


def normalize_message(service: Any, message_id: str, *, format_name: str = "metadata") -> dict[str, Any]:
    kwargs: dict[str, Any] = {"userId": "me", "id": message_id, "format": format_name}
    if format_name == "metadata":
        kwargs["metadataHeaders"] = ["From", "To", "Cc", "Bcc", "Subject", "Date", "Reply-To", "Message-Id", "References"]
    payload = service.users().messages().get(**kwargs).execute()
    header_values = header_map(payload.get("payload", {}))
    body = ""
    if format_name != "metadata":
        body = extract_body(payload.get("payload", {}))
    return {
        "id": payload.get("id", ""),
        "thread_id": payload.get("threadId", ""),
        "label_ids": payload.get("labelIds", []),
        "snippet": payload.get("snippet", ""),
        "history_id": payload.get("historyId", ""),
        "internal_date": payload.get("internalDate", ""),
        "from": header_values.get("from", ""),
        "to": header_values.get("to", ""),
        "cc": header_values.get("cc", ""),
        "bcc": header_values.get("bcc", ""),
        "reply_to": header_values.get("reply-to", ""),
        "subject": header_values.get("subject", ""),
        "date": header_values.get("date", ""),
        "message_id_header": header_values.get("message-id", ""),
        "references": header_values.get("references", ""),
        "body": body,
    }


def mime_to_raw(message: EmailMessage) -> str:
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return encoded.rstrip("=")


def command_auth(args: argparse.Namespace) -> int:
    creds = auth(Path(args.credentials), Path(args.token), args.mode)
    payload = {
        "ok": True,
        "token_path": str(Path(args.token)),
        "scopes": creds.scopes or [],
    }
    print_json(payload)
    return 0


def command_status(args: argparse.Namespace) -> int:
    token_path = Path(args.token)
    creds = load_token(token_path)
    if creds is None:
        print_json({"ok": False, "token_path": str(token_path), "authenticated": False})
        return 0
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_token(token_path, creds)
    service = get_service(token_path)
    profile = service.users().getProfile(userId="me").execute()
    print_json(
        {
            "ok": True,
            "authenticated": True,
            "email_address": profile.get("emailAddress", ""),
            "messages_total": profile.get("messagesTotal", 0),
            "threads_total": profile.get("threadsTotal", 0),
            "history_id": profile.get("historyId", ""),
            "scopes": creds.scopes or [],
            "token_path": str(token_path),
        }
    )
    return 0


def command_labels(args: argparse.Namespace) -> int:
    service = get_service(Path(args.token), require="read")
    payload = service.users().labels().list(userId="me").execute()
    print_json({"labels": payload.get("labels", [])})
    return 0


def command_list(args: argparse.Namespace) -> int:
    service = get_service(Path(args.token), require="read")
    label_ids = args.label or None
    payload = service.users().messages().list(
        userId="me",
        labelIds=label_ids,
        q=args.query or None,
        maxResults=args.limit,
    ).execute()
    rows = []
    for row in payload.get("messages", []):
        rows.append(normalize_message(service, row["id"], format_name="metadata"))
    print_json({"messages": rows, "result_size_estimate": payload.get("resultSizeEstimate", 0)})
    return 0


def command_read(args: argparse.Namespace) -> int:
    service = get_service(Path(args.token), require="read")
    print_json({"message": normalize_message(service, args.id, format_name="full")})
    return 0


def build_base_email(args: argparse.Namespace) -> EmailMessage:
    message = EmailMessage()
    message["To"] = args.to
    if args.cc:
        message["Cc"] = args.cc
    if args.bcc:
        message["Bcc"] = args.bcc
    message["Subject"] = args.subject
    if args.reply_to:
        message["Reply-To"] = args.reply_to
    if args.from_address:
        message["From"] = args.from_address
    body = args.body
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    if body is None:
        raise GmailApiError("Provide either --body or --body-file.")
    message.set_content(body)
    return message


def command_draft(args: argparse.Namespace) -> int:
    service = get_service(Path(args.token), require="write")
    message = build_base_email(args)
    payload: dict[str, Any] = {"message": {"raw": mime_to_raw(message)}}
    if args.thread_id:
        payload["message"]["threadId"] = args.thread_id
    draft = service.users().drafts().create(userId="me", body=payload).execute()
    print_json({"draft": draft})
    return 0


def command_draft_reply(args: argparse.Namespace) -> int:
    service = get_service(Path(args.token), require="write")
    source = normalize_message(service, args.id, format_name="full")
    to_address = source.get("reply_to") or source.get("from")
    subject = source.get("subject", "").strip()
    subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    message = EmailMessage()
    message["To"] = to_address
    message["Subject"] = subject
    if source.get("message_id_header"):
        message["In-Reply-To"] = source["message_id_header"]
        message["References"] = " ".join(
            part for part in [source.get("references", "").strip(), source["message_id_header"]] if part
        )
    body = args.body
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
    if body is None:
        raise GmailApiError("Provide either --body or --body-file.")
    message.set_content(body)
    payload = {
        "message": {
            "raw": mime_to_raw(message),
            "threadId": source.get("thread_id", ""),
        }
    }
    draft = service.users().drafts().create(userId="me", body=payload).execute()
    print_json({"source_message": source, "draft": draft})
    return 0


def command_send(args: argparse.Namespace) -> int:
    service = get_service(Path(args.token), require="write")
    message = build_base_email(args)
    payload = {"raw": mime_to_raw(message)}
    sent = service.users().messages().send(userId="me", body=payload).execute()
    print_json({"message": sent})
    return 0


def add_common_auth_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--credentials", default=str(DEFAULT_CREDENTIALS))
    parser.add_argument("--token", default=str(DEFAULT_TOKEN))


def add_body_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--body")
    parser.add_argument("--body-file")


def add_compose_args(parser: argparse.ArgumentParser) -> None:
    add_common_auth_paths(parser)
    parser.add_argument("--to", required=True)
    parser.add_argument("--cc")
    parser.add_argument("--bcc")
    parser.add_argument("--subject", required=True)
    parser.add_argument("--reply-to")
    parser.add_argument("--from-address")
    parser.add_argument("--thread-id")
    add_body_args(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control Gmail through the official Gmail API.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_parser = subparsers.add_parser("auth", help="Run the Gmail OAuth flow and cache a local token.")
    add_common_auth_paths(auth_parser)
    auth_parser.add_argument("--mode", choices=sorted(SCOPES_BY_MODE), default="readonly")
    auth_parser.set_defaults(func=command_auth)

    status_parser = subparsers.add_parser("status", help="Show local Gmail auth status and basic profile info.")
    add_common_auth_paths(status_parser)
    status_parser.set_defaults(func=command_status)

    labels_parser = subparsers.add_parser("labels", help="List Gmail labels.")
    add_common_auth_paths(labels_parser)
    labels_parser.set_defaults(func=command_labels)

    list_parser = subparsers.add_parser("list", help="List recent Gmail messages.")
    add_common_auth_paths(list_parser)
    list_parser.add_argument("--label", action="append", help="Gmail label id such as INBOX. Repeatable.")
    list_parser.add_argument("--query", help="Gmail search query.")
    list_parser.add_argument("--limit", type=int, default=10)
    list_parser.set_defaults(func=command_list)

    read_parser = subparsers.add_parser("read", help="Read one Gmail message.")
    add_common_auth_paths(read_parser)
    read_parser.add_argument("--id", required=True, help="Gmail message id.")
    read_parser.set_defaults(func=command_read)

    draft_parser = subparsers.add_parser("draft", help="Create a Gmail draft.")
    add_compose_args(draft_parser)
    draft_parser.set_defaults(func=command_draft)

    reply_parser = subparsers.add_parser("draft-reply", help="Create a Gmail reply draft for one message.")
    add_common_auth_paths(reply_parser)
    reply_parser.add_argument("--id", required=True, help="Source Gmail message id.")
    add_body_args(reply_parser)
    reply_parser.set_defaults(func=command_draft_reply)

    send_parser = subparsers.add_parser("send", help="Send a Gmail message immediately.")
    add_compose_args(send_parser)
    send_parser.set_defaults(func=command_send)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except HttpError as exc:
        details = exc.error_details if hasattr(exc, "error_details") else str(exc)
        print(f"Error: Gmail API request failed: {details}", file=sys.stderr)
        return 1
    except GmailApiError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
