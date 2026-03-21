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
- Secondary capture path:
  `chrome-extension/`
- Fallback API path:
  `skill-snapshots/gmail-api-mail/`
- Fallback local client path:
  `mail-app/` and `skill-snapshots/mail-app-mailbox/`

## Immediate Next Steps

1. Verify whether `gstack-browse` can open Gmail Web and Outlook Web with the user's existing browser session.
2. If not logged in, test cookie import or another low-friction session bootstrap path.
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
- Gmail Web opens reliably, but the gstack browser session does not inherit Google login state by default.
- Direct cookie import from Chrome to `mail.google.com` imports at least one cookie, but not enough to bypass the Google sign-in page.
- Outlook Web is more promising:
  - direct Chrome cookie import is available
  - after import, navigation can remain on `https://outlook.office.com/mail/`
- Current blocker on Outlook Web is tool stability:
  - once on the page, `text` or `snapshot -i` can cause `gstack-browse` to lose its server connection and restart
- This means the browser-first direction is still correct, but the next task is to stabilize `gstack-browse` on Outlook Web before building extraction and drafting on top of it.

## Short-Term Success Criteria

- Open Gmail Web or Outlook Web through `gstack-browse`
- Read one real message reliably
- Insert one reply draft reliably
- Detect one sent outcome reliably

## Risks

- Headless browser sessions may not share Chrome login state automatically.
- Webmail DOM can drift, so selectors must be robust.
- Send-tracking must avoid false positives when the user discards or rewrites heavily.
