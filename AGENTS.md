# AGENTS.md

## Scope

`email-triage` is a local-first Outlook automation workspace. It spans several
surfaces at once:

- `browser/`: the current browser-first control path
- `mail-app/`: local Mail.app helpers
- `chrome-extension/`: extension experiments
- `outlook-addin/`: Outlook add-in experiments
- `shared/`: rules, schemas, and triage logic shared across surfaces

## What reviewers should understand first

- This is stateful automation against a live mailbox, not a toy parser repo.
- Safety and idempotence matter more than feature count.
- "Important" and "reply-worthy" are intentionally separate concepts in this
  project.

## Review focus

- Treat accidental mail movement, accidental read-state changes, accidental
  draft creation, or anything that could hide or destroy user intent as
  high-severity issues.
- Flag flows that could run concurrently against the same Outlook session or
  tab without coordination.
- Flag any path that could send mail automatically when the intended behavior
  is only to draft or stage a reply.
- Check that pinned mail, Inbox retention rules, and `Night Review` behavior
  stay aligned with the documented policy.
- Flag hardcoded local secrets, browser profile assumptions, cookies, access
  tokens, or account-specific IDs.
- When code changes triage categories or LLM schemas in `shared/`, make sure
  the browser and mail surfaces still agree on those contracts.

## Validation expectations

- Prefer targeted validation on the touched surface instead of broad rewrites.
- For browser changes, review the corresponding workflow/helper in `browser/`.
- For extension or add-in changes, check the adjacent manifest and UI files as
  part of the same review.
