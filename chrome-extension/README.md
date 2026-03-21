# Outlook Web Triage Prototype

This directory contains a best-effort Manifest V3 Chrome extension for Outlook Web.

What it does:

- Captures visible subject/body metadata from Outlook Web pages using DOM heuristics.
- Scores messages with a small local rule engine.
- Shows a floating triage panel and a popup summary.

What is stubbed:

- DOM selectors are brittle and may need adjustment for Outlook Web UI changes.
- Reply drafting is currently heuristic text only.
- No server-side AI model is wired in yet.
- No mail mutation actions are implemented.

Load it unpacked from Chrome by selecting this folder as the extension root.
