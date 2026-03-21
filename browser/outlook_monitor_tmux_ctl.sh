#!/bin/zsh
set -euo pipefail

SESSION="email-triage-monitor"
ROOT="/Users/tianhao/Downloads/email-triage-lab"
CMD="/opt/homebrew/bin/python3 $ROOT/browser/outlook_live_monitor.py watch --include-pinned --interval 30 >> $ROOT/shared/outlook_monitor.stdout.log 2>> $ROOT/shared/outlook_monitor.stderr.log"

case "${1:-}" in
  start)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "already running: $SESSION"
      exit 0
    fi
    tmux new-session -d -s "$SESSION" "cd $ROOT && $CMD"
    echo "started $SESSION"
    ;;
  stop)
    tmux kill-session -t "$SESSION"
    echo "stopped $SESSION"
    ;;
  restart)
    "$0" stop >/dev/null 2>&1 || true
    "$0" start
    ;;
  status)
    tmux has-session -t "$SESSION" 2>/dev/null
    tmux list-sessions | grep "$SESSION"
    ;;
  logs)
    tail -n 20 "$ROOT/shared/outlook_monitor.stdout.log"
    printf '\n---\n'
    tail -n 20 "$ROOT/shared/outlook_monitor.stderr.log"
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status|logs}" >&2
    exit 1
    ;;
esac
