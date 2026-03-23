#!/bin/zsh
set -euo pipefail

LABEL="com.emailtriage.outlook-monitor"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_PLIST="$ROOT/launchd/com.emailtriage.outlook-monitor.plist"
DEST_PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
TMP_PLIST="$(mktemp -t email-triage-monitor.XXXXXX.plist)"

mkdir -p "$HOME/Library/LaunchAgents"
trap 'rm -f "$TMP_PLIST"' EXIT

case "${1:-}" in
  install|start)
    sed "s#__REPO_ROOT__#$ROOT#g" "$SOURCE_PLIST" > "$TMP_PLIST"
    cp "$TMP_PLIST" "$DEST_PLIST"
    launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    launchctl bootstrap "$DOMAIN" "$DEST_PLIST"
    launchctl kickstart -k "$DOMAIN/$LABEL"
    echo "started $LABEL"
    ;;
  stop)
    launchctl bootout "$DOMAIN/$LABEL"
    echo "stopped $LABEL"
    ;;
  restart)
    "$0" stop || true
    "$0" start
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
    rm -f "$DEST_PLIST"
    echo "uninstalled $LABEL"
    ;;
  status)
    launchctl print "$DOMAIN/$LABEL"
    ;;
  *)
    echo "usage: $0 {install|start|stop|restart|status|uninstall}" >&2
    exit 1
    ;;
esac
