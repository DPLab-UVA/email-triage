# Gmail API Notes

## Why This Route

For Gmail accounts, the official Gmail API is usually more stable than:

- scraping Gmail or Outlook Web DOM
- driving Mail.app through AppleScript

## Recommended First Pass

Use polling plus local state:

- list recent `INBOX` messages every few minutes
- triage with local rules/examples
- create reply drafts for important human messages
- collect sent-mail feedback later

## Why Not Push First

Gmail push notifications are real, but they add extra setup:

- a Google Cloud Pub/Sub topic
- Gmail `users.watch`
- periodic renewal of the watch

That is a good second step, not the fastest first step.

## MCP Note

There is no special Gmail-only MCP requirement here. The simple architecture is:

1. official Gmail API
2. local Python CLI
3. Codex Skill on top

If needed later, the same CLI can be wrapped in a local MCP server.
