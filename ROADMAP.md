# Local Mail Triage Roadmap

## Goal

Build one local Codex skill that can:

- read mail from the user's Mac through Mail.app
- ingest and learn from Outlook Web captures
- suppress low-value notifications
- draft likely replies in the user's style
- later automate background polling and notification delivery

## Current Assets

- `mail-app/mail_app_triage.py`
  Mail.app triage and draft pipeline
- `shared/triage_engine.py`
  Rule- and example-based classifier
- `shared/triage_server.py`
  Local ingest server for Outlook Web captures
- `shared/captured_outlook_reports.jsonl`
  Captured Outlook Web messages
- `shared/prelabeled_review_queue.jsonl`
  First-pass review queue for user correction
- `chrome-extension/`
  Outlook Web capture prototype

## Phase 1: Local Skill Wrapper

- Create one skill that points Codex at the local project paths.
- Add one wrapper CLI so the skill has a stable entrypoint.
- Support:
  - status
  - recent Outlook capture summary
  - prelabel queue summary
  - Mail.app poll
  - Mail.app draft for selected message

## Phase 2: Correction Loop

- Turn the review queue into a proper correction dataset.
- Add commands to mark a message `important` or `not_important`.
- Promote corrected examples into `shared/example_labeled_emails.jsonl`.
- Tighten rules around research mail, helpdesk, travel, newsletters, and marketing.

## Phase 3: Reply Personalization

- Mine a small sample of sent mail to infer reply style.
- Add templates for:
  - scheduling
  - helpdesk / ops
  - conference review
  - faculty / collaborator follow-up
- Default to draft creation, not auto-send.
- Log every draft suggestion and compare later sent mail to learn:
  - sent as-is
  - sent after edits

## Phase 4: Background Automation

- Run the triage server persistently.
- Poll selected Mail.app inboxes in the background.
- Queue low-priority mail into one nightly digest instead of notifying immediately.
- Auto-decline journal review invitations by opening the best `unavailable` link.
- Notify only for `important` mail.
- Auto-draft replies only for reply-eligible important mail, not `noreply` notifications.
- Keep local logs of:
  - decisions
  - draft suggestions
  - sent-mail feedback
  - auto actions

## Phase 5: Safer Write Actions

- Expose explicit draft / move / mark-read actions through the wrapper.
- Require clear user intent before send or mailbox mutation.
- Add a dry-run mode for risky actions.

## Open Risks

- Mail.app AppleScript becomes unreliable when Mail is busy or large aggregate views are open.
- Mail.app mailbox listing can currently time out even for small inbox windows; the new runner now fails fast instead of hanging forever, but deeper stabilization is still needed.
- Direct Mail database access needs macOS `Full Disk Access`.
- Outlook Web DOM extraction still needs cleanup to reduce UI-noise captures.
- User style learning should stay conservative until enough corrected examples exist.
