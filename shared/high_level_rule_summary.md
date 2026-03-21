# High-Level Triage Rules

Generated from the current stable sample pool on 2026-03-19.

## Sample Status

- Stable unique items reviewed so far: about `55`
- Sources used:
  - `Mail.app` header snapshots from `Exchange/Inbox` top 20
  - `Mail.app` header snapshots from `Google/INBOX` top 20
  - deduped Outlook Web visible-list captures
- Target remains `100-200`, but deeper Mail.app pagination is still unreliable and needs more work.

## Proposed Big Rules

### 1. Default Important

Treat these as `important` unless a later user correction says otherwise:

- direct project / collaborator threads
- research computing or infrastructure operations
- tracked flight alerts
- Google Scholar reminders
- the UVA Engineering newsletter
- explicit deadlines or action-required admin mail
- helpdesk / ticket / repair threads
- security alerts and CI failure notifications

Typical examples:

- `Follow-up on Privsyn Project & Next Steps`
- `implementing the PrivSyn prototype on UVA Research Computing infrastructure`
- `Prices for your tracked flights to Hong Kong have changed`
- `Time to update your articles`
- `UVA Engineering Newsletter - March 19, 2026`
- `[SIGMOD 2026] URGENT: Please pre-register by the weekend`
- `CSHD-12091 dplab02 Repair and dplab07 Follow-up`
- `Security alert`
- `Run failed: CI - main`

### 2. Default Not Important

Treat these as `not_important` unless the user says they are personally high-priority:

- newsletters
- department-wide announcements
- general seminar / symposium / webinar / panel announcements
- marketing / promotion / early-bird pricing mail
- consumer service / finance / shipping / travel alerts
- submitted-review receipts
- congratulation threads with long quoted replies
- most SDS broadcasts, including talks and funding opportunities
- journal review invitations

Typical examples:

- `UVA Engineering Research Symposium (UVERS) 2026`
- `Agentic AI Summit 2026 - ... Early-Bird Prices Increasing Soon`
- `Your equipment is on its way`
- `Special pricing for Rocket Mortgage clients like you`
- `[TPDP 2026] Submitted review #104B`
- `Congratulations on ...`
- `New Funding Opportunity - $50,000 for Public Safety Innovations`
- `CEE Seminar: David Noyce (UW Madison)`
- `Invitation to review manuscript ...`

### 3. Likely Low-Priority But Keep Reviewable

These currently look lower-priority or preference-sensitive, but I do not want to suppress them too aggressively until you confirm:

- self-generated AI digests
- learning-community / course-discussion mail
- platform policy updates

Typical examples:

- `Time to update your articles`
- `AI 新闻摘要 - 2026-03-19`
- `最近刚开始看cs336，又看到一门叫CME295`
- `We’re updating our Terms of Service`

### 4. Borderline / Need Your Policy

These need your explicit preference because different users would classify them differently:

- research invitations
- funding opportunities
- internal faculty summaries
- volunteering / registrar / faculty-participation calls
- opportunities that are informational now but may matter later

Typical examples:

- `Invitation: NII Shonan Meeting on Exploring Responsible AI through Security and Privacy`
- `Announcing data.org - Activate AI Challenge`
- `Funds available to grow your network of external mentors`
- `New Funding Opportunity - $50,000 for Public Safety Innovations`
- `Final Exercises 2026 - Request for Faculty Participation`

## Current Working Policy

If a message appears to involve your active research, direct responsibility, infrastructure, security, or a concrete action deadline, it should notify and usually get a draft.

If a message is low-priority, it should not notify immediately; instead it should go into the nightly digest queue.

If a message is a journal review invitation, it should be marked low-priority and placed into an auto-decline queue rather than notifying immediately.
