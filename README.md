# email-triage

Browser-first Outlook triage for this Mac. It watches Outlook Web, decides which messages matter, moves low-priority mail into `Night Review`, opens real Outlook reply drafts for threads that need a response, and keeps a local audit trail so the policy can keep improving.

This repo is opinionated and personal. The current workflow is tuned for Tianhao's Outlook habits, not for a generic team rollout.

## What It Does

- Monitors Outlook Web from a controlled browser session.
- Keeps important mail in `Inbox` and shows a macOS notification.
- Moves low-priority mail into `Night Review` and marks those messages read before moving.
- Opens real Outlook reply drafts for important human threads that likely need a response.
- Avoids drafting replies for automated mail, system alerts, newsletters, editorial spam, and similar bulk mail.
- Queues special actions such as Workday expense approvals instead of replying.
- Tracks `Night Review` state so the queue can be revisited and later restored to `Inbox`.
- Learns triage and draft behavior from local rules, sent mail, and explicit corrections over time.

## Current Workflow

1. The live monitor watches the top of `Inbox`.
2. Each newly seen message is triaged into one of three buckets:
   - `important_notify`
   - `important_action`
   - `night_digest`
3. `important_notify` stays in `Inbox`. If the message needs a reply, the system opens a real Outlook reply draft.
4. `important_action` stays in `Inbox` and may trigger a narrow automation instead of a reply.
5. `night_digest` is moved into `Night Review` and marked read first.
6. At night, the system reminds the user to check `Night Review`.
7. The next morning, carried-over Night Review items can be restored to `Inbox`.

The important distinction is:

- Important does not always mean reply.
- Automated mail can still be important.
- Reply drafts should only be opened for human threads that look like they genuinely need a response.

## Main Components

- [`browser/outlook_live_monitor.py`](/Users/tianhao/Downloads/email-triage/browser/outlook_live_monitor.py)
  Continuous monitor and policy executor.
- [`browser/outlook_recent_triage.py`](/Users/tianhao/Downloads/email-triage/browser/outlook_recent_triage.py)
  Structured extraction and triage of recent visible Outlook messages.
- [`browser/outlook_apply_triage.py`](/Users/tianhao/Downloads/email-triage/browser/outlook_apply_triage.py)
  Message movement and mark-read logic.
- [`browser/outlook_draft_helper.py`](/Users/tianhao/Downloads/email-triage/browser/outlook_draft_helper.py)
  Reply-draft generation and injection into Outlook Web.
- [`browser/outlook_auto_actions.py`](/Users/tianhao/Downloads/email-triage/browser/outlook_auto_actions.py)
  Narrow non-reply actions such as expense-approval follow-through.
- [`browser/outlook_night_review.py`](/Users/tianhao/Downloads/email-triage/browser/outlook_night_review.py)
  Night Review queue state, reminder, and restore logic.
- [`shared/default_rules.json`](/Users/tianhao/Downloads/email-triage/shared/default_rules.json)
  Policy, thresholds, hours, and LLM settings.
- [`shared/triage_engine.py`](/Users/tianhao/Downloads/email-triage/shared/triage_engine.py)
  Rule-guided triage plus LLM escalation.

## Repo Layout

- `browser/`
  Outlook Web control, monitor, drafts, and automation.
- `shared/`
  Rules, logs, JSON state, caches, and learned profiles.
- `chrome-extension/`
  Earlier DOM-capture tooling used during rapid prototyping.
- `mail-app/`
  Older Mail.app experiments and local helpers.
- `docs/`
  One-off generated documents and workflow artifacts.
- `skill-snapshots/`
  Snapshots of related local skills for archival/reference.

## Setup Assumptions

This repo assumes all of the following:

- macOS
- Outlook Web already works in Google Chrome
- the active Outlook login is in Chrome `Profile 1`
- `tmux` is installed
- `bun` is installed at `~/.bun/bin/bun`
- local browser automation is available through the gstack browse bridge

The monitor controls a real logged-in browser session. Do not assume it is safe to run multiple browser-writing jobs at the same time.

## Start and Stop

Start the live monitor:

```bash
/Users/tianhao/Downloads/email-triage/browser/outlook_monitor_tmux_ctl.sh start
```

Check status:

```bash
/Users/tianhao/Downloads/email-triage/browser/outlook_monitor_tmux_ctl.sh status
```

Tail logs:

```bash
/Users/tianhao/Downloads/email-triage/browser/outlook_monitor_tmux_ctl.sh logs
```

Stop it:

```bash
/Users/tianhao/Downloads/email-triage/browser/outlook_monitor_tmux_ctl.sh stop
```

## Night Review

Low-priority mail goes into the Outlook folder `Night Review`.

By default, the system:

- reminds the user at night
- keeps unread carry-over items there
- restores the queue to `Inbox` the next morning if the relevant carried-over messages are ready to come back

If the user finishes reviewing earlier and wants everything moved back immediately, run:

```bash
python3 /Users/tianhao/Downloads/email-triage/browser/outlook_night_review.py restore-now
```

If you want to restore every currently visible message in the folder, not just tracked pending items:

```bash
python3 /Users/tianhao/Downloads/email-triage/browser/outlook_night_review.py restore-now --all-visible
```

If you want the command to restore only messages Outlook still shows as read:

```bash
python3 /Users/tianhao/Downloads/email-triage/browser/outlook_night_review.py restore-now --only-read
```

This is the intended operator workflow:

- the system moves low-priority mail into `Night Review`
- the user checks that folder when convenient
- after review, either the user tells Codex to move everything back, or runs `restore-now`

## Important Local Files

- [`shared/default_rules.json`](/Users/tianhao/Downloads/email-triage/shared/default_rules.json)
  The main policy file.
- [`shared/outlook_monitor_state.json`](/Users/tianhao/Downloads/email-triage/shared/outlook_monitor_state.json)
  Live monitor state.
- [`shared/outlook_monitor_events.jsonl`](/Users/tianhao/Downloads/email-triage/shared/outlook_monitor_events.jsonl)
  Live monitor event log.
- [`shared/outlook_night_review_state.json`](/Users/tianhao/Downloads/email-triage/shared/outlook_night_review_state.json)
  Night Review queue state.
- [`shared/outlook_night_review_events.jsonl`](/Users/tianhao/Downloads/email-triage/shared/outlook_night_review_events.jsonl)
  Night Review reminder and restore log.
- [`shared/outlook_monitor.stdout.log`](/Users/tianhao/Downloads/email-triage/shared/outlook_monitor.stdout.log)
  Background monitor stdout.
- [`shared/outlook_monitor.stderr.log`](/Users/tianhao/Downloads/email-triage/shared/outlook_monitor.stderr.log)
  Background monitor stderr.

## Design Principles

- Rules should stay broad. Final decisions should come from understanding the specific email.
- Do not overfit to isolated keywords.
- Personalized, credible, actionable human threads deserve more weight than generic outreach.
- Automated messages almost never need reply drafts.
- Important notifications and reply-worthy threads are different things.
- `Pinned` is a user override and should not be auto-moved.
- Browser actions must be serialized. Competing tab automation will make the system unstable.

## Known Constraints

- The system is Outlook Web first. It is not yet a clean Outlook API product.
- Outlook DOM and menu behavior can drift, so movement actions still need defensive retries.
- Workday-style approval links may still require the real browser session or SSO context.
- If another tool or human is actively driving the same Outlook tab, the monitor can interfere.

## Privacy

This repo intentionally keeps private working state local by default. Logs, caches, samples, and learned profiles under `shared/` may contain sensitive mail metadata or text. Review `.gitignore` carefully before publishing anything beyond source code.
