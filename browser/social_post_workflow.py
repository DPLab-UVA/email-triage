#!/usr/bin/env python3
"""Browser-first social post drafting workflow on top of the gstack bridge."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gstack_browse_bridge import BridgeError, ensure_tmux_server, send_command

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".gstack"
DEFAULT_BROWSER = "Chrome"
DEFAULT_PROFILE = "Profile 1"
SOCIAL_SESSION = "email-triage-social-browse"
SOCIAL_STATE_FILE = STATE_DIR / "bridge-browse-social.json"
SOCIAL_SERVER_LOG = STATE_DIR / "bridge-browse-social-server.log"


@dataclass(frozen=True)
class PlatformConfig:
    slug: str
    display_name: str
    home_url: str
    compose_url: str
    cookie_domains: list[str]
    login_markers: list[str]
    logged_out_markers: list[str]


PLATFORMS: dict[str, PlatformConfig] = {
    "linkedin": PlatformConfig(
        slug="linkedin",
        display_name="LinkedIn",
        home_url="https://www.linkedin.com/feed/",
        compose_url="https://www.linkedin.com/feed/",
        cookie_domains=["linkedin.com", ".linkedin.com", "www.linkedin.com"],
        login_markers=["start a post", "linkedin", "feed", "post"],
        logged_out_markers=["sign in", "join now", "forgot password", "new to linkedin"],
    ),
    "x": PlatformConfig(
        slug="x",
        display_name="X",
        home_url="https://x.com/home",
        compose_url="https://x.com/compose/post",
        cookie_domains=["x.com", ".x.com", "twitter.com", ".twitter.com"],
        login_markers=["post", "what's happening", "for you", "following"],
        logged_out_markers=["sign in to x", "don't miss what's happening", "log in", "create account"],
    ),
    "xiaohongshu": PlatformConfig(
        slug="xiaohongshu",
        display_name="Xiaohongshu",
        home_url="https://creator.xiaohongshu.com/publish/publish",
        compose_url="https://creator.xiaohongshu.com/publish/publish",
        cookie_domains=[
            "xiaohongshu.com",
            ".xiaohongshu.com",
            "www.xiaohongshu.com",
            "creator.xiaohongshu.com",
        ],
        login_markers=["发布", "创作服务", "创作中心", "笔记"],
        logged_out_markers=["登录", "扫码登录", "手机号登录", "短信登录"],
    ),
}


def activate_social_bridge() -> None:
    os.environ["GSTACK_BRIDGE_SESSION"] = SOCIAL_SESSION
    os.environ["GSTACK_BRIDGE_STATE_FILE"] = str(SOCIAL_STATE_FILE)
    os.environ["GSTACK_BRIDGE_SERVER_LOG"] = str(SOCIAL_SERVER_LOG)


def bridge_page_closed(exc: BridgeError) -> bool:
    message = str(exc).lower()
    return "context or browser has been closed" in message or "target page, context or browser has been closed" in message


def kill_social_server() -> None:
    activate_social_bridge()
    subprocess.run(["tmux", "kill-session", "-t", SOCIAL_SESSION], check=False, capture_output=True, text=True)


def bridge_cmd(command: str, *args: str, timeout: float = 30.0) -> str:
    activate_social_bridge()
    try:
        return send_command(command, list(args), timeout=timeout).rstrip()
    except BridgeError as exc:
        if not bridge_page_closed(exc):
            raise
        kill_social_server()
        ensure_social_server()
        return send_command(command, list(args), timeout=timeout).rstrip()


def bridge_js(expr: str, *, timeout: float = 30.0) -> str:
    return bridge_cmd("js", expr, timeout=timeout)


def bridge_json(expr: str, *, timeout: float = 30.0) -> Any:
    raw = bridge_js(expr, timeout=timeout)
    return json.loads(raw or "null")


def ensure_social_server() -> dict[str, Any]:
    activate_social_bridge()
    return ensure_tmux_server()


def platform_config(slug: str) -> PlatformConfig:
    try:
        return PLATFORMS[slug]
    except KeyError as exc:
        raise BridgeError(f"Unsupported platform: {slug}") from exc


def normalize_text(value: str) -> str:
    return " ".join((value or "").lower().split())


def is_logged_in(config: PlatformConfig, url: str, page_text: str) -> bool:
    lower_url = (url or "").lower()
    lowered = normalize_text(page_text)
    if any(marker in lowered for marker in config.logged_out_markers):
        return False
    if "login" in lower_url or "signin" in lower_url:
        return False
    return any(marker in lowered for marker in config.login_markers)


def wait_ready(timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            bridge_cmd("wait", "--load", timeout=10.0)
            return
        except BridgeError:
            time.sleep(0.2)


def current_view(text_limit: int = 4000) -> dict[str, Any]:
    return {
        "url": bridge_cmd("url"),
        "tabs": bridge_cmd("tabs"),
        "text": bridge_cmd("text", timeout=45.0)[:text_limit],
    }


def import_platform_cookies(browser: str, profile: str, config: PlatformConfig) -> list[str]:
    results: list[str] = []
    for domain in config.cookie_domains:
        results.append(
            bridge_cmd(
                "cookie-import-browser",
                browser,
                "--domain",
                domain,
                "--profile",
                profile,
                timeout=45.0,
            )
        )
    return results


def ensure_platform_session(config: PlatformConfig, browser: str, profile: str) -> dict[str, Any]:
    server = ensure_social_server()
    imports = import_platform_cookies(browser, profile, config)
    bridge_cmd("goto", config.home_url, timeout=45.0)
    wait_ready()
    payload = current_view()
    payload.update(
        {
            "server": server,
            "browser": browser,
            "profile": profile,
            "platform": config.slug,
            "logged_in": is_logged_in(config, payload["url"], payload["text"]),
            "import_results": imports,
        }
    )
    return payload


def require_logged_in(session_payload: dict[str, Any], config: PlatformConfig) -> None:
    if session_payload.get("logged_in"):
        return
    compose = compose_state(config.slug)
    if compose.get("open"):
        return
    raise BridgeError(
        f"{config.display_name} session is not ready. Please log into {config.display_name} in Chrome {session_payload.get('profile', DEFAULT_PROFILE)} first."
    )


def compose_open_linkedin() -> dict[str, Any]:
    script = """
JSON.stringify(
  (() => {
    const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    const visible = (el) => !!el && el.getClientRects().length > 0;
    const click = (el) => {
      el.scrollIntoView({ block: 'center' });
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.click();
    };
    const dialog = document.querySelector('[role="dialog"]');
    if (dialog && dialog.querySelector('[contenteditable="true"], [role="textbox"]')) {
      return { ok: true, already_open: true };
    }
    const candidates = Array.from(document.querySelectorAll('button,[role="button"]')).filter(visible);
    const button = candidates.find((el) => {
      const label = normalize(el.getAttribute('aria-label') || el.innerText || el.textContent || '');
      return label.includes('start a post') || label.includes('开始发帖');
    });
    if (!button) return { ok: false, reason: 'start-post-button-not-found' };
    click(button);
    return { ok: true, already_open: false };
  })(),
  null,
  2
)
""".strip()
    return bridge_json(script, timeout=15.0) or {}


def compose_open_x() -> dict[str, Any]:
    bridge_cmd("goto", PLATFORMS["x"].compose_url, timeout=45.0)
    wait_ready()
    return {"ok": True, "already_open": False}


def compose_open_xiaohongshu() -> dict[str, Any]:
    bridge_cmd("goto", PLATFORMS["xiaohongshu"].compose_url, timeout=45.0)
    wait_ready()
    return {"ok": True, "already_open": False}


def wait_compose(platform: str, timeout_seconds: float = 12.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        state = compose_state(platform)
        if state.get("open"):
            return state
        time.sleep(0.25)
    return compose_state(platform)


def open_compose(config: PlatformConfig) -> dict[str, Any]:
    if config.slug == "linkedin":
        result = compose_open_linkedin()
    elif config.slug == "x":
        result = compose_open_x()
    elif config.slug == "xiaohongshu":
        result = compose_open_xiaohongshu()
    else:
        raise BridgeError(f"Unsupported platform for compose: {config.slug}")
    state = wait_compose(config.slug)
    return {**result, "compose_state": state}


def compose_state(platform: str) -> dict[str, Any]:
    if platform == "linkedin":
        script = """
JSON.stringify(
  (() => {
    const dialog = document.querySelector('[role="dialog"]');
    const box = dialog ? dialog.querySelector('[contenteditable="true"], [role="textbox"]') : null;
    return {
      open: !!box,
      text: box ? String(box.innerText || box.textContent || '').trim() : '',
      dialog_title: dialog ? String(dialog.getAttribute('aria-label') || '') : ''
    };
  })(),
  null,
  2
)
""".strip()
    elif platform == "x":
        script = """
JSON.stringify(
  (() => {
    const box = document.querySelector('[data-testid="tweetTextarea_0"], [role="textbox"][data-testid], [role="textbox"]');
    return {
      open: !!box,
      text: box ? String(box.innerText || box.textContent || '').trim() : ''
    };
  })(),
  null,
  2
)
""".strip()
    elif platform == "xiaohongshu":
        script = """
JSON.stringify(
  (() => {
    const title = document.querySelector('input[placeholder*="标题"], textarea[placeholder*="标题"]');
    const box = document.querySelector('[contenteditable="true"], textarea[placeholder*="正文"], textarea[placeholder*="描述"]');
    return {
      open: !!(title || box),
      title: title ? String(title.value || title.textContent || '').trim() : '',
      text: box ? String(box.value || box.innerText || box.textContent || '').trim() : ''
    };
  })(),
  null,
  2
)
""".strip()
    else:
        raise BridgeError(f"Unsupported platform state: {platform}")
    return bridge_json(script, timeout=15.0) or {}


def set_linkedin_draft(text: str) -> dict[str, Any]:
    script = f"""
JSON.stringify(
  (() => {{
    const value = {json.dumps(text, ensure_ascii=False)};
    const dialog = document.querySelector('[role="dialog"]');
    if (!dialog) return {{ ok: false, reason: 'dialog-not-found' }};
    const box = dialog.querySelector('[contenteditable="true"], [role="textbox"]');
    if (!box) return {{ ok: false, reason: 'textbox-not-found' }};
    box.focus();
    box.innerHTML = '';
    box.textContent = value;
    box.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: value }}));
    return {{ ok: true, text: String(box.innerText || box.textContent || '').trim() }};
  }})(),
  null,
  2
)
""".strip()
    return bridge_json(script, timeout=15.0) or {}


def set_x_draft(text: str) -> dict[str, Any]:
    script = f"""
JSON.stringify(
  (() => {{
    const value = {json.dumps(text, ensure_ascii=False)};
    const box = document.querySelector('[data-testid="tweetTextarea_0"], [role="textbox"][data-testid], [role="textbox"]');
    if (!box) return {{ ok: false, reason: 'textbox-not-found' }};
    box.focus();
    box.textContent = value;
    box.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: value }}));
    return {{ ok: true, text: String(box.innerText || box.textContent || '').trim() }};
  }})(),
  null,
  2
)
""".strip()
    return bridge_json(script, timeout=15.0) or {}


def set_xiaohongshu_draft(title: str, text: str) -> dict[str, Any]:
    script = f"""
JSON.stringify(
  (() => {{
    const titleValue = {json.dumps(title, ensure_ascii=False)};
    const bodyValue = {json.dumps(text, ensure_ascii=False)};
    const titleInput = document.querySelector('input[placeholder*="标题"], textarea[placeholder*="标题"]');
    const bodyInput = document.querySelector('[contenteditable="true"], textarea[placeholder*="正文"], textarea[placeholder*="描述"]');
    if (!titleInput && !bodyInput) return {{ ok: false, reason: 'editor-not-found' }};
    if (titleInput) {{
      titleInput.focus();
      if ('value' in titleInput) {{
        titleInput.value = titleValue;
      }} else {{
        titleInput.textContent = titleValue;
      }}
      titleInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
    }}
    if (bodyInput) {{
      bodyInput.focus();
      if ('value' in bodyInput) {{
        bodyInput.value = bodyValue;
      }} else {{
        bodyInput.textContent = bodyValue;
      }}
      bodyInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
    }}
    return {{
      ok: true,
      title: titleInput ? String(titleInput.value || titleInput.textContent || '').trim() : '',
      text: bodyInput ? String(bodyInput.value || bodyInput.innerText || bodyInput.textContent || '').trim() : ''
    }};
  }})(),
  null,
  2
)
""".strip()
    return bridge_json(script, timeout=15.0) or {}


def set_draft(config: PlatformConfig, text: str, *, title: str = "") -> dict[str, Any]:
    if config.slug == "linkedin":
        return set_linkedin_draft(text)
    if config.slug == "x":
        return set_x_draft(text)
    if config.slug == "xiaohongshu":
        return set_xiaohongshu_draft(title, text)
    raise BridgeError(f"Unsupported platform for draft writing: {config.slug}")


def load_text(args: argparse.Namespace) -> str:
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8")
    if args.text is not None:
        return args.text
    raise BridgeError("Provide --text or --text-file")


def print_payload(payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            print(f"{key}:")
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            print(f"{key}: {value}")
    return 0


def command_bootstrap(args: argparse.Namespace) -> int:
    config = platform_config(args.platform)
    payload = ensure_platform_session(config, args.browser, args.profile)
    return print_payload(payload, args.json)


def command_status(args: argparse.Namespace) -> int:
    config = platform_config(args.platform)
    payload = ensure_platform_session(config, args.browser, args.profile)
    payload["compose_state"] = compose_state(config.slug)
    return print_payload(payload, args.json)


def command_open_compose(args: argparse.Namespace) -> int:
    config = platform_config(args.platform)
    session_payload = ensure_platform_session(config, args.browser, args.profile)
    require_logged_in(session_payload, config)
    payload = {
        "platform": config.slug,
        "compose": open_compose(config),
        "view": current_view(),
    }
    return print_payload(payload, args.json)


def command_draft(args: argparse.Namespace) -> int:
    config = platform_config(args.platform)
    text = load_text(args)
    session_payload = ensure_platform_session(config, args.browser, args.profile)
    require_logged_in(session_payload, config)
    compose = open_compose(config)
    written = set_draft(config, text, title=args.title or "")
    payload = {
        "platform": config.slug,
        "compose": compose,
        "written": written,
        "compose_state": compose_state(config.slug),
        "view": current_view(),
    }
    return print_payload(payload, args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browser-first social post drafting workflow.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_platform_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("platform", choices=sorted(PLATFORMS))
        subparser.add_argument("--browser", default=DEFAULT_BROWSER)
        subparser.add_argument("--profile", default=DEFAULT_PROFILE)
        subparser.add_argument("--json", action="store_true")

    bootstrap_parser = subparsers.add_parser("bootstrap", help="Import cookies and land on the platform home page.")
    add_platform_args(bootstrap_parser)
    bootstrap_parser.set_defaults(func=command_bootstrap)

    status_parser = subparsers.add_parser("status", help="Show current platform page and compose state.")
    add_platform_args(status_parser)
    status_parser.set_defaults(func=command_status)

    compose_parser = subparsers.add_parser("open-compose", help="Open the platform compose page or dialog.")
    add_platform_args(compose_parser)
    compose_parser.set_defaults(func=command_open_compose)

    draft_parser = subparsers.add_parser("draft", help="Open compose and write a post draft.")
    add_platform_args(draft_parser)
    draft_parser.add_argument("--text")
    draft_parser.add_argument("--text-file")
    draft_parser.add_argument("--title", default="")
    draft_parser.set_defaults(func=command_draft)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except BridgeError as exc:
        print(f"Error: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
