---
name: gmail-api-mail
description: Control Gmail through the official Gmail API from a local Python CLI on this Mac. Use when Codex should authenticate to Gmail, inspect labels, list or read messages, create draft replies, or send mail without relying on Chrome DOM scraping or Mail.app AppleScript.
---

# Gmail API Mail

## Overview

Use this skill when the mailbox is Gmail or Google Workspace mail and a stable API path is preferable to browser scraping or Mail.app automation.

This skill wraps the official Gmail API in a local CLI. It is the recommended route when:

- the user is willing to connect Gmail directly
- browser DOM automation is too fragile
- Mail.app background reads are timing out

## Quick Start

1. Read [references/setup.md](references/setup.md) and place the Google OAuth desktop-app credentials JSON at:
   `/Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/gmail-api-mail/state/credentials.json`
2. Authenticate once:
   `scripts/gmail_api_mail auth --mode triage`
3. Confirm the account:
   `scripts/gmail_api_mail status`
4. List recent inbox mail:
   `scripts/gmail_api_mail list --label INBOX --limit 10`
5. Read one message:
   `scripts/gmail_api_mail read --id <gmail-message-id>`
6. Create a new draft:
   `scripts/gmail_api_mail draft --to person@example.com --subject "..." --body "..."`
7. Create a reply draft for an existing message:
   `scripts/gmail_api_mail draft-reply --id <gmail-message-id> --body "..."`

## Scope

- Local OAuth for one Gmail or Google Workspace account
- Label listing
- Message listing and reading
- Draft creation
- Reply-draft creation in the original thread
- Explicit send when the user asks

## Guardrails

- Prefer `draft` or `draft-reply` over `send`.
- Use `--mode readonly` for read-only workflows and `--mode triage` when drafts or sends are needed.
- Start with polling, not Gmail push notifications. If push is needed later, read [references/api-notes.md](references/api-notes.md) first.
- Store credentials and tokens only in the local `state/` directory for this skill.

## Resources

- `scripts/gmail_api_mail.py`: Gmail API CLI
- `scripts/gmail_api_mail`: wrapper that runs the CLI inside the skill-local virtualenv
- [references/setup.md](references/setup.md): local Google Cloud setup flow
- [references/api-notes.md](references/api-notes.md): architecture and tradeoffs

## Validation

- Run `scripts/gmail_api_mail --help` after edits.
- Run `scripts/gmail_api_mail status` after authentication.
- Run `scripts/gmail_api_mail list --label INBOX --limit 3` to verify read access.
