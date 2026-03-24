#!/usr/bin/env python3
"""Apply Outlook Web triage actions to recent visible messages."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from gstack_browse_bridge import BridgeError, send_command
from outlook_recent_triage import (
    SHARED,
    fetch_recent_messages,
    triage_recent_messages,
    write_json,
    write_jsonl,
)
from outlook_web_workflow import (
    DEFAULT_BROWSER,
    DEFAULT_COOKIE_DOMAINS,
    DEFAULT_PROFILE,
    ensure_outlook_session,
)
sys.path.append(str(SHARED))
from sqlite_store import append_event  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACTION_LOG = "outlook_move_actions"


def bridge_js(expr: str, *, timeout: float = 30.0) -> str:
    return send_command("js", [expr], timeout=timeout).strip()


def bridge_cmd(command: str, *args: str, timeout: float = 30.0) -> str:
    return send_command(command, list(args), timeout=timeout).strip()


def bridge_json(expr: str, *, timeout: float = 30.0) -> Any:
    raw = bridge_js(expr, timeout=timeout)
    return json.loads(raw or "null")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    append_event(path, row)


def folder_exists(folder_name: str) -> bool:
    expr = f"""
JSON.stringify(
  (() => {{
    const target = {json.dumps(folder_name, ensure_ascii=False)};
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const cleanFolder = (value) => normalize(value)
      .replace(/\\bselected\\b/gi, '')
      .replace(/\\b\\d+\\s+(?:item|items|unread)\\b/gi, '')
      .replace(/\\s+/g, ' ')
      .trim();
    return Array.from(document.querySelectorAll('[role="treeitem"]')).some(
      (el) => cleanFolder(el.innerText || el.textContent || '') === target
    );
  }})()
)
""".strip()
    return bool(bridge_json(expr, timeout=10.0))


def mark_selected_message_read() -> dict[str, Any]:
    expr = """
JSON.stringify(
  (() => {
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const click = (el) => {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.click();
    };
    const selected = Array.from(document.querySelectorAll('[role="option"]')).find(
      (el) => el.getAttribute('aria-selected') === 'true'
    );
    const scopes = [];
    if (selected) scopes.push(selected);
    scopes.push(document);
    for (const scope of scopes) {
      const unreadButton = Array.from(scope.querySelectorAll('button, [role="button"], [title], [aria-label]')).find((el) => {
        const label = normalize(el.getAttribute('title') || el.getAttribute('aria-label') || el.innerText || el.textContent || '');
        return label === 'Mark as unread';
      });
      if (unreadButton) {
        return { ok: true, status: 'already-read' };
      }
      const button = Array.from(scope.querySelectorAll('button, [role="button"], [title], [aria-label]')).find((el) => {
        const label = normalize(el.getAttribute('title') || el.getAttribute('aria-label') || el.innerText || el.textContent || '');
        return label === 'Mark as read';
      });
      if (button) {
        click(button);
        return { ok: true, status: 'clicked' };
      }
    }
    return { ok: true, status: 'control-not-found' };
  })(),
  null,
  2
)
""".strip()
    return bridge_json(expr, timeout=10.0) or {}


def select_visible_message(
    dom_id: str,
    subject: str,
    *,
    sender: str = "",
    received_at: str = "",
    conversation_id: str = "",
) -> dict[str, Any]:
    expr = f"""
JSON.stringify(
  (() => {{
    const domId = {json.dumps(dom_id, ensure_ascii=False)};
    const subject = {json.dumps(subject, ensure_ascii=False)};
    const sender = {json.dumps(sender, ensure_ascii=False)};
    const receivedAt = {json.dumps(received_at, ensure_ascii=False)};
    const conversationId = {json.dumps(conversation_id, ensure_ascii=False)};
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const scoreCandidate = (text, convid) => {{
      let score = 0;
      if (domId) score += 0;
      if (conversationId && convid === conversationId) score += 10;
      if (subject && text.includes(subject)) score += 5;
      if (sender && text.includes(sender)) score += 3;
      if (receivedAt && text.includes(receivedAt)) score += 2;
      return score;
    }};
    const click = (el) => {{
      el.scrollIntoView({{ block: 'center' }});
      el.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
      el.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
      el.click();
    }};

    let el = domId ? document.getElementById(domId) : null;
    let strategy = 'dom_id';
    if (!el || el.getAttribute('role') !== 'option') {{
      const options = Array.from(document.querySelectorAll('[role="option"]'));
      const byConversation = conversationId
        ? options.find((candidate) => (candidate.getAttribute('data-convid') || '') === conversationId)
        : null;
      if (byConversation) {{
        el = byConversation;
        strategy = 'conversation_id';
      }} else {{
        let best = null;
        let bestScore = -1;
        for (const candidate of options) {{
          const text = normalize(candidate.innerText || candidate.textContent || '');
          const score = scoreCandidate(text, candidate.getAttribute('data-convid') || '');
          if (score > bestScore) {{
            best = candidate;
            bestScore = score;
          }}
        }}
        el = bestScore > 0 ? best : null;
        strategy = 'composite';
      }}
    }}
    if (!el) {{
      return {{ ok: false, reason: 'message-not-found', dom_id: domId, subject }};
    }}
    click(el);
    return {{
      ok: true,
      strategy,
      dom_id: el.id || '',
      subject,
      selected: el.getAttribute('aria-selected') === 'true'
    }};
  }})(),
  null,
  2
)
    """.strip()
    result = bridge_json(expr, timeout=15.0) or {}
    if result.get("ok"):
        time.sleep(0.2)
        if selected_subject_matches(subject, sender=sender, received_at=received_at, conversation_id=conversation_id):
            result["selected"] = True
            return result
        fallback = click_option_via_snapshot(subject, sender=sender, received_at=received_at, conversation_id=conversation_id)
        result["fallback"] = fallback
        if fallback.get("ok"):
            time.sleep(0.3)
            result["selected"] = selected_subject_matches(subject, sender=sender, received_at=received_at, conversation_id=conversation_id)
    return result


def selected_subject_matches(
    subject: str,
    *,
    sender: str = "",
    received_at: str = "",
    conversation_id: str = "",
) -> bool:
    expr = f"""
JSON.stringify(
  (() => {{
    const subject = {json.dumps(subject, ensure_ascii=False)};
    const sender = {json.dumps(sender, ensure_ascii=False)};
    const receivedAt = {json.dumps(received_at, ensure_ascii=False)};
    const conversationId = {json.dumps(conversation_id, ensure_ascii=False)};
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const selected = Array.from(document.querySelectorAll('[role="option"]')).find(
      (el) => el.getAttribute('aria-selected') === 'true'
    );
    if (!selected) return false;
    const text = normalize(selected.innerText || selected.textContent || '');
    const convid = selected.getAttribute('data-convid') || '';
    if (conversationId && convid === conversationId) return true;
    if (subject && !text.includes(subject)) return false;
    if (sender && !text.includes(sender)) return false;
    if (receivedAt && !text.includes(receivedAt)) return false;
    return Boolean(subject || sender || receivedAt);
  }})()
)
""".strip()
    return bool(bridge_json(expr, timeout=10.0))


def click_option_via_snapshot(
    subject: str,
    *,
    sender: str = "",
    received_at: str = "",
    conversation_id: str = "",
) -> dict[str, Any]:
    snapshot = bridge_cmd("snapshot", "-i", timeout=20.0)
    pattern = re.compile(r"^\s*(@e\d+)\s+\[option\]\s+\"(.*)$")
    best: tuple[int, str, str] | None = None
    for line in snapshot.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        element_id, text = match.groups()
        score = 0
        if conversation_id and conversation_id in text:
            score += 10
        if subject and subject in text:
            score += 5
        if sender and sender in text:
            score += 3
        if received_at and received_at in text:
            score += 2
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, element_id, text)
    if not best:
        return {"ok": False, "reason": "snapshot-option-not-found"}
    _, element_id, text = best
    bridge_cmd("click", element_id, timeout=10.0)
    return {"ok": True, "strategy": "snapshot", "element_id": element_id, "text": text}


def inspect_move_picker(folder_name: str) -> dict[str, Any]:
    expr = f"""
JSON.stringify(
  (() => {{
    const target = {json.dumps(folder_name, ensure_ascii=False)};
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const click = (el) => {{
      el.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
      el.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
      el.click();
    }};

    const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).find((el) =>
      /Move items|Choose a destination folder/i.test(normalize(el.innerText || el.textContent || ''))
    );
    if (dialog) {{
      return {{ ok: true, stage: 'dialog' }};
    }}

    const directFolder = Array.from(document.querySelectorAll('[role="menuitem"]')).find(
      (el) => normalize(el.innerText || el.textContent || '') === target
    );
    if (directFolder) {{
      return {{ ok: true, stage: 'direct-menu-folder' }};
    }}

    const moreFolders = Array.from(document.querySelectorAll('[role="menuitem"]')).find((el) =>
      /Move to a different folder/i.test(normalize(el.innerText || el.textContent || ''))
    );
    if (!moreFolders) {{
      return {{ ok: false, reason: 'move-picker-not-ready' }};
    }}
    return {{ ok: true, stage: 'different-folder-menuitem' }};
  }})(),
  null,
  2
)
""".strip()
    return bridge_json(expr, timeout=15.0) or {}


def open_move_picker(folder_name: str) -> dict[str, Any]:
    existing = inspect_move_picker(folder_name)
    if existing.get("ok") and existing.get("stage") != "different-folder-menuitem":
        return existing

    expr = """
JSON.stringify(
  (() => {
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const click = (el) => {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.click();
    };
    const moveButton = Array.from(document.querySelectorAll('button')).find((el) => {
      const label = normalize(
        el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.textContent || ''
      );
      return label === 'Move to';
    });
    if (!moveButton) return { ok: false, reason: 'move-button-not-found' };
    click(moveButton);
    return { ok: true, stage: 'clicked-move-button' };
  })(),
  null,
  2
)
""".strip()
    if existing.get("stage") == "different-folder-menuitem":
        clicked = {"ok": True, "stage": "different-folder-menuitem"}
    else:
        clicked = bridge_json(expr, timeout=15.0) or {}
        if not clicked.get("ok"):
            return clicked

    for _ in range(6):
        time.sleep(0.2)
        state = inspect_move_picker(folder_name)
        if state.get("ok"):
            if state.get("stage") == "different-folder-menuitem":
                bridge_js(
                    """
(() => {
  const normalize = (value) => (value || '')
    .replace(/[\\uE000-\\uF8FF]/g, ' ')
    .replace(/\\s+/g, ' ')
    .trim();
  const click = (el) => {
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    el.click();
  };
  const moreFolders = Array.from(document.querySelectorAll('[role="menuitem"]')).find((el) =>
    /Move to a different folder/i.test(normalize(el.innerText || el.textContent || ''))
  );
  if (!moreFolders) return 'not-found';
  click(moreFolders);
  return 'clicked';
})()
""".strip(),
                    timeout=10.0,
                )
                time.sleep(0.3)
                dialog_state = inspect_move_picker(folder_name)
                if dialog_state.get("ok"):
                    return dialog_state
            else:
                return state

    return {"ok": False, "reason": "different-folder-menuitem-not-found"}


def dismiss_move_dialog() -> bool:
    expr = """
JSON.stringify(
  (() => {
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const click = (el) => {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.click();
    };
    const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).find((el) =>
      /Move items|Choose a destination folder/i.test(normalize(el.innerText || el.textContent || ''))
    );
    if (!dialog) return false;
    const cancel = Array.from(dialog.querySelectorAll('button')).find(
      (el) => normalize(el.innerText || el.textContent || '') === 'Cancel'
    );
    if (!cancel) return false;
    click(cancel);
    return true;
  })()
)
""".strip()
    return bool(bridge_json(expr, timeout=10.0))


def select_folder_in_dialog(folder_name: str) -> dict[str, Any]:
    expr = f"""
JSON.stringify(
  (() => {{
    const target = {json.dumps(folder_name, ensure_ascii=False)};
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const click = (el) => {{
      el.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
      el.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
      el.click();
    }};

    const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).find((el) =>
      /Move items|Choose a destination folder/i.test(normalize(el.innerText || el.textContent || ''))
    );
    if (!dialog) {{
      return {{ ok: false, reason: 'move-dialog-not-found' }};
    }}

    const treeItem = Array.from(dialog.querySelectorAll('[role="treeitem"]')).find(
      (el) => normalize(el.innerText || el.textContent || '') === target
    );
    if (!treeItem) {{
      return {{
        ok: false,
        reason: 'target-folder-not-found',
        available: Array.from(dialog.querySelectorAll('[role="treeitem"]')).map((el) =>
          normalize(el.innerText || el.textContent || '')
        )
      }};
    }}
    click(treeItem);
    const moveButton = Array.from(dialog.querySelectorAll('button')).find(
      (el) => normalize(el.innerText || el.textContent || '') === 'Move'
    );
    if (!moveButton) {{
      return {{ ok: false, reason: 'move-confirm-not-found' }};
    }}
    return {{ ok: true, move_enabled: !moveButton.disabled }};
  }})(),
  null,
  2
)
""".strip()
    return bridge_json(expr, timeout=20.0) or {}


def move_button_enabled() -> bool:
    expr = """
JSON.stringify(
  (() => {
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).find((el) =>
      /Move items|Choose a destination folder/i.test(normalize(el.innerText || el.textContent || ''))
    );
    if (!dialog) return false;
    const moveButton = Array.from(dialog.querySelectorAll('button')).find(
      (el) => normalize(el.innerText || el.textContent || '') === 'Move'
    );
    return !!moveButton && !moveButton.disabled;
  })()
)
""".strip()
    return bool(bridge_json(expr, timeout=10.0))


def click_menu_folder(folder_name: str) -> dict[str, Any]:
    expr = f"""
JSON.stringify(
  (() => {{
    const target = {json.dumps(folder_name, ensure_ascii=False)};
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const click = (el) => {{
      el.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
      el.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
      el.click();
    }};
    const item = Array.from(document.querySelectorAll('[role="menuitem"]')).find(
      (el) => normalize(el.innerText || el.textContent || '') === target
    );
    if (!item) return {{ ok: false, reason: 'menu-folder-not-found' }};
    click(item);
    return {{ ok: true }};
  }})(),
  null,
  2
)
""".strip()
    return bridge_json(expr, timeout=10.0) or {}


def confirm_move_in_dialog() -> dict[str, Any]:
    expr = """
JSON.stringify(
  (() => {
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    const click = (el) => {
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.click();
    };
    const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).find((el) =>
      /Move items|Choose a destination folder/i.test(normalize(el.innerText || el.textContent || ''))
    );
    if (!dialog) return { ok: false, reason: 'move-dialog-not-found' };
    const moveButton = Array.from(dialog.querySelectorAll('button')).find(
      (el) => normalize(el.innerText || el.textContent || '') === 'Move'
    );
    if (!moveButton) return { ok: false, reason: 'move-confirm-not-found' };
    if (moveButton.disabled) return { ok: false, reason: 'move-confirm-disabled' };
    click(moveButton);
    return { ok: true };
  })(),
  null,
  2
)
""".strip()
    return bridge_json(expr, timeout=15.0) or {}


def visible_subjects() -> list[str]:
    expr = """
JSON.stringify(
  (() => {
    const normalize = (value) => (value || '')
      .replace(/[\\uE000-\\uF8FF]/g, ' ')
      .replace(/\\s+/g, ' ')
      .trim();
    return Array.from(document.querySelectorAll('[role="option"]')).map((el) =>
      normalize(el.innerText || el.textContent || '')
    );
  })(),
  null,
  2
)
""".strip()
    return bridge_json(expr, timeout=15.0) or []


def move_message_to_folder(row: dict[str, Any], folder_name: str, *, mark_read_before_move: bool = False) -> dict[str, Any]:
    dismiss_move_dialog()
    selection = select_visible_message(
        str(row.get("dom_id", "")),
        str(row.get("subject", "")),
        sender=str(row.get("from", "")),
        received_at=str(row.get("received_at", "")),
        conversation_id=str(row.get("conversation_id", "")),
    )
    if not selection.get("ok"):
        return {"ok": False, "step": "select", "detail": selection}
    time.sleep(0.4)
    read_result: dict[str, Any] | None = None
    if mark_read_before_move and bool(row.get("unread")):
        read_result = mark_selected_message_read()
        time.sleep(0.3)

    opened = open_move_picker(folder_name)
    if not opened.get("ok"):
        return {
            "ok": False,
            "step": "open_move_picker",
            "detail": {
                "selection": selection,
                "mark_read": read_result,
                "opened": opened,
            },
        }
    time.sleep(0.5)

    if opened.get("stage") == "direct-menu-folder":
        clicked_folder = click_menu_folder(folder_name)
        if not clicked_folder.get("ok"):
            return {"ok": False, "step": "click_menu_folder", "detail": clicked_folder}
        time.sleep(0.8)
        still_visible = any(str(row.get("subject", "")) in text for text in visible_subjects())
        return {
            "ok": not still_visible,
            "step": "move-direct",
            "detail": {
                "selection": selection,
                "mark_read": read_result,
                "opened": opened,
                "clicked_folder": clicked_folder,
                "still_visible": still_visible,
            },
        }

    chosen = select_folder_in_dialog(folder_name)
    if not chosen.get("ok"):
        if chosen.get("reason") == "move-dialog-not-found":
            dismiss_move_dialog()
            time.sleep(0.2)
            reopened = open_move_picker(folder_name)
            if reopened.get("ok") and reopened.get("stage") == "direct-menu-folder":
                clicked_folder = click_menu_folder(folder_name)
                if not clicked_folder.get("ok"):
                    return {"ok": False, "step": "click_menu_folder", "detail": clicked_folder}
                time.sleep(0.8)
                still_visible = any(str(row.get("subject", "")) in text for text in visible_subjects())
                return {
                    "ok": not still_visible,
                    "step": "move-direct-retry",
                    "detail": {
                        "selection": selection,
                        "mark_read": read_result,
                        "opened": reopened,
                        "clicked_folder": clicked_folder,
                        "still_visible": still_visible,
                    },
                }
            if reopened.get("ok"):
                chosen = select_folder_in_dialog(folder_name)
        if not chosen.get("ok"):
            return {"ok": False, "step": "select_folder_in_dialog", "detail": chosen}

    enabled = bool(chosen.get("move_enabled"))
    if not enabled:
        for _ in range(5):
            time.sleep(0.2)
            if move_button_enabled():
                enabled = True
                break
    if not enabled:
        return {"ok": False, "step": "wait_move_enabled", "detail": chosen}

    moved = confirm_move_in_dialog()
    if not moved.get("ok"):
        return {"ok": False, "step": "confirm_move_in_dialog", "detail": moved}
    time.sleep(0.8)

    still_visible = any(str(row.get("subject", "")) in text for text in visible_subjects())
    return {
        "ok": not still_visible,
        "step": "move",
        "detail": {
            "selection": selection,
            "mark_read": read_result,
            "opened": opened,
            "chosen": chosen,
            "moved": moved,
            "still_visible": still_visible,
        },
    }


def apply_triage_actions(
    *,
    screens: int,
    limit: int,
    include_pinned: bool,
    rules_path: Path,
    examples_path: Path,
    raw_output: Path,
    triage_output: Path,
    digest_output: Path,
    summary_output: Path,
    action_log: Path,
    move_limit: int,
    dry_run: bool,
) -> dict[str, Any]:
    ensure_outlook_session(DEFAULT_BROWSER, DEFAULT_PROFILE, DEFAULT_COOKIE_DOMAINS)
    rows = fetch_recent_messages(screens=screens, limit=limit, recent_only=not include_pinned)
    triaged, summary = triage_recent_messages(rows, rules_path=rules_path, examples_path=examples_path)

    write_json(raw_output, rows)
    write_jsonl(triage_output, triaged)
    write_jsonl(digest_output, [row for row in triaged if row.get("bucket") in {"night_digest", "auto_action"}])

    folder_name = str(summary.get("nightly_digest_folder", "Night Review"))
    summary["night_review_folder_exists"] = folder_exists(folder_name)
    if not summary["night_review_folder_exists"]:
        raise BridgeError(f"Outlook folder not found: {folder_name}")

    candidates = [row for row in triaged if row.get("bucket") == "night_digest" and not row.get("pinned")]
    if move_limit > 0:
        candidates = candidates[:move_limit]

    actions: list[dict[str, Any]] = []
    for row in candidates:
        action = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "subject": row.get("subject", ""),
            "from": row.get("from", ""),
            "dom_id": row.get("dom_id", ""),
            "bucket": row.get("bucket", ""),
            "target_folder": folder_name,
            "dry_run": dry_run,
        }
        if dry_run:
            action["status"] = "planned"
            action["result"] = {"ok": True, "step": "dry-run"}
        else:
            result = move_message_to_folder(row, folder_name, mark_read_before_move=True)
            action["status"] = "moved" if result.get("ok") else "failed"
            action["result"] = result
        actions.append(action)
        append_jsonl(action_log, action)

    summary["action_log"] = str(action_log)
    summary["planned_moves"] = len(candidates)
    summary["moved"] = sum(1 for action in actions if action["status"] == "moved")
    summary["move_failures"] = sum(1 for action in actions if action["status"] == "failed")
    summary["dry_run"] = dry_run
    summary["move_examples"] = [
        {
            "subject": action["subject"],
            "from": action["from"],
            "status": action["status"],
            "target_folder": action["target_folder"],
        }
        for action in actions[:6]
    ]

    write_json(summary_output, summary)
    return {
        "raw_output": str(raw_output),
        "triage_output": str(triage_output),
        "digest_output": str(digest_output),
        "summary_output": str(summary_output),
        **summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply Outlook Web triage actions to recent visible messages.")
    parser.add_argument("--screens", type=int, default=4)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--include-pinned", action="store_true")
    parser.add_argument("--rules", default=str(SHARED / "default_rules.json"))
    parser.add_argument("--examples", default=str(SHARED / "example_labeled_emails.jsonl"))
    parser.add_argument("--raw-output", default=str(SHARED / "outlook_recent_messages.json"))
    parser.add_argument("--triage-output", default=str(SHARED / "outlook_recent_triage.jsonl"))
    parser.add_argument("--digest-output", default=str(SHARED / "outlook_recent_digest.jsonl"))
    parser.add_argument("--summary-output", default=str(SHARED / "outlook_recent_summary.json"))
    parser.add_argument("--action-log", default=str(DEFAULT_ACTION_LOG))
    parser.add_argument("--move-limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = apply_triage_actions(
        screens=args.screens,
        limit=args.limit,
        include_pinned=args.include_pinned,
        rules_path=Path(args.rules),
        examples_path=Path(args.examples),
        raw_output=Path(args.raw_output),
        triage_output=Path(args.triage_output),
        digest_output=Path(args.digest_output),
        summary_output=Path(args.summary_output),
        action_log=Path(args.action_log),
        move_limit=args.move_limit,
        dry_run=args.dry_run,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BridgeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
