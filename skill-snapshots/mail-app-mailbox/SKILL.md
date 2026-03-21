---
name: mail-app-mailbox
description: Control macOS Mail.app mailboxes through local AppleScript automation from a Python CLI. Use when Codex needs to inspect accounts, list mailboxes, read or draft messages, trigger mail checks, or manage Outlook/Exchange mail that is already synced into Apple Mail, especially when Microsoft Graph app registration is blocked or unavailable.
---

# Mail App Mailbox

## Overview

Use this skill when the mailbox is already connected to macOS Mail and local automation is preferable to Microsoft Graph. It is the recommended fallback for school or enterprise Outlook accounts when the tenant blocks app registration.

## Quick Start

1. Make sure the Outlook or Exchange account is added to Mail.app. If not, read `references/setup.md`.
2. On first use, let macOS grant automation permission when Mail or Terminal/Codex prompts.
3. Inspect local accounts and mailboxes:
   `python3 scripts/mail_app_mailbox.py accounts`
   `python3 scripts/mail_app_mailbox.py mailboxes`
4. List and read messages:
   `python3 scripts/mail_app_mailbox.py list --mailbox "Your Account/INBOX" --limit 20`
   `python3 scripts/mail_app_mailbox.py read --mailbox "Your Account/INBOX" --id 12345`
   `python3 scripts/mail_app_mailbox.py selected --limit 5 --include-body --json`
   `python3 scripts/mail_app_mailbox.py current --include-body`
5. Draft or send only with explicit user intent:
   `python3 scripts/mail_app_mailbox.py compose --to someone@example.com --subject "..." --body "..."`
   `python3 scripts/mail_app_mailbox.py send --to someone@example.com --subject "..." --body "..."`

## Scope

- Read local mailbox state through Mail.app:
  accounts, mailboxes, message listing, message reading
- Read only the currently selected Mail.app messages without enumerating a large mailbox
- Trigger local mailbox refresh:
  `check-mail`
- Create drafts or send mail through the account Mail.app resolves from the sender address
- Mark messages read or unread and move messages between local mailboxes

## Mailbox Selection

- Always discover mailbox paths with `mailboxes` before reading or mutating messages.
- The script prints mailbox paths in the form `Account Name/Mailbox/Submailbox`.
- Resolve by full path when possible. Bare mailbox names such as `INBOX` are only safe when they are unique across all configured accounts.

## Safety

- Require explicit confirmation before `send`, `mark-read`, or `move`.
- Prefer `compose` over `send` when the user wants a reviewable draft.
- Expect macOS privacy prompts the first time the script controls Mail.app. If automation is denied, guide the user to `System Settings > Privacy & Security > Automation`.

## Resources

- `scripts/mail_app_mailbox.py`: local CLI wrapper around AppleScript.
- `references/setup.md`: how to add Outlook/Exchange accounts and grant automation permissions.
- `references/notes.md`: implementation notes, limits, and when to prefer this skill over Graph.

## Validation

- Run `python3 scripts/mail_app_mailbox.py --help` after edits.
- Run `accounts` and `mailboxes` to verify AppleScript access before using message-mutating commands.
- If mailbox resolution fails, rerun `mailboxes` and pass the full path instead of a short name.
