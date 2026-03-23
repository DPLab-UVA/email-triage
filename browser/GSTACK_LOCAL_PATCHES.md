# Local Gstack Patches

These are local changes in `~/gstack` that the repo depends on for the current Outlook-first workflow.

## Patched Files

- `browse/src/cli.ts`
  - changed non-Windows server startup to `nohup ... &`
  - writes server logs to `browse-server.log`
  - surfaces log tail on startup timeout
- `browse/src/write-commands.ts`
  - added `--profile` support to `cookie-import-browser ... --domain ...`
  - this is required because the active Chrome login state is in `Profile 1`, not `Default`
- `browse/src/commands.ts`
  - updated help text for `cookie-import-browser [--profile p]`

## Why This Exists

The raw `gstack-browse` CLI does not yet behave reliably enough in this environment when Outlook Web needs imported browser cookies.

The project-local workaround is:

- stable tmux bridge: `browser/gstack_browse_bridge.py`
- higher-level Outlook wrapper: `browser/outlook_web_workflow.py`

The local gstack patches above are still necessary so the wrapper can bootstrap Outlook Web from the correct Chrome profile.
