# Social Post Plan

## Goal

Turn the existing browser-first automation stack into a local social posting assistant.

The first version should prepare posts safely:

- open the platform with the user's existing browser login
- open the compose UI
- inject draft text
- stop before the final publish click

## Scope

Platforms:

- LinkedIn
- X
- Xiaohongshu

Execution path:

- separate `gstack-browse` session from Outlook
- file: `browser/social_post_workflow.py`
- separate bridge session/state/log:
  - tmux session: `email-triage-social-browse`
  - state: `.gstack/bridge-browse-social.json`
  - log: `.gstack/bridge-browse-social-server.log`
- visible Atlas path for already-logged-in sessions:
  - file: `browser/atlas_social_helper.py`

## Why Separate It

The Outlook monitor already uses `browser/gstack_browse_bridge.py` as a long-lived execution path.

If social posting reused that same browser session, it would steal the active tab and interfere with live email monitoring.

So the social path must use its own browser bridge session.

## Current Status (2026-03-21)

- Multi-session bridge support now exists in `browser/gstack_browse_bridge.py`
- Social posting workflow exists in `browser/social_post_workflow.py`
- Visible Atlas social helper exists in `browser/atlas_social_helper.py`
- Current commands:
  - `bootstrap`
  - `status`
  - `open-compose`
  - `draft`
- Default browser source:
  - `Chrome`
  - profile: `Profile 1`

## Current Findings

- LinkedIn cookies import works, but the current Chrome `Profile 1` session lands on the LinkedIn sign-in page.
- X cookies import works partially, but the current session does not produce a stable logged-in home page yet.
- Xiaohongshu cookies import works partially, but the current creator page still needs a cleaner logged-in/editor detection path.
- Atlas already holds live logged-in tabs for:
  - `X`
  - `LinkedIn`
  - regular `Xiaohongshu` browsing
- Atlas-visible draft injection is now verified for:
  - `X`
  - `LinkedIn`
- Xiaohongshu still needs a separate login on `creator.xiaohongshu.com`; the regular browse session on `www.xiaohongshu.com` is not enough for publishing.

So the code path is ready, but at least some platforms still need a live logged-in browser session before drafting can work end to end.

## Near-Term Steps

1. Stabilize login/session detection for all three platforms.
2. Keep the Atlas path as the fastest route for visible drafting on platforms where Atlas is already logged in.
3. Make `draft` write text reliably without publishing.
4. Add Xiaohongshu creator login support and then implement its draft injection.
5. Add optional local queue files for:
   - post ideas
   - pending drafts
   - approved-to-post items
6. Add a second-stage workflow:
   - generate candidate post from source material
   - prepare draft in platform UI
   - wait for user review

## Later Extensions

- publish after explicit approval
- schedule batches of posts
- learn platform-specific writing style
- repurpose email/news/research updates into platform-specific copy
