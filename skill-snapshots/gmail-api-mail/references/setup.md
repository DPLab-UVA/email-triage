# Gmail API Setup

Use this flow when the user wants Codex to control Gmail through the official Gmail API.

## Files

- Credentials JSON:
  `/Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/gmail-api-mail/state/credentials.json`
- Token cache:
  `/Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/gmail-api-mail/state/gmail_token.json`

## Steps

1. Create or choose a Google Cloud project.
2. Enable the Gmail API for that project.
3. Configure the OAuth consent screen.
4. Create an OAuth client ID of type `Desktop app`.
5. Download the OAuth client JSON and save it as:
   `/Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/gmail-api-mail/state/credentials.json`
6. Run:
   `/Users/tianhao/Library/CloudStorage/Dropbox/notes/skills/gmail-api-mail/scripts/gmail_api_mail auth --mode triage`
7. Complete the browser login and consent flow once.

## Notes

- `readonly` mode requests read-only Gmail access.
- `triage` mode requests `gmail.modify`, which supports reading mail, drafting, sending, and label changes.
- If the token was created with insufficient scopes, rerun `auth` with a broader mode.
