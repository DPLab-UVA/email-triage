#!/usr/bin/env python3
"""Control macOS Mail.app through AppleScript."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"
APPLE_SCRIPT_TIMEOUT = 20.0


class MailAppError(RuntimeError):
    """Raised for recoverable Mail.app automation failures."""


def run_applescript(script: str, *args: str) -> str:
    try:
        process = subprocess.run(
            ["osascript", "-", *args],
            input=script,
            capture_output=True,
            text=True,
            check=False,
            timeout=APPLE_SCRIPT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise MailAppError(f"AppleScript timed out after {APPLE_SCRIPT_TIMEOUT} seconds.") from exc
    if process.returncode != 0:
        stderr = (process.stderr or process.stdout).strip()
        hint = " Grant Terminal/Codex permission in System Settings > Privacy & Security > Automation if prompted."
        raise MailAppError(f"{stderr or 'AppleScript execution failed.'}{hint}")
    return process.stdout.strip()


def parse_rows(raw: str, fields: list[str]) -> list[dict[str, str]]:
    if not raw:
        return []
    rows = []
    for record in raw.split(RECORD_SEP):
        if not record:
            continue
        parts = record.split(FIELD_SEP)
        row = {field: parts[index] if index < len(parts) else "" for index, field in enumerate(fields)}
        rows.append(row)
    return rows


def print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


ACCOUNTS_SCRIPT = r'''
on joinList(itemsList, delimiterValue)
	set oldDelimiters to AppleScript's text item delimiters
	set AppleScript's text item delimiters to delimiterValue
	set joinedValue to itemsList as text
	set AppleScript's text item delimiters to oldDelimiters
	return joinedValue
end joinList

on boolText(flagValue)
	if flagValue then return "true"
	return "false"
end boolText

on run argv
	set fieldDelimiter to ASCII character 31
	set recordDelimiter to ASCII character 30
	set rows to {}
	tell application "Mail"
		repeat with acct in every account
			try
				set acctType to (account type of acct) as text
			on error
				set acctType to ""
			end try
			try
				set serverNameValue to server name of acct
			on error
				set serverNameValue to ""
			end try
			try
				set emailText to my joinList(email addresses of acct, ", ")
			on error
				set emailText to ""
			end try
			set rowValue to (name of acct as text) & fieldDelimiter & (id of acct as text) & fieldDelimiter & (my boolText(enabled of acct)) & fieldDelimiter & acctType & fieldDelimiter & emailText & fieldDelimiter & (user name of acct as text) & fieldDelimiter & serverNameValue
			set end of rows to rowValue
		end repeat
	end tell
	set oldDelimiters to AppleScript's text item delimiters
	set AppleScript's text item delimiters to recordDelimiter
	set outputText to rows as text
	set AppleScript's text item delimiters to oldDelimiters
	return outputText
end run
'''

MAILBOXES_SCRIPT = r'''
on appendMailboxRows(theMailbox, prefixValue, rows, fieldDelimiter)
	tell application "Mail"
		set mailboxName to name of theMailbox as text
		set mailboxPath to prefixValue & "/" & mailboxName
		set unreadValue to unread count of theMailbox
		set accountNameValue to name of account of theMailbox as text
		set rowValue to mailboxPath & fieldDelimiter & mailboxName & fieldDelimiter & accountNameValue & fieldDelimiter & (unreadValue as text)
		set end of rows to rowValue
		repeat with childMailbox in every mailbox of theMailbox
			set rows to my appendMailboxRows(childMailbox, mailboxPath, rows, fieldDelimiter)
		end repeat
	end tell
	return rows
end appendMailboxRows

on run argv
	set fieldDelimiter to ASCII character 31
	set recordDelimiter to ASCII character 30
	set rows to {}
	tell application "Mail"
		repeat with acct in every account
			set accountNameValue to name of acct as text
			repeat with theMailbox in every mailbox of acct
				set rows to my appendMailboxRows(theMailbox, accountNameValue, rows, fieldDelimiter)
			end repeat
		end repeat
	end tell
	set oldDelimiters to AppleScript's text item delimiters
	set AppleScript's text item delimiters to recordDelimiter
	set outputText to rows as text
	set AppleScript's text item delimiters to oldDelimiters
	return outputText
end run
'''

LIST_SCRIPT = r'''
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

on boolText(flagValue)
	if flagValue then return "true"
	return "false"
end boolText

on dateText(messageRef, propertyName)
	try
		if propertyName is "received" then
			return (date received of messageRef as text)
		else
			return (date sent of messageRef as text)
		end if
	on error
		return ""
	end try
end dateText

on run argv
	set mailboxPath to item 1 of argv
	set limitValue to item 2 of argv as integer
	set offsetValue to item 3 of argv as integer
	set fieldDelimiter to ASCII character 31
	set recordDelimiter to ASCII character 30
	set rows to {}
	tell application "Mail"
		set targetMailbox to my mailboxForPath(mailboxPath)
		set messageList to messages of targetMailbox
		set messageCount to count of messageList
		if messageCount is 0 then return ""
		if offsetValue < 0 then set offsetValue to 0
		set startIndex to offsetValue + 1
		if startIndex > messageCount then return ""
		set endIndex to messageCount
		if limitValue > 0 then
			set candidateEndIndex to startIndex + limitValue - 1
			if candidateEndIndex < endIndex then set endIndex to candidateEndIndex
		end if
		set messageList to items startIndex thru endIndex of messageList
		repeat with messageRef in messageList
			try
				set headerIdValue to message id of messageRef as text
			on error
				set headerIdValue to ""
			end try
			set rowValue to (id of messageRef as text) & fieldDelimiter & headerIdValue & fieldDelimiter & (subject of messageRef as text) & fieldDelimiter & (sender of messageRef as text) & fieldDelimiter & (my boolText(read status of messageRef)) & fieldDelimiter & (my dateText(messageRef, "received")) & fieldDelimiter & (my dateText(messageRef, "sent"))
			set end of rows to rowValue
		end repeat
	end tell
	set oldDelimiters to AppleScript's text item delimiters
	set AppleScript's text item delimiters to recordDelimiter
	set outputText to rows as text
	set AppleScript's text item delimiters to oldDelimiters
	return outputText
end run
'''

READ_SCRIPT = r'''
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

on boolText(flagValue)
	if flagValue then return "true"
	return "false"
end boolText

on dateText(messageRef, propertyName)
	try
		if propertyName is "received" then
			return (date received of messageRef as text)
		else
			return (date sent of messageRef as text)
		end if
	on error
		return ""
	end try
end dateText

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
		try
			set replyToValue to reply to of messageRef as text
		on error
			set replyToValue to ""
		end try
		set bodyValue to content of messageRef as text
		return (id of messageRef as text) & fieldDelimiter & headerIdValue & fieldDelimiter & (subject of messageRef as text) & fieldDelimiter & (sender of messageRef as text) & fieldDelimiter & (my boolText(read status of messageRef)) & fieldDelimiter & (my dateText(messageRef, "received")) & fieldDelimiter & (my dateText(messageRef, "sent")) & fieldDelimiter & replyToValue & fieldDelimiter & bodyValue
	end tell
end run
'''

SELECTED_SCRIPT = r'''
on boolText(flagValue)
	if flagValue then return "true"
	return "false"
end boolText

on dateText(messageRef, propertyName)
	tell application "Mail"
		try
			if propertyName is "received" then
				return (date received of messageRef as text)
			else
				return (date sent of messageRef as text)
			end if
		on error
			return ""
		end try
	end tell
end dateText

on messageRow(messageRef, fieldDelimiter, includeBody)
	tell application "Mail"
		try
			set headerIdValue to message id of messageRef as text
		on error
			set headerIdValue to ""
		end try
		try
			set accountNameValue to name of account of mailbox of messageRef as text
		on error
			set accountNameValue to ""
		end try
		try
			set mailboxNameValue to name of mailbox of messageRef as text
		on error
			set mailboxNameValue to ""
		end try
		try
			set replyToValue to reply to of messageRef as text
		on error
			set replyToValue to ""
		end try
		if includeBody then
			try
				set bodyValue to content of messageRef as text
			on error
				set bodyValue to ""
			end try
		else
			set bodyValue to ""
		end if
		return (id of messageRef as text) & fieldDelimiter & headerIdValue & fieldDelimiter & accountNameValue & fieldDelimiter & mailboxNameValue & fieldDelimiter & (subject of messageRef as text) & fieldDelimiter & (sender of messageRef as text) & fieldDelimiter & (my boolText(read status of messageRef)) & fieldDelimiter & (my dateText(messageRef, "received")) & fieldDelimiter & (my dateText(messageRef, "sent")) & fieldDelimiter & replyToValue & fieldDelimiter & bodyValue
	end tell
end messageRow

on run argv
	set limitValue to item 1 of argv as integer
	set includeBody to (item 2 of argv is "true")
	set fieldDelimiter to ASCII character 31
	set recordDelimiter to ASCII character 30
	set rows to {}
	tell application "Mail"
		if (count of message viewers) is 0 then return ""
		try
			set selectedList to selected messages of message viewer 1
		on error
			set selectedList to {}
		end try
		if selectedList is missing value then set selectedList to {}
		if (count of selectedList) is 0 then return ""
		if limitValue > 0 and limitValue < (count of selectedList) then
			set selectedList to items 1 thru limitValue of selectedList
		end if
		repeat with messageRef in selectedList
			set end of rows to my messageRow(messageRef, fieldDelimiter, includeBody)
		end repeat
	end tell
	set oldDelimiters to AppleScript's text item delimiters
	set AppleScript's text item delimiters to recordDelimiter
	set outputText to rows as text
	set AppleScript's text item delimiters to oldDelimiters
	return outputText
end run
'''

MARK_READ_SCRIPT = r'''
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
	set targetState to item 3 of argv
	if targetState is "true" then
		set boolValue to true
	else
		set boolValue to false
	end if
	tell application "Mail"
		set targetMailbox to my mailboxForPath(mailboxPath)
		set messageRef to first message of targetMailbox whose id is messageInternalId
		set read status of messageRef to boolValue
		return id of messageRef as text
	end tell
end run
'''

MOVE_SCRIPT = r'''
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
	set sourceMailboxPath to item 1 of argv
	set messageInternalId to item 2 of argv as integer
	set destinationMailboxPath to item 3 of argv
	tell application "Mail"
		set sourceMailbox to my mailboxForPath(sourceMailboxPath)
		set destinationMailbox to my mailboxForPath(destinationMailboxPath)
		set messageRef to first message of sourceMailbox whose id is messageInternalId
		move messageRef to destinationMailbox
		return destinationMailboxPath
	end tell
end run
'''

CHECK_MAIL_SCRIPT = r'''
on run argv
	tell application "Mail"
		check for new mail
	end tell
	return "ok"
end run
'''

COMPOSE_SCRIPT = r'''
on splitAddresses(rawValue)
	if rawValue is "" then return {}
	set oldDelimiters to AppleScript's text item delimiters
	set AppleScript's text item delimiters to ","
	set rawItems to every text item of rawValue
	set AppleScript's text item delimiters to oldDelimiters
	set outputItems to {}
	repeat with rawItem in rawItems
		set trimmedItem to my trimText(rawItem as text)
		if trimmedItem is not "" then set end of outputItems to trimmedItem
	end repeat
	return outputItems
end splitAddresses

on trimText(inputValue)
	set whitespaceChars to {space, tab, return, linefeed}
	set outputValue to inputValue
	repeat while outputValue is not "" and character 1 of outputValue is in whitespaceChars
		set outputValue to text 2 thru -1 of outputValue
	end repeat
	repeat while outputValue is not "" and character -1 of outputValue is in whitespaceChars
		set outputValue to text 1 thru -2 of outputValue
	end repeat
	return outputValue
end trimText

on addRecipients(messageRef, addressList, recipientKind)
	tell application "Mail"
		repeat with addressValue in addressList
			if recipientKind is "to" then
				make new to recipient at end of to recipients of messageRef with properties {address:(addressValue as text)}
			else if recipientKind is "cc" then
				make new cc recipient at end of cc recipients of messageRef with properties {address:(addressValue as text)}
			else if recipientKind is "bcc" then
				make new bcc recipient at end of bcc recipients of messageRef with properties {address:(addressValue as text)}
			end if
		end repeat
	end tell
end addRecipients

on run argv
	set sendNowText to item 1 of argv
	set subjectText to item 2 of argv
	set bodyText to item 3 of argv
	set toText to item 4 of argv
	set ccText to item 5 of argv
	set bccText to item 6 of argv
	set senderText to item 7 of argv
	set visibleText to item 8 of argv
	set sendNow to (sendNowText is "true")
	set visibleFlag to (visibleText is "true")
	tell application "Mail"
		set messageRef to make new outgoing message with properties {subject:subjectText, content:bodyText, visible:visibleFlag}
		if senderText is not "" then set sender of messageRef to senderText
		my addRecipients(messageRef, my splitAddresses(toText), "to")
		my addRecipients(messageRef, my splitAddresses(ccText), "cc")
		my addRecipients(messageRef, my splitAddresses(bccText), "bcc")
		if sendNow then
			send messageRef
		else
			save messageRef
		end if
		return (id of messageRef as text) & ASCII character 31 & (sender of messageRef as text)
	end tell
end run
'''


def get_accounts() -> list[dict[str, str]]:
    return parse_rows(
        run_applescript(ACCOUNTS_SCRIPT),
        ["name", "id", "enabled", "account_type", "email_addresses", "user_name", "server_name"],
    )


def get_mailboxes() -> list[dict[str, str]]:
    rows = parse_rows(run_applescript(MAILBOXES_SCRIPT), ["path", "name", "account_name", "unread_count"])
    return sorted(rows, key=lambda row: row["path"].casefold())


def resolve_mailbox(selector: str) -> dict[str, str]:
    mailboxes = get_mailboxes()
    normalized = selector.strip().strip("/")
    if not normalized:
        raise MailAppError("Mailbox selector cannot be empty.")
    exact_matches = [row for row in mailboxes if row["path"].casefold() == normalized.casefold()]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise MailAppError(f"Mailbox path is ambiguous: {selector}")
    leaf_matches = [row for row in mailboxes if row["name"].casefold() == normalized.casefold()]
    if len(leaf_matches) == 1:
        return leaf_matches[0]
    if len(leaf_matches) > 1:
        options = ", ".join(row["path"] for row in leaf_matches)
        raise MailAppError(f"Mailbox name is ambiguous: {selector}. Use one of: {options}")
    raise MailAppError(f"Mailbox not found: {selector}")


def parse_compose_result(raw: str) -> dict[str, str]:
    parts = raw.split(FIELD_SEP)
    return {
        "id": parts[0] if len(parts) > 0 else "",
        "sender": parts[1] if len(parts) > 1 else "",
    }


def parse_message_rows(raw: str) -> list[dict[str, str]]:
    return parse_rows(
        raw,
        ["id", "message_id", "account", "mailbox", "subject", "sender", "read", "date_received", "date_sent", "reply_to", "body"],
    )


def selected_messages(*, include_body: bool, limit: int) -> list[dict[str, str]]:
    return parse_message_rows(
        run_applescript(
            SELECTED_SCRIPT,
            str(limit),
            "true" if include_body else "false",
        )
    )


def command_accounts(args: argparse.Namespace) -> int:
    accounts = get_accounts()
    if args.json:
        print_json(accounts)
        return 0
    for account in accounts:
        print(
            f"{account['name']} | enabled={account['enabled']} | type={account['account_type']} "
            f"| emails={account['email_addresses']} | id={account['id']}"
        )
    return 0


def command_mailboxes(args: argparse.Namespace) -> int:
    mailboxes = get_mailboxes()
    if args.json:
        print_json(mailboxes)
        return 0
    for mailbox in mailboxes:
        print(
            f"{mailbox['path']} | unread={mailbox['unread_count']} | account={mailbox['account_name']}"
        )
    return 0


def command_list(args: argparse.Namespace) -> int:
    mailbox = resolve_mailbox(args.mailbox)
    rows = parse_rows(
        run_applescript(LIST_SCRIPT, mailbox["path"], str(args.limit), str(args.offset)),
        ["id", "message_id", "subject", "sender", "read", "date_received", "date_sent"],
    )
    payload = {"mailbox": mailbox, "messages": rows}
    if args.json:
        print_json(payload)
        return 0
    for row in rows:
        status = "READ" if row["read"] == "true" else "UNREAD"
        when = row["date_received"] or row["date_sent"] or "-"
        subject = row["subject"] or "(no subject)"
        print(f"[{status}] {when} | {row['sender']} | {subject} | id={row['id']}")
    return 0


def command_read(args: argparse.Namespace) -> int:
    mailbox = resolve_mailbox(args.mailbox)
    raw = run_applescript(READ_SCRIPT, mailbox["path"], str(args.id))
    rows = parse_rows(
        raw,
        ["id", "message_id", "subject", "sender", "read", "date_received", "date_sent", "reply_to", "body"],
    )
    if not rows:
        raise MailAppError(f"Message not found in {mailbox['path']}: {args.id}")
    payload = {"mailbox": mailbox, "message": rows[0]}
    if args.json:
        print_json(payload)
        return 0
    message = rows[0]
    print(f"Mailbox: {mailbox['path']}")
    print(f"Subject: {message['subject']}")
    print(f"From: {message['sender']}")
    print(f"Reply-To: {message['reply_to']}")
    print(f"Received: {message['date_received']}")
    print(f"Sent: {message['date_sent']}")
    print(f"Read: {message['read']}")
    print(f"Message-ID: {message['message_id']}")
    print("")
    print("Body:")
    print(message["body"])
    return 0


def command_selected(args: argparse.Namespace) -> int:
    rows = selected_messages(include_body=args.include_body, limit=args.limit)
    payload = {"selected_count": len(rows), "messages": rows}
    if args.json:
        print_json(payload)
        return 0
    for row in rows:
        status = "READ" if row["read"] == "true" else "UNREAD"
        when = row["date_received"] or row["date_sent"] or "-"
        subject = row["subject"] or "(no subject)"
        mailbox = "/".join(part for part in [row["account"], row["mailbox"]] if part) or "-"
        print(f"[{status}] {when} | {mailbox} | {row['sender']} | {subject} | id={row['id']}")
    return 0


def command_current(args: argparse.Namespace) -> int:
    rows = selected_messages(include_body=args.include_body, limit=1)
    if not rows:
        raise MailAppError("No selected message in the front Mail viewer.")
    payload = {"message": rows[0]}
    if args.json:
        print_json(payload)
        return 0
    message = rows[0]
    print(f"Account: {message['account']}")
    print(f"Mailbox: {message['mailbox']}")
    print(f"Subject: {message['subject']}")
    print(f"From: {message['sender']}")
    print(f"Reply-To: {message['reply_to']}")
    print(f"Received: {message['date_received']}")
    print(f"Sent: {message['date_sent']}")
    print(f"Read: {message['read']}")
    print(f"Message-ID: {message['message_id']}")
    if args.include_body:
        print("")
        print("Body:")
        print(message["body"])
    return 0


def command_mark_read(args: argparse.Namespace) -> int:
    mailbox = resolve_mailbox(args.mailbox)
    target_state = "false" if args.unread else "true"
    run_applescript(MARK_READ_SCRIPT, mailbox["path"], str(args.id), target_state)
    payload = {"mailbox": mailbox["path"], "id": str(args.id), "read": target_state == "true"}
    if args.json:
        print_json(payload)
        return 0
    state = "unread" if args.unread else "read"
    print(f"Marked message as {state}: {args.id} in {mailbox['path']}")
    return 0


def command_move(args: argparse.Namespace) -> int:
    source = resolve_mailbox(args.mailbox)
    destination = resolve_mailbox(args.destination)
    run_applescript(MOVE_SCRIPT, source["path"], str(args.id), destination["path"])
    payload = {"id": str(args.id), "source": source["path"], "destination": destination["path"]}
    if args.json:
        print_json(payload)
        return 0
    print(f"Moved message {args.id} from {source['path']} to {destination['path']}")
    return 0


def read_body_argument(args: argparse.Namespace) -> str:
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8")
    if args.body is not None:
        return args.body
    raise MailAppError("Provide either --body or --body-file.")


def choose_sender(args: argparse.Namespace) -> str:
    if args.sender:
        return args.sender
    if not args.account:
        return ""
    accounts = get_accounts()
    matches = [row for row in accounts if row["name"].casefold() == args.account.casefold()]
    if not matches:
        raise MailAppError(f"Account not found: {args.account}")
    emails = [value.strip() for value in matches[0]["email_addresses"].split(",") if value.strip()]
    if not emails:
        raise MailAppError(f"Account has no configured sender address: {args.account}")
    return emails[0]


def command_compose_common(args: argparse.Namespace, *, send_now: bool) -> int:
    body = read_body_argument(args)
    sender = choose_sender(args)
    result = parse_compose_result(
        run_applescript(
            COMPOSE_SCRIPT,
            "true" if send_now else "false",
            args.subject,
            body,
            args.to,
            args.cc or "",
            args.bcc or "",
            sender,
            "true" if args.visible else "false",
        )
    )
    payload = {
        "id": result["id"],
        "sender": result["sender"],
        "to": args.to,
        "cc": args.cc or "",
        "bcc": args.bcc or "",
        "subject": args.subject,
        "action": "send" if send_now else "compose",
    }
    if args.json:
        print_json(payload)
        return 0
    if send_now:
        print(f"Sent message with subject '{args.subject}' from {result['sender'] or '<default sender>'}")
    else:
        print(f"Created draft with subject '{args.subject}' from {result['sender'] or '<default sender>'}")
    return 0


def command_compose(args: argparse.Namespace) -> int:
    return command_compose_common(args, send_now=False)


def command_send(args: argparse.Namespace) -> int:
    return command_compose_common(args, send_now=True)


def command_check_mail(args: argparse.Namespace) -> int:
    del args
    run_applescript(CHECK_MAIL_SCRIPT)
    print("Triggered Mail.app check for new mail.")
    return 0


def add_json_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")


def add_message_body_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--body", help="Inline message body.")
    parser.add_argument("--body-file", help="Read UTF-8 body content from a file.")


def add_compose_arguments(parser: argparse.ArgumentParser) -> None:
    add_json_argument(parser)
    parser.add_argument("--to", required=True, help="Comma-separated to-recipient list.")
    parser.add_argument("--cc", help="Comma-separated CC list.")
    parser.add_argument("--bcc", help="Comma-separated BCC list.")
    parser.add_argument("--subject", required=True, help="Message subject.")
    add_message_body_arguments(parser)
    parser.add_argument("--account", help="Mail.app account name to derive the sender address from.")
    parser.add_argument("--sender", help="Explicit sender email address.")
    parser.add_argument("--visible", action="store_true", help="Open the compose window visibly.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control macOS Mail.app mailboxes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    accounts_parser = subparsers.add_parser("accounts", help="List configured Mail.app accounts.")
    add_json_argument(accounts_parser)
    accounts_parser.set_defaults(func=command_accounts)

    mailboxes_parser = subparsers.add_parser("mailboxes", help="List mailbox paths.")
    add_json_argument(mailboxes_parser)
    mailboxes_parser.set_defaults(func=command_mailboxes)

    list_parser = subparsers.add_parser("list", help="List messages from one mailbox.")
    add_json_argument(list_parser)
    list_parser.add_argument("--mailbox", required=True, help="Mailbox path or unique mailbox name.")
    list_parser.add_argument("--limit", type=int, default=10, help="Number of messages to list.")
    list_parser.add_argument("--offset", type=int, default=0, help="Skip this many newest messages before listing.")
    list_parser.set_defaults(func=command_list)

    read_parser = subparsers.add_parser("read", help="Read one message by Mail.app message id.")
    add_json_argument(read_parser)
    read_parser.add_argument("--mailbox", required=True, help="Mailbox path or unique mailbox name.")
    read_parser.add_argument("--id", required=True, type=int, help="Mail.app message id from the list command.")
    read_parser.set_defaults(func=command_read)

    selected_parser = subparsers.add_parser("selected", help="Read currently selected messages in Mail.app.")
    add_json_argument(selected_parser)
    selected_parser.add_argument("--limit", type=int, default=20, help="Maximum number of selected messages to return.")
    selected_parser.add_argument(
        "--include-body",
        action="store_true",
        help="Include body text for selected messages. Slower on remote mailboxes.",
    )
    selected_parser.set_defaults(func=command_selected)

    current_parser = subparsers.add_parser(
        "current",
        help="Read the first selected message in the front Mail.app viewer.",
    )
    add_json_argument(current_parser)
    current_parser.add_argument(
        "--include-body",
        action="store_true",
        help="Include body text for the selected message. Slower on remote mailboxes.",
    )
    current_parser.set_defaults(func=command_current)

    mark_parser = subparsers.add_parser("mark-read", help="Mark a message read or unread.")
    add_json_argument(mark_parser)
    mark_parser.add_argument("--mailbox", required=True, help="Mailbox path or unique mailbox name.")
    mark_parser.add_argument("--id", required=True, type=int, help="Mail.app message id.")
    mark_parser.add_argument("--unread", action="store_true", help="Mark unread instead of read.")
    mark_parser.set_defaults(func=command_mark_read)

    move_parser = subparsers.add_parser("move", help="Move a message between mailboxes.")
    add_json_argument(move_parser)
    move_parser.add_argument("--mailbox", required=True, help="Source mailbox path or unique name.")
    move_parser.add_argument("--id", required=True, type=int, help="Mail.app message id.")
    move_parser.add_argument("--destination", required=True, help="Destination mailbox path or unique name.")
    move_parser.set_defaults(func=command_move)

    compose_parser = subparsers.add_parser("compose", help="Create and save a draft message.")
    add_compose_arguments(compose_parser)
    compose_parser.set_defaults(func=command_compose)

    send_parser = subparsers.add_parser("send", help="Send a message immediately.")
    add_compose_arguments(send_parser)
    send_parser.set_defaults(func=command_send)

    check_parser = subparsers.add_parser("check-mail", help="Trigger Mail.app to check for new mail.")
    check_parser.set_defaults(func=command_check_mail)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except MailAppError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
