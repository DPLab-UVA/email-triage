# email-triage

I get around fifty emails a day. The real problem is not just volume. The problem is interruption.

If Outlook notifies me for all fifty, my flow gets broken fifty times. But if I turn notifications off completely, I still end up checking anyway, because a few of those emails really do matter. So the actual job is not "show me all email" and not "hide all email." The job is:

- keep the actually important ones in front of me
- stop noisy mail from interrupting me
- put the rest somewhere I can review later, on my own schedule

This repo is the current best version of that idea for my setup.

## Why This Exists

My university runs on Outlook. That matters, because Outlook is not a very friendly ecosystem if you want fine-grained local automation.

If you are on Gmail, or you only get a handful of emails a day, you probably do not need this. A few filters and some discipline are enough.

If you are deep inside an Outlook-heavy university or enterprise workflow, and you want something smarter than "all notifications on" or "all notifications off," then this starts to make sense.

The core goal is simple:

- important mail should stay in `Inbox` and be allowed to interrupt me
- unimportant mail should not notify me
- low-priority mail should be moved into `Night Review`
- when something clearly needs a reply, the system should prepare a real Outlook draft so I can just send it, edit it, or delete it

## What I Tried Before Landing Here

This repo is not the first attempt.

I tried:

- direct Outlook Web DOM automation
- a Chrome extension
- a Mail.app route on macOS
- more local-client style workflows

All of those could do pieces of the job, but none felt stable enough as the main path.

What ended up being the most mature setup was:

- Outlook Web as the mail surface
- browser automation as the control layer
- local rules plus LLM judgment as the triage policy
- a dedicated `Night Review` folder as the low-priority holding area

That is what this repo implements.

## What The System Does

At a high level, it watches Outlook Web and makes one of three decisions for newly seen mail:

- `important_notify`
  Keep it in `Inbox`. If it looks reply-worthy, prepare a real Outlook draft.
- `important_action`
  Keep it in `Inbox`, but do not draft a reply if the right action is something else, such as approving an expense workflow.
- `night_digest`
  Mark it read and move it into `Night Review` so it stops interrupting me.

Then later:

- at night, it reminds me to check `Night Review`
- after I finish reviewing, I can move those messages back to `Inbox`
- if I forget to review them, they can stay there instead of being silently lost

## Important Constraint

Important does not mean reply-worthy.

That distinction matters a lot.

Examples:

- a security alert can be important but should not get a reply draft
- a Google Flights alert can be important but should not get a reply draft
- a real human thread about hiring, reimbursement, logistics, or a research task might deserve both attention and a prepared draft

The system is built around that distinction.

## Assumptions And Prerequisites

This setup assumes a fairly specific local environment.

You should expect to need:

- macOS
- Outlook Web working in Chrome
- the right Outlook login already alive in the browser profile the automation uses
- `tmux`
- `bun`
- the local gstack browser tooling
- the relevant Codex/browser skills installed

In practice, this repo was developed alongside local skills and browser tooling such as:

- Atlas, as a visible browser/session holder when that route is useful
- gstack browse, as the more practical page-control layer
- local Codex skills that help drive browser and mail workflows on this machine

This is not meant to be plug-and-play for a random laptop. It is a personal system first.

## What It Is Good At

- reducing pointless Outlook interruptions
- separating "important" from "later"
- keeping `Pinned` or otherwise user-signaled mail out of the automated move path
- preparing drafts for human threads that actually look like they need a response
- handling some special workflows differently from normal reply logic

## What It Is Not Good At

- being a general-purpose Outlook product
- working without browser/session context
- promising API-level stability from Outlook Web DOM behavior
- safely running multiple browser-writing automations on the same Outlook tab at the same time

If another human or another automation is actively driving the same Outlook session, things can get weird. This system works best when it is the only thing touching that controlled Outlook tab.

## Why Browser-First Instead Of API-First

The short version is: because Outlook in this environment is easier to automate through the browser than through a clean official integration path.

An API-first design would be cleaner in theory. In practice, for this exact university Outlook setup, browser control turned out to be the fastest path to something that actually worked end to end.

So this repo is unapologetically pragmatic.

## Storage

Originally, most local runtime data lived in scattered `json` and `jsonl` files under `shared/`.

That worked fine for fast prototyping, but it is not a great long-term storage model because:

- it is annoying to query
- it is easy to fragment state across too many files
- it is harder to reason about history and feedback loops

So the project now also mirrors key runtime events and state into a local SQLite database:

- [`shared/email_triage.db`](/Users/tianhao/Downloads/email-triage/shared/email_triage.db)

The JSON and JSONL files still exist because they are simple and useful, but SQLite is the better foundation for the next version.

## How I Actually Use It

The intended workflow is:

1. Let the monitor watch Outlook Web.
2. Important mail stays in `Inbox`.
3. Low-priority mail gets moved into `Night Review`.
4. At some point at night, review `Night Review`.
5. If I am done, move those messages back to `Inbox`.
6. If I have not dealt with them yet, leave them there and let them carry over.

This matters because the system is trying to protect focus, not to hide information.

## Moving Night Review Back

If I have already checked `Night Review` and want the messages moved back to `Inbox`, I can do it explicitly with:

```bash
python3 /Users/tianhao/Downloads/email-triage/browser/outlook_night_review.py restore-now
```

If I want to restore everything currently visible in that folder:

```bash
python3 /Users/tianhao/Downloads/email-triage/browser/outlook_night_review.py restore-now --all-visible
```

If I want to restore only messages Outlook is currently showing as read:

```bash
python3 /Users/tianhao/Downloads/email-triage/browser/outlook_night_review.py restore-now --only-read
```

In practice, I often just tell Codex to do it.

## Main Moving Parts

If you need to read code, start here:

- [`browser/outlook_live_monitor.py`](/Users/tianhao/Downloads/email-triage/browser/outlook_live_monitor.py)
- [`browser/outlook_recent_triage.py`](/Users/tianhao/Downloads/email-triage/browser/outlook_recent_triage.py)
- [`browser/outlook_apply_triage.py`](/Users/tianhao/Downloads/email-triage/browser/outlook_apply_triage.py)
- [`browser/outlook_draft_helper.py`](/Users/tianhao/Downloads/email-triage/browser/outlook_draft_helper.py)
- [`browser/outlook_night_review.py`](/Users/tianhao/Downloads/email-triage/browser/outlook_night_review.py)
- [`shared/triage_engine.py`](/Users/tianhao/Downloads/email-triage/shared/triage_engine.py)
- [`shared/default_rules.json`](/Users/tianhao/Downloads/email-triage/shared/default_rules.json)
- [`shared/sqlite_store.py`](/Users/tianhao/Downloads/email-triage/shared/sqlite_store.py)

## Start And Stop

Start the monitor:

```bash
/Users/tianhao/Downloads/email-triage/browser/outlook_monitor_tmux_ctl.sh start
```

Check status:

```bash
/Users/tianhao/Downloads/email-triage/browser/outlook_monitor_tmux_ctl.sh status
```

See logs:

```bash
/Users/tianhao/Downloads/email-triage/browser/outlook_monitor_tmux_ctl.sh logs
```

Stop it:

```bash
/Users/tianhao/Downloads/email-triage/browser/outlook_monitor_tmux_ctl.sh stop
```

## Design Philosophy

- Rules should be broad, not brittle.
- Final judgment should come from understanding the actual email, not from isolated keywords.
- Automated mail should almost never trigger a reply draft.
- The system should optimize for preserving focus, not for maximizing automation theater.
- If a message is important but not actionable, keep it visible and do not invent a reply.

## Known Rough Edges

- Outlook Web DOM is still Outlook Web DOM. It drifts.
- Browser actions still need careful serialization.
- Special workflows such as Workday approvals may still depend on the real browser session and SSO state.
- This is a strong personal tool, not yet a clean reusable product.

## Privacy

This repo touches real mail. Treat the runtime files accordingly.

Even if source code is public, the live data under `shared/` can contain sensitive metadata, message text, and learned style artifacts. Review `.gitignore` and the SQLite contents before sharing anything wider.
