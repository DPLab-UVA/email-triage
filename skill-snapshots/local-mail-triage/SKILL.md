---
name: local-mail-triage
description: Use local macOS mail tooling to triage email, inspect recent Outlook Web captures, review tentative labels, poll Mail.app inboxes, and create draft replies through the user's existing local setup. Trigger this when Codex should read mail, summarize triage state, draft a reply, or operate the local email triage prototype on this Mac.
---

# Local Mail Triage

## Overview

Use this skill when the user wants Codex to work with the local email triage prototype on this Mac. It is the orchestration layer above the existing `Mail.app` and Outlook Web capture tooling.

## Quick Start

1. Check local status:
   `python3 scripts/local_mail_bridge.py status`
2. Review recent tentative labels:
   `python3 scripts/local_mail_bridge.py queue-summary`
3. Build the fast header-first review queue:
   `python3 scripts/local_mail_bridge.py fast-pipeline`
4. Review recent Outlook Web captures:
   `python3 scripts/local_mail_bridge.py captures-tail --limit 10`
5. Poll one Mail.app mailbox:
   `python3 scripts/local_mail_bridge.py poll-mail --mailbox "Exchange/Inbox" --limit 10`
6. Draft a reply for the selected Mail.app message:
   `python3 scripts/local_mail_bridge.py draft-selected`
7. Draft a reply for one known mailbox/id pair without changing the current Mail.app selection:
   `python3 scripts/local_mail_bridge.py draft-message --mailbox "Exchange/Inbox" --id 595251`
8. For a selected or specified journal review invitation in Mail.app, open the best unavailable/decline URL:
   `python3 scripts/local_mail_bridge.py auto-decline-selected --open --json`
   `python3 scripts/local_mail_bridge.py auto-decline-selected --mailbox "Exchange/Inbox" --message-id 595251 --open --json`
9. Run one background-style cycle:
   `python3 scripts/local_mail_bridge.py auto-run-once --mailbox "Exchange/Inbox" --mailbox "Google/INBOX"`
10. Reconcile recent sent mail against logged draft suggestions:
   `python3 scripts/local_mail_bridge.py reconcile-sent --mailbox "Exchange/Sent Items" --limit 20`

## Scope

- Read project status for the local triage prototype.
- Summarize recent Outlook Web captures already ingested locally.
- Summarize the current prelabel review queue.
- Build a fast header-first review queue from stable local snapshots.
- Run Mail.app triage polling for one mailbox.
- Create a draft reply for the currently selected Mail.app message or a known mailbox/id pair.
- Open the best unavailable/decline URL from a selected Mail.app review invitation or a known mailbox/id pair.
- Run one background-style cycle that polls inboxes, queues low-priority mail for the nightly digest, auto-declines journal review invites, drafts replies for eligible important mail, and reconciles sent-mail feedback.
- Reconcile sent mail against previous draft suggestions to learn whether the user sent as-is or modified the draft.

## Guardrails

- Prefer draft creation over send.
- Treat Outlook Web captures as noisy until reviewed.
- Treat Mail.app background reads as best-effort; large aggregate views can still stall AppleScript.
- Do not send mail automatically unless the user explicitly asks.

## Resources

- `scripts/local_mail_bridge.py`: stable entrypoint for this local setup.
- Project root:
  `/Users/tianhao/Downloads/email-triage-lab`
- Mail.app triage backend:
  `/Users/tianhao/Downloads/email-triage-lab/mail-app/mail_app_triage.py`
- Review queue:
  `/Users/tianhao/Downloads/email-triage-lab/shared/prelabeled_review_queue.jsonl`
- Draft suggestion log:
  `/Users/tianhao/Downloads/email-triage-lab/shared/draft_suggestions.jsonl`
- Draft feedback log:
  `/Users/tianhao/Downloads/email-triage-lab/shared/draft_feedback.jsonl`
- Auto-action log:
  `/Users/tianhao/Downloads/email-triage-lab/shared/auto_action_log.jsonl`

## Validation

- Run `python3 scripts/local_mail_bridge.py status` after edits.
- Run `python3 scripts/local_mail_bridge.py queue-summary` to verify data paths.
- Run `python3 scripts/local_mail_bridge.py --help` if command wiring changes.
