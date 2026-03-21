#!/usr/bin/env python3
"""Open the best unavailable/decline URL from a Mail.app review invitation."""

from __future__ import annotations

import argparse
import html
import json
import quopri
import re
import subprocess
import sys
from pathlib import Path

FIELD_SEP = "\x1f"
APPLE_SCRIPT_TIMEOUT = 20.0
MAIL_CLI_TIMEOUT = 20.0
MAIL_APP_CLI = Path(
    "/Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/mail-app-mailbox/scripts/mail_app_mailbox.py"
)

SELECTED_SOURCE_SCRIPT = r'''
on run argv
	set fieldDelimiter to ASCII character 31
	tell application "Mail"
		if (count of message viewers) is 0 then error "No Mail viewer is open."
		try
			set selectedList to selected messages of message viewer 1
		on error
			set selectedList to {}
		end try
		if selectedList is missing value then set selectedList to {}
		if (count of selectedList) is 0 then error "No selected message in the front Mail viewer."
		set messageRef to item 1 of selectedList
		try
			set headerIdValue to message id of messageRef as text
		on error
			set headerIdValue to ""
		end try
		try
			set mailboxNameValue to name of mailbox of messageRef as text
		on error
			set mailboxNameValue to ""
		end try
		try
			set accountNameValue to name of account of mailbox of messageRef as text
		on error
			set accountNameValue to ""
		end try
		set rawSource to source of messageRef as text
		return (id of messageRef as text) & fieldDelimiter & headerIdValue & fieldDelimiter & accountNameValue & fieldDelimiter & mailboxNameValue & fieldDelimiter & (sender of messageRef as text) & fieldDelimiter & (subject of messageRef as text) & fieldDelimiter & rawSource
	end tell
end run
'''

READ_SOURCE_SCRIPT = r'''
on mailboxForPath(pathValue)
	set oldDelimiters to AppleScript's text item delimiters
	set AppleScript's text item delimiters to "/"
	set pathItems to every text item of pathValue
	set AppleScript's text item delimiters to oldDelimiters
	if (count of pathItems) < 2 then error "Mailbox path must include account and mailbox."
	set accountNameValue to item 1 of pathItems
	tell application "Mail"
		set currentMailbox to mailbox (item 2 of pathItems) of account accountNameValue
		if (count of pathItems) > 2 then
			repeat with itemIndex from 3 to count of pathItems
				set currentMailbox to mailbox (item itemIndex of pathItems) of currentMailbox
			end repeat
		end if
		return currentMailbox
	end tell
end mailboxForPath

on run argv
	set mailboxPath to item 1 of argv
	set messageInternalId to item 2 of argv as integer
	set fieldDelimiter to ASCII character 31
	tell application "Mail"
		set targetMailbox to my mailboxForPath(mailboxPath)
		set messageRef to first message of targetMailbox whose id is messageInternalId
		try
			set headerIdValue to message id of messageRef as text
		on error
			set headerIdValue to ""
		end try
		return (id of messageRef as text) & fieldDelimiter & headerIdValue & fieldDelimiter & mailboxPath & fieldDelimiter & (sender of messageRef as text) & fieldDelimiter & (subject of messageRef as text) & fieldDelimiter & (source of messageRef as text)
	end tell
end run
'''

URL_RE = re.compile(r'https?://[^\s<>"\'()]+')
REVIEW_SUBJECT_RE = re.compile(r'(invitation to review|review invitation|invited to review|would you review)', re.I)
REVIEW_BODY_RE = re.compile(r'(journal|manuscript|associate editor|editor|referee|peer review)', re.I)


def run_applescript(script: str, *args: str) -> str:
    try:
        process = subprocess.run(
            ["osascript", "-", *args],
            input=script,
            text=True,
            capture_output=True,
            check=False,
            timeout=APPLE_SCRIPT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"AppleScript timed out after {APPLE_SCRIPT_TIMEOUT} seconds") from exc
    if process.returncode != 0:
        raise RuntimeError((process.stderr or process.stdout).strip() or "AppleScript failed")
    return process.stdout


def load_selected_message() -> dict[str, str]:
    raw = run_applescript(SELECTED_SOURCE_SCRIPT).strip()
    parts = raw.split(FIELD_SEP, 6)
    if len(parts) < 7:
        raise RuntimeError("Could not parse selected message source.")
    return {
        "id": parts[0],
        "message_id": parts[1],
        "account": parts[2],
        "mailbox": parts[3],
        "from": parts[4],
        "subject": parts[5],
        "source": parts[6],
    }


def load_message_by_mailbox_id(mailbox: str, message_id: int) -> dict[str, str]:
    raw = run_applescript(READ_SOURCE_SCRIPT, mailbox, str(message_id)).strip()
    parts = raw.split(FIELD_SEP, 5)
    if len(parts) < 6:
        raise RuntimeError("Could not parse source for requested message.")
    return {
        "id": parts[0],
        "message_id": parts[1],
        "account": mailbox.split("/", 1)[0],
        "mailbox": mailbox,
        "from": parts[3],
        "subject": parts[4],
        "source": parts[5],
    }


def run_mail_cli(*args: str) -> dict:
    try:
        process = subprocess.run(
            ["python3", str(MAIL_APP_CLI), *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=MAIL_CLI_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"mail_app_mailbox timed out after {MAIL_CLI_TIMEOUT} seconds") from exc
    if process.returncode != 0:
        raise RuntimeError((process.stderr or process.stdout).strip() or "mail_app_mailbox failed")
    return json.loads(process.stdout) if process.stdout.strip() else {}


def load_message_by_subject(mailboxes: list[str], subject_query: str, limit: int) -> dict[str, str]:
    query = subject_query.lower()
    for mailbox in mailboxes:
        payload = run_mail_cli("list", "--mailbox", mailbox, "--limit", str(limit), "--json")
        for row in payload.get("messages", []):
            if query in (row.get("subject", "").lower()):
                raw = run_applescript(READ_SOURCE_SCRIPT, mailbox, str(row["id"])).strip()
                parts = raw.split(FIELD_SEP, 5)
                if len(parts) < 6:
                    raise RuntimeError("Could not parse source for located message.")
                return {
                    "id": parts[0],
                    "message_id": parts[1],
                    "account": mailbox.split("/", 1)[0],
                    "mailbox": mailbox,
                    "from": parts[3],
                    "subject": parts[4],
                    "source": parts[5],
                }
    raise RuntimeError(f"No message found for subject query: {subject_query}")


def decode_source(raw_source: str) -> str:
    raw_bytes = raw_source.encode("utf-8", errors="ignore")
    decoded = quopri.decodestring(raw_bytes).decode("utf-8", errors="ignore")
    decoded = html.unescape(decoded)
    decoded = decoded.replace("=\r\n", "").replace("=\n", "")
    return decoded


def extract_urls(decoded_source: str) -> list[str]:
    urls = []
    seen = set()
    for url in URL_RE.findall(decoded_source):
        cleaned = url.rstrip(".,;)>]").replace("=3D", "=")
        if cleaned in seen:
            continue
        seen.add(cleaned)
        urls.append(cleaned)
    return urls


def score_url(url: str) -> int:
    lower = url.lower()
    score = 0
    if any(token in lower for token in ["unavailable", "decline", "declinereview", "notavailable"]):
        score += 20
    if any(token in lower for token in ["review", "reviewer", "manuscript", "editor", "invitation"]):
        score += 8
    if any(token in lower for token in ["scholarone", "editorialmanager", "manuscriptcentral", "elsevier", "springer", "wiley", "ieee"]):
        score += 6
    if any(token in lower for token in ["unsubscribe", "mailchi.mp", "list-manage", "facebook", "linkedin", "twitter", "instagram"]):
        score -= 20
    return score


def choose_best_url(urls: list[str]) -> tuple[str, int] | None:
    scored = sorted(((url, score_url(url)) for url in urls), key=lambda item: item[1], reverse=True)
    if not scored or scored[0][1] <= 0:
        return None
    return scored[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the best decline/unavailable URL from a Mail.app message.")
    parser.add_argument("--open", action="store_true", help="Open the best URL instead of printing it only.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--message-id", type=int, help="Mail.app internal id of the target message.")
    parser.add_argument("--subject-query", help="Find the message by subject substring instead of current selection.")
    parser.add_argument("--mailbox", action="append", help="Mailbox path to search with --subject-query. Repeatable.")
    parser.add_argument("--limit", type=int, default=40, help="Per-mailbox search limit for --subject-query.")
    args = parser.parse_args()

    if args.message_id is not None:
        if not args.mailbox or len(args.mailbox) != 1:
            raise RuntimeError("Provide exactly one --mailbox when using --message-id.")
        message = load_message_by_mailbox_id(args.mailbox[0], args.message_id)
    elif args.subject_query:
        mailboxes = args.mailbox or ["Exchange/Inbox", "Google/INBOX"]
        message = load_message_by_subject(mailboxes, args.subject_query, args.limit)
    else:
        message = load_selected_message()
    decoded_source = decode_source(message["source"])
    urls = extract_urls(decoded_source)
    best = choose_best_url(urls)
    subject = message["subject"]
    looks_like_review_invite = bool(REVIEW_SUBJECT_RE.search(subject) or (REVIEW_BODY_RE.search(decoded_source) and REVIEW_SUBJECT_RE.search(decoded_source)))

    payload = {
        "message": {
            "account": message["account"],
            "mailbox": message["mailbox"],
            "from": message["from"],
            "subject": subject,
            "id": message["id"],
            "message_id": message["message_id"],
        },
        "looks_like_review_invitation": looks_like_review_invite,
        "best_url": best[0] if best else "",
        "best_score": best[1] if best else 0,
        "url_count": len(urls),
        "candidate_urls": urls[:20],
        "opened": False,
    }

    if args.open and best and looks_like_review_invite:
        subprocess.run(["open", best[0]], check=False)
        payload["opened"] = True

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Subject: {subject}")
        print(f"From: {message['from']}")
        print(f"Review invitation: {looks_like_review_invite}")
        print(f"Best URL: {best[0] if best else ''}")
        print(f"Opened: {payload['opened']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
