# Notes

This skill exists because local macOS automation avoids Microsoft Entra and Azure permissions entirely.

## Why this is useful

- School tenants often block `App registrations`, which prevents a self-service Graph integration.
- Mail.app is scriptable on macOS through AppleScript.
- Outlook and Exchange accounts can usually be synced into Mail.app even when Azure subscription access is unavailable.

## Practical limits

- This skill only works on macOS.
- The mailbox must already be present in Mail.app.
- The script uses Mail.app's local message identifiers for read, move, and mark operations. Always get them from the `list` command first.
- Mailbox selection is safest by full path, not short name.

## When to prefer this skill over the Graph skill

Prefer `mail-app-mailbox` when:

- The tenant blocks app registration.
- The user only needs local mailbox control on one Mac.
- Fast setup matters more than cloud portability.

Prefer `outlook-graph-mail` when:

- You can register or obtain a Microsoft Entra app.
- You need a more portable API-oriented integration.
- You want to evolve the integration into an MCP server later.
