# Browser-First Plan

## Goal

Use browser automation as the primary execution path for email triage and drafting.

Keep Gmail API and Mail.app as fallback paths, not the main path.

## Product Goal

Build one local workflow that can:

- monitor Gmail Web or Outlook Web
- classify incoming mail with local rules and examples
- suppress low-priority interruptions
- queue low-priority mail into a nightly digest
- draft replies for important human messages
- record whether the user sent the draft as-is or after edits

## Current Decision

- Primary execution path:
  `gstack-browse`
- Visible session helper:
  `browser/atlas_outlook_helper.py`
- Secondary capture path:
  `chrome-extension/`
- Fallback API path:
  `skill-snapshots/gmail-api-mail/`
- Fallback local client path:
  `mail-app/` and `skill-snapshots/mail-app-mailbox/`

## Immediate Next Steps

1. Keep `gstack-browse` as the primary Outlook Web control path.
2. Reuse the project-local bridge and Outlook workflow wrapper instead of raw ad hoc CLI calls.
3. Build a browser-side extractor for:
   - subject
   - sender
   - body text
   - thread metadata
   - compose/reply box state
4. Reuse `shared/triage_engine.py` for browser-side classification.
5. Add browser-side reply draft insertion.
6. Add browser-side send tracking:
   - draft created
   - sent as-is
   - sent after edits

## Current Findings (2026-03-21)

- `gstack-browse` is installed and runnable from:
  `~/.codex/skills/gstack/browse/dist/browse`
- Gmail Web still does not inherit login state by default, so Gmail is not the active path.
- Outlook Web is now the active path.
- The raw `gstack-browse` CLI server lifecycle is still flaky in this environment:
  - it can restart instead of reconnecting
  - state files can be replaced unexpectedly
- A project-local tmux-hosted bridge fixes the practical stability problem:
  - file: `browser/gstack_browse_bridge.py`
  - state file: `.gstack/bridge-browse.json`
- Chrome profile selection mattered:
  - the machine's recent Chrome profile is `Profile 1`, not `Default`
  - `cookie-import-browser` needed `--profile` support to import the right Outlook cookies
- After importing cookies from Chrome `Profile 1`, Outlook Web now stays logged in and readable:
  - current URL can remain on real message pages under `https://outlook.office.com/mail/...`
  - `text` and `snapshot -i` both work through the bridge
- A higher-level Outlook wrapper now exists:
  - file: `browser/outlook_web_workflow.py`
  - commands:
    - `bootstrap`
    - `status`
    - `current-view`
    - `capture-current`
- A real Outlook move-to-folder action now works end to end:
  - target folder: `Night Review`
  - verified by moving one low-risk journal-invitation email out of Inbox
  - action-layer script: `browser/outlook_apply_triage.py`
- A live poller now exists for Outlook Web:
  - monitor script: `browser/outlook_live_monitor.py`
  - state file: `shared/outlook_monitor_state.json`
  - event log: `shared/outlook_monitor_events.jsonl`
  - launchd wrapper: `launchd/outlook_monitor_ctl.sh`
  - tmux wrapper: `browser/outlook_monitor_tmux_ctl.sh`
- A Night Review queue manager now exists:
  - helper script: `browser/outlook_night_review.py`
  - state file: `shared/outlook_night_review_state.json`
  - event log: `shared/outlook_night_review_events.jsonl`
  - supports:
    - bootstrapping existing `Night Review` mail into pending state
    - one nightly reminder for pending low-priority mail
    - next-morning restore to `Inbox` if the carried-over Night Review items are all read
- A draft helper now exists for Outlook Web:
  - helper script: `browser/outlook_draft_helper.py`
  - suggestion log: `shared/outlook_draft_suggestions.jsonl`
  - feedback log: `shared/outlook_draft_feedback.jsonl`
  - supports selected-message extraction, folder-level draft suggestion, reply draft injection, explicit feedback logging, and send-time feedback logging
- A lightweight style learner now exists for Outlook replies:
  - helper script: `browser/outlook_reply_style.py`
  - reads recent `Sent Items` previews
  - writes a local reply-style profile used to make drafts shorter and less AI-like
- Atlas is now confirmed as a live visible Outlook session holder:
  - the Atlas app already has logged-in Outlook tabs
  - helper file: `browser/atlas_outlook_helper.py`
  - current supported actions:
    - `tabs`
    - `focus-outlook`
    - `reload-outlook`
    - `open-outlook`
- Atlas is useful immediately for visible tab/session operations, but not yet as a reusable cookie source for `gstack-browse`:
  - Outlook cookies are present in the active Atlas profile
  - they are encrypted
  - the Atlas Safe Storage keychain service name has not been identified yet

## Short-Term Success Criteria

- Open Outlook Web through `gstack-browse`
- Read one real message reliably
- Insert one reply draft reliably
- Detect one sent outcome reliably

## Risks

- Headless browser sessions may not share Chrome login state automatically.
- Webmail DOM can drift, so selectors must be robust.
- Send-tracking must avoid false positives when the user discards or rewrites heavily.
- Night Review restore is driven by Outlook's read/unread state, so if a message stays unread it will remain queued instead of being restored.

## Operational Rules Learned (2026-03-22)

- Do not run parallel actions against the same live Outlook page.
  Serial page operations are slower, but much more reliable.
- Stop the live monitor before any manual thread inspection or manual drafting.
  Otherwise the monitor can navigate the page away from the thread or draft being inspected.
- Prefer visible-list scrolling over Outlook Web search for deep thread retrieval.
  Search is currently less reliable than scrolling and matching stable subjects.
- Treat Outlook `dom_id` values as short-lived.
  Re-find the row in the current visible list before clicking; do not assume an old `dom_id` will still work after scrolling or folder changes.
- Distinguish three states, not two:
  `important + needs_notify`, `important + needs_reply`, and `not_important`.
  Important automatic mail should notify if useful, but should not generate a reply draft.
- Never auto-draft replies for automated, system, or mass-mail messages.
  This includes alerts, newsletters, conference system mail, flight trackers, scholar updates, generic invitations, and other no-reply style traffic.
- Do not overfit triage rules to exact subjects.
  Rules should encode broad principles, while per-message judgment should come from Codex using the actual thread text.
- For HR / hiring / administrative tasks, inspect `Sent Items` as well as `Inbox`.
  The actionable context often lives in sent threads rather than new inbound mail.
- For document-heavy tasks, generate the artifact locally first, then return to the live browser only for the final reply step.
  This keeps browser automation focused on the narrow part it is good at.
- Do not rely on selected-row state after a reply box is already open.
  If the compose box is visible, inspect the compose DOM directly instead of assuming the message list still exposes a selected row.
- Keep long-running dependencies out of the repo when possible.
  Temporary tool installs, like `docx`, should live in a disposable location instead of polluting the project tree.
- Pinned messages are effectively user overrides.
  They should never be auto-moved or treated as disposable low-priority mail.
- Night Review state should tolerate transient visibility misses.
  One missed scan is not enough evidence that a message disappeared.
