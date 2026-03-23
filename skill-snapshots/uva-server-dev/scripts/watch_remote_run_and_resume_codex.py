#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


FLOAT_RE = r"[-+]?(?:\d+\.\d+|\d+)(?:[eE][-+]?\d+)?"
LOSS_STEP_RE = re.compile(rf"Loss:\s*({FLOAT_RE}), step:\s*(\d+)")
PE_FID_RE = re.compile(
    rf"fid_before_selection:\s*({FLOAT_RE})\s+fid_top:\s*({FLOAT_RE})\s+fid_bottom:\s*({FLOAT_RE})"
)
FID_RE = re.compile(rf"The FID of synthetic images is ({FLOAT_RE})")
IS_RE = re.compile(rf"The Inception Score of synthetic images is ({FLOAT_RE})")
PREC_RECALL_RE = re.compile(
    rf"The Precision and Recall of synthetic images is ({FLOAT_RE}) and ({FLOAT_RE})"
)
FLD_RE = re.compile(rf"The FLD of synthetic images is ({FLOAT_RE})")
EPS_RE = re.compile(rf"Eps-value after (\d+) epochs:\s*({FLOAT_RE})")
ACTUAL_TRACEBACK_RE = re.compile(r"(?m)^Traceback \(most recent call last\):")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Watch a remote run log over SSH. When the run becomes terminal, "
            "write a local summary, notify the caller in an agent-friendly way, "
            "and optionally resume the current Codex thread with a self-message."
        )
    )
    parser.add_argument("--host", required=True, help="Remote SSH host, e.g. dplab05")
    parser.add_argument("--log", required=True, help="Absolute remote log path")
    parser.add_argument(
        "--remote-command-prefix",
        help=(
            "Optional shell prefix executed on the remote host before each watcher "
            "command. Useful for portal-to-worker nested SSH, for example "
            "\"ssh -o BatchMode=yes groupml02.cs.virginia.edu\"."
        ),
    )
    parser.add_argument(
        "--process-pattern",
        required=True,
        help="Unique process substring used to detect whether the run is still alive",
    )
    parser.add_argument("--label", required=True, help="Human-readable run label")
    parser.add_argument(
        "--output",
        required=True,
        help="Absolute local markdown output path for the terminal summary",
    )
    parser.add_argument(
        "--json-output",
        help="Optional absolute local JSON output path for the terminal summary",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=180,
        help="Polling interval in seconds",
    )
    parser.add_argument(
        "--log-tail-lines",
        type=int,
        default=200,
        help="How many log lines to fetch per poll. Use 0 to read the full log.",
    )
    parser.add_argument(
        "--idle-polls",
        type=int,
        default=2,
        help=(
            "If the process disappears and the latest step stops changing for this "
            "many consecutive polls, treat the run as terminal."
        ),
    )
    parser.add_argument(
        "--terminal-file",
        action="append",
        default=[],
        help=(
            "Optional absolute remote path whose presence marks the run as terminal. "
            "Repeatable."
        ),
    )
    parser.add_argument(
        "--terminal-file-mode",
        choices=("all", "any"),
        default="all",
        help="How repeated --terminal-file signals should be combined.",
    )
    parser.add_argument(
        "--codex-thread-id",
        help=(
            "Optional Codex thread id to resume when the watched run becomes terminal. "
            "If omitted, the watcher falls back to the CODEX_THREAD_ID environment variable."
        ),
    )
    parser.add_argument(
        "--codex-cwd",
        help=(
            "Optional working directory to use when resuming the Codex thread. "
            "Defaults to the current working directory."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Poll once, write a snapshot, and exit without waiting for terminal state",
    )
    parser.add_argument(
        "--resume-prompt",
        help=(
            "Optional full prompt override used when resuming the Codex thread. "
            "Useful for safe end-to-end testing or fully custom hook behavior."
        ),
    )
    parser.add_argument(
        "--resume-instruction",
        help=(
            "Optional follow-up instruction appended to the default hook-style "
            "resume message. Use this to decide the desired next step when the "
            "watcher is launched."
        ),
    )
    parser.add_argument(
        "--notify-mode",
        choices=("auto", "desktop", "stdout", "none"),
        default="auto",
        help=(
            "How to surface terminal state. auto: if resuming Codex, skip local "
            "desktop notifications; otherwise emit a machine-readable JSON event "
            "to stdout for hook callers. desktop: show a macOS notification. "
            "stdout: always emit the JSON event. none: suppress both."
        ),
    )
    parser.add_argument(
        "--refresh-codex-ui",
        action="store_true",
        help=(
            "After a successful codex resume, force-refresh the local Codex desktop "
            "app by relaunching it with the helper script."
        ),
    )
    parser.add_argument(
        "--refresh-codex-ui-mode",
        choices=("nudge", "route-cycle", "restart"),
        default="restart",
        help=(
            "How the local helper should refresh Codex after a successful resume. "
            "nudge tries a lightweight in-app refresh; route-cycle remounts the "
            "active thread route; restart relaunches the app."
        ),
    )
    parser.add_argument(
        "--refresh-delay-seconds",
        type=float,
        default=2.0,
        help=(
            "When --refresh-codex-ui is set, wait this many seconds after the "
            "resume call before triggering the local UI refresh."
        ),
    )
    return parser.parse_args()


def _wrap_remote_command(remote_cmd: str, remote_command_prefix: Optional[str]) -> str:
    if not remote_command_prefix:
        return remote_cmd
    return f"{remote_command_prefix} {shlex.quote(remote_cmd)}"


def ssh_run(
    host: str,
    remote_cmd: str,
    remote_command_prefix: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        host,
        _wrap_remote_command(remote_cmd, remote_command_prefix),
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def ssh_read_log(
    host: str,
    path: str,
    remote_command_prefix: Optional[str] = None,
    tail_lines: int = 200,
) -> str:
    if tail_lines > 0:
        remote_cmd = f"tail -n {tail_lines} {shlex.quote(path)}"
    else:
        remote_cmd = f"cat {shlex.quote(path)}"
    result = ssh_run(host, remote_cmd, remote_command_prefix)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"failed to read {host}:{path}")
    return result.stdout


def ssh_process_alive(host: str, process_pattern: str, remote_command_prefix: Optional[str] = None) -> bool:
    remote_cmd = (
        "ps -fu \"$USER\" | grep -F -- "
        f"{shlex.quote(process_pattern)} | grep -v grep >/dev/null"
    )
    result = ssh_run(host, remote_cmd, remote_command_prefix)
    return result.returncode == 0


def ssh_file_exists(host: str, path: str, remote_command_prefix: Optional[str] = None) -> bool:
    result = ssh_run(host, f"test -f {shlex.quote(path)}", remote_command_prefix)
    return result.returncode == 0


def ssh_file_size(host: str, path: str, remote_command_prefix: Optional[str] = None) -> Optional[int]:
    result = ssh_run(host, f"wc -c < {shlex.quote(path)}", remote_command_prefix)
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def terminal_files_satisfied(
    host: str,
    paths: list[str],
    *,
    mode: str,
    remote_command_prefix: Optional[str] = None,
) -> tuple[bool, Dict[str, bool]]:
    statuses = {path: ssh_file_exists(host, path, remote_command_prefix) for path in paths}
    if not paths:
        return False, statuses
    if mode == "any":
        return any(statuses.values()), statuses
    return all(statuses.values()), statuses


def last_match(pattern: re.Pattern[str], text: str) -> Optional[Tuple[str, ...]]:
    matches = pattern.findall(text)
    if not matches:
        return None
    match = matches[-1]
    if isinstance(match, str):
        return (match,)
    return tuple(match)


def infer_stage(summary: Dict[str, Any]) -> str:
    if summary["has_traceback"]:
        return "error"
    if summary["eval_metrics_reported"]:
        return "done_eval"
    if summary["skip_eval_done"]:
        return "done_skip_eval"
    if summary["generation_finished"]:
        return "generated"
    if summary["pe_training_started"] and not summary["pe_training_finished"]:
        return "pe_training"
    if summary["latest_step"] is not None:
        return "main_training"
    if summary["starting_training_events"] > 0:
        return "warmup_or_pretrain"
    return "initialized"


def summarize_text(text: str) -> Dict[str, Any]:
    loss_step = last_match(LOSS_STEP_RE, text)
    pe_fid = last_match(PE_FID_RE, text)
    precision_recall = last_match(PREC_RECALL_RE, text)
    eps = last_match(EPS_RE, text)
    fid_match = last_match(FID_RE, text)
    is_match = last_match(IS_RE, text)
    fld_match = last_match(FLD_RE, text)

    summary: Dict[str, Any] = {
        "latest_step": int(loss_step[1]) if loss_step else None,
        "latest_loss": float(loss_step[0]) if loss_step else None,
        "starting_training_events": text.count("Starting training at step 0"),
        "pe_training_started": "PE training start!" in text,
        "pe_training_finished": "PE training end!" in text,
        "generation_finished": "Generation Finished!" in text,
        "eval_metrics_reported": bool(fid_match),
        "skip_eval_done": "skip_eval=true: skipping evaluation step" in text,
        "has_traceback": bool(ACTUAL_TRACEBACK_RE.search(text)),
        "final_fid": float(fid_match[0]) if fid_match else None,
        "final_is": float(is_match[0]) if is_match else None,
        "final_precision": float(precision_recall[0]) if precision_recall else None,
        "final_recall": float(precision_recall[1]) if precision_recall else None,
        "final_fld": float(fld_match[0]) if fld_match else None,
        "pe_fid_before_last": float(pe_fid[0]) if pe_fid else None,
        "pe_fid_top_last": float(pe_fid[1]) if pe_fid else None,
        "pe_fid_bottom_last": float(pe_fid[2]) if pe_fid else None,
        "last_reported_epoch": int(eps[0]) if eps else None,
        "last_reported_epsilon": float(eps[1]) if eps else None,
        "last_lines": [line for line in text.strip().splitlines() if line][-20:],
    }
    summary["stage"] = infer_stage(summary)
    return summary


def make_progress_signature(summary: Dict[str, Any], text: str, log_size: Optional[int]) -> tuple[Any, ...]:
    if summary["latest_step"] is not None:
        return ("step", summary["latest_step"])
    tail = tuple(line for line in text.strip().splitlines() if line)[-10:]
    return ("tail", log_size, len(text), tail)


def is_terminal(
    summary: Dict[str, Any],
    running: bool,
    stagnant_polls: int,
    idle_polls: int,
    terminal_files_done: bool,
) -> bool:
    if summary["stage"] in {"done_eval", "done_skip_eval", "error"}:
        return True
    if terminal_files_done:
        return True
    if not running and stagnant_polls >= idle_polls:
        return True
    return False


def ensure_parent(path_str: str) -> Path:
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def format_metric(name: str, value: Optional[float]) -> str:
    if value is None:
        return f"- {name}: n/a"
    return f"- {name}: {value:.4f}"


def write_markdown(
    path: Path,
    *,
    label: str,
    host: str,
    log_path: str,
    process_pattern: str,
    running: bool,
    summary: Dict[str, Any],
    terminal_reason: str,
    remote_command_prefix: Optional[str],
    terminal_files: Dict[str, bool],
) -> None:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        f"# Run Watch Summary: {label}",
        "",
        f"- checked_at: `{now}`",
        f"- host: `{host}`",
        f"- log: `{log_path}`",
        f"- process_pattern: `{process_pattern}`",
        f"- terminal_reason: `{terminal_reason}`",
        f"- process_running: `{running}`",
        f"- stage: `{summary['stage']}`",
    ]
    if remote_command_prefix:
        lines.append(f"- remote_command_prefix: `{remote_command_prefix}`")
    lines.extend(
        [
            "",
            "## Progress",
            "",
            f"- latest_step: `{summary['latest_step']}`",
            f"- latest_loss: `{summary['latest_loss']}`",
            f"- last_reported_epoch: `{summary['last_reported_epoch']}`",
            f"- last_reported_epsilon: `{summary['last_reported_epsilon']}`",
            "",
        ]
    )
    if terminal_files:
        lines.extend(["## Terminal Signals", ""])
        for file_path, exists in terminal_files.items():
            lines.append(f"- `{file_path}`: `{exists}`")
        lines.append("")
    lines.extend(
        [
            "## Final Metrics",
            "",
            format_metric("FID", summary["final_fid"]),
            format_metric("IS", summary["final_is"]),
            format_metric("Precision", summary["final_precision"]),
            format_metric("Recall", summary["final_recall"]),
            format_metric("FLD", summary["final_fld"]),
            "",
            "## PE Selection Signal",
            "",
            format_metric("fid_before_selection", summary["pe_fid_before_last"]),
            format_metric("fid_top", summary["pe_fid_top_last"]),
            format_metric("fid_bottom", summary["pe_fid_bottom_last"]),
            "",
            "## Last Log Lines",
            "",
            "```text",
            *summary["last_lines"],
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def notify_desktop(title: str, body: str) -> None:
    script = f'display notification {json.dumps(body)} with title {json.dumps(title)}'
    subprocess.run(["osascript", "-e", script], check=False)


def build_terminal_event(
    *,
    label: str,
    host: str,
    log_path: str,
    output_path: Path,
    json_path: Optional[Path],
    summary: Dict[str, Any],
    terminal_reason: str,
    terminal_files: Dict[str, bool],
    title: str,
    body: str,
) -> Dict[str, Any]:
    return {
        "event": "remote_run_terminal",
        "label": label,
        "host": host,
        "log": log_path,
        "watch_summary": str(output_path),
        "json_output": str(json_path) if json_path else None,
        "stage": summary["stage"],
        "terminal_reason": terminal_reason,
        "terminal_files": terminal_files,
        "latest_step": summary["latest_step"],
        "latest_loss": summary["latest_loss"],
        "final_fid": summary["final_fid"],
        "final_is": summary["final_is"],
        "final_precision": summary["final_precision"],
        "final_recall": summary["final_recall"],
        "final_fld": summary["final_fld"],
        "title": title,
        "body": body,
    }


def maybe_notify(
    *,
    notify_mode: str,
    codex_thread_id: Optional[str],
    title: str,
    body: str,
    event_payload: Dict[str, Any],
) -> None:
    effective_mode = notify_mode
    if effective_mode == "auto":
        effective_mode = "none" if codex_thread_id else "stdout"

    if effective_mode == "desktop":
        notify_desktop(title, body)
    elif effective_mode == "stdout":
        print(json.dumps(event_payload, ensure_ascii=False), flush=True)


def build_resume_prompt(
    *,
    label: str,
    host: str,
    log_path: str,
    output_path: Path,
    summary: Dict[str, Any],
    terminal_reason: str,
    terminal_files: Dict[str, bool],
    resume_instruction: Optional[str] = None,
) -> str:
    metrics = [
        f"- stage: {summary['stage']}",
        f"- terminal_reason: {terminal_reason}",
        f"- log: {host}:{log_path}",
        f"- watch_summary: {output_path}",
        f"- latest_step: {summary['latest_step']}",
        f"- latest_loss: {summary['latest_loss']}",
        f"- last_reported_epoch: {summary['last_reported_epoch']}",
        f"- last_reported_epsilon: {summary['last_reported_epsilon']}",
        f"- final_fid: {summary['final_fid']}",
        f"- final_is: {summary['final_is']}",
        f"- final_precision: {summary['final_precision']}",
        f"- final_recall: {summary['final_recall']}",
        f"- final_fld: {summary['final_fld']}",
        f"- pe_fid_before_selection: {summary['pe_fid_before_last']}",
        f"- pe_fid_top: {summary['pe_fid_top_last']}",
        f"- pe_fid_bottom: {summary['pe_fid_bottom_last']}",
    ]
    if terminal_files:
        metrics.extend(
            f"- terminal_file[{path}]: {exists}"
            for path, exists in terminal_files.items()
        )
    next_step = (
        resume_instruction.strip()
        if resume_instruction and resume_instruction.strip()
        else "Inspect the result, update the notes/tables if needed, then continue with the next planned step."
    )
    prompt_lines = [
        f"Remote run finished: {label}.",
        "",
        "When you respond in the Codex Desktop thread, make the first line clearly visible:",
        f"[WATCHER] {label} finished ({terminal_reason})",
        "",
        "After that first line, give a short status summary and continue with the requested next step.",
        "",
        "Hook summary:",
        *metrics,
        "",
        "Requested next step:",
        next_step,
        "",
        "Recent log tail:",
        *summary["last_lines"],
    ]
    return "\n".join(prompt_lines)


def resume_codex_thread(thread_id: str, prompt: str, cwd: Optional[str]) -> subprocess.CompletedProcess[str]:
    cmd = ["codex"]
    if cwd:
        cmd.extend(["-C", cwd])
    cmd.extend(["exec", "resume", "--skip-git-repo-check", thread_id, prompt, "--json"])
    return subprocess.run(cmd, capture_output=True, text=True)


def refresh_codex_ui(mode: str, thread_id: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    cmd = ["/Users/tianhao/.local/bin/codex-ui-refresh", "--mode", mode]
    if mode == "route-cycle":
        if not thread_id:
            raise ValueError("route-cycle Codex UI refresh requires a thread id")
        cmd.extend(["--thread-id", thread_id])
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> int:
    args = parse_args()
    output_path = ensure_parent(args.output)
    json_path = ensure_parent(args.json_output) if args.json_output else None
    codex_thread_id = args.codex_thread_id or os.environ.get("CODEX_THREAD_ID")
    codex_cwd = args.codex_cwd or os.getcwd()

    last_progress_signature: Optional[tuple[Any, ...]] = None
    stagnant_polls = 0

    while True:
        text = ssh_read_log(
            args.host,
            args.log,
            args.remote_command_prefix,
            tail_lines=args.log_tail_lines,
        )
        log_size = ssh_file_size(args.host, args.log, args.remote_command_prefix)
        running = ssh_process_alive(args.host, args.process_pattern, args.remote_command_prefix)
        summary = summarize_text(text)
        terminal_done, terminal_files = terminal_files_satisfied(
            args.host,
            args.terminal_file,
            mode=args.terminal_file_mode,
            remote_command_prefix=args.remote_command_prefix,
        )

        progress_signature = make_progress_signature(summary, text, log_size)
        if progress_signature == last_progress_signature:
            stagnant_polls += 1
        else:
            stagnant_polls = 0
            last_progress_signature = progress_signature

        terminal_reason = "snapshot"
        if summary["stage"] == "done_eval":
            terminal_reason = "done_eval"
        elif summary["stage"] == "done_skip_eval":
            terminal_reason = "done_skip_eval"
        elif summary["stage"] == "error":
            terminal_reason = "traceback"
        elif terminal_done:
            terminal_reason = "terminal_files_present"
        elif not running and stagnant_polls >= args.idle_polls:
            terminal_reason = "process_gone_and_log_stagnant"

        write_markdown(
            output_path,
            label=args.label,
            host=args.host,
            log_path=args.log,
            process_pattern=args.process_pattern,
            running=running,
            summary=summary,
            terminal_reason=terminal_reason,
            remote_command_prefix=args.remote_command_prefix,
            terminal_files=terminal_files,
        )

        if json_path is not None:
            payload = {
                "checked_at": datetime.now().astimezone().isoformat(),
                "label": args.label,
                "host": args.host,
                "log": args.log,
                "process_pattern": args.process_pattern,
                "process_running": running,
                "terminal_reason": terminal_reason,
                "remote_command_prefix": args.remote_command_prefix,
                "log_tail_lines": args.log_tail_lines,
                "log_size_bytes": log_size,
                "terminal_files": terminal_files,
                **summary,
            }
            json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        if args.once:
            return 0

        if is_terminal(summary, running, stagnant_polls, args.idle_polls, terminal_done):
            if summary["final_fid"] is not None:
                body = f"{summary['stage']} | FID={summary['final_fid']:.2f}"
            elif summary["latest_step"] is not None:
                body = f"{summary['stage']} | last_step={summary['latest_step']}"
            elif terminal_done:
                body = f"{summary['stage']} | terminal_artifacts_ready"
            else:
                body = summary["stage"]
            title = f"Remote run finished: {args.label}"
            event_payload = build_terminal_event(
                label=args.label,
                host=args.host,
                log_path=args.log,
                output_path=output_path,
                json_path=json_path,
                summary=summary,
                terminal_reason=terminal_reason,
                terminal_files=terminal_files,
                title=title,
                body=body,
            )
            maybe_notify(
                notify_mode=args.notify_mode,
                codex_thread_id=codex_thread_id,
                title=title,
                body=body,
                event_payload=event_payload,
            )
            if codex_thread_id:
                prompt = args.resume_prompt or build_resume_prompt(
                    label=args.label,
                    host=args.host,
                    log_path=args.log,
                    output_path=output_path,
                    summary=summary,
                    terminal_reason=terminal_reason,
                    terminal_files=terminal_files,
                    resume_instruction=args.resume_instruction,
                )
                resume_result = resume_codex_thread(codex_thread_id, prompt, codex_cwd)
                refresh_result: Optional[subprocess.CompletedProcess[str]] = None
                if args.refresh_codex_ui and resume_result.returncode == 0:
                    time.sleep(max(args.refresh_delay_seconds, 0.0))
                    refresh_result = refresh_codex_ui(
                        args.refresh_codex_ui_mode,
                        thread_id=codex_thread_id,
                    )
                if json_path is not None:
                    payload = json.loads(json_path.read_text(encoding="utf-8"))
                    payload["codex_resume"] = {
                        "thread_id": codex_thread_id,
                        "cwd": codex_cwd,
                        "returncode": resume_result.returncode,
                        "stdout_tail": resume_result.stdout[-2000:],
                        "stderr_tail": resume_result.stderr[-2000:],
                    }
                    if refresh_result is not None:
                        payload["codex_ui_refresh"] = {
                            "mode": args.refresh_codex_ui_mode,
                            "returncode": refresh_result.returncode,
                            "stdout_tail": refresh_result.stdout[-2000:],
                            "stderr_tail": refresh_result.stderr[-2000:],
                        }
                    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return 0

        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
