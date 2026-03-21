# Mail.app Setup For Outlook Or Exchange

Use this setup when Microsoft Graph is blocked by tenant policy or when local macOS automation is simpler.

## 1. Add the mailbox to macOS Mail

Use one of these entry points:

- `Mail.app` -> `Add Account`
- `System Settings` -> `Internet Accounts`

For school or enterprise Outlook mail, choose the Microsoft Exchange or Microsoft 365 flow that matches what macOS presents on your version.

Complete sign-in with the school account and make sure Mail sync finishes before trying automation.

## 2. Grant automation permission

The first time the bundled script talks to Mail.app, macOS may ask whether Terminal or Codex can control Mail. Allow it.

If you denied it earlier, reopen the permission in:

- `System Settings` -> `Privacy & Security` -> `Automation`

Enable control for the app that is running the script.

## 3. Smoke test

Run:

```bash
python3 scripts/mail_app_mailbox.py accounts
python3 scripts/mail_app_mailbox.py mailboxes
```

Then pick the exact mailbox path from `mailboxes` and run:

```bash
python3 scripts/mail_app_mailbox.py list --mailbox "Your Account/INBOX" --limit 10
```

## 4. Common operations

Read a message:

```bash
python3 scripts/mail_app_mailbox.py read --mailbox "Your Account/INBOX" --id 12345
```

Create a draft:

```bash
python3 scripts/mail_app_mailbox.py compose --account "Your Account" --to someone@example.com --subject "Draft" --body "Hello"
```

Send immediately:

```bash
python3 scripts/mail_app_mailbox.py send --account "Your Account" --to someone@example.com --subject "Hello" --body "World"
```

Mark as read:

```bash
python3 scripts/mail_app_mailbox.py mark-read --mailbox "Your Account/INBOX" --id 12345
```

Move a message:

```bash
python3 scripts/mail_app_mailbox.py move --mailbox "Your Account/INBOX" --id 12345 --destination "Your Account/Archive"
```

## Sources

- [Add email accounts in Mail on Mac](https://support.apple.com/guide/mail/add-email-accounts-mail35803/mac)
- Local scripting dictionary from `sdef /System/Applications/Mail.app`
