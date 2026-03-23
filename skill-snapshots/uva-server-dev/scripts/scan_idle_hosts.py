#!/usr/bin/env python3
"""Scan DPLab hosts for lightweight CPU/GPU availability over SSH.

This is a managed copy of the user's home-directory helper. It distinguishes
between "no GPU info because the machine has no GPU" and "nvidia-smi exists but
the driver stack is broken", which matters for DPLab scheduling decisions.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import shlex
import subprocess
from typing import Any

DEFAULT_HOSTS = [f"dplab{n:02d}" for n in range(1, 9)]
DEFAULT_GPU_FREE_UTIL = 20
DEFAULT_GPU_FREE_MEM_MIB = 1024
SSH_BASE_OPTS = [
    "-o",
    "BatchMode=yes",
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "ConnectTimeout=5",
    "-o",
    "ServerAliveInterval=10",
    "-o",
    "ServerAliveCountMax=2",
]

REMOTE_CMD = r"""bash -lc '
host=$(hostname 2>/dev/null || echo unknown)
cpu=$(nproc 2>/dev/null || echo 1)
la=$(awk "{print \$1}" /proc/loadavg 2>/dev/null || echo 0)
mem=$(awk "/MemTotal:/ {t=\$2} /MemAvailable:/ {a=\$2} END{if(t>0) printf \"%.2f\", (t-a)/t*100; else print 0}" /proc/meminfo 2>/dev/null || echo 0)
if command -v nvidia-smi >/dev/null 2>&1; then
  gpu_tmp=$(mktemp)
  if nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits >"$gpu_tmp" 2>&1; then
    gpu_state=OK
    gpus=$(tr "\n" ";" <"$gpu_tmp")
  else
    gpu_state=DRIVER_ERROR
    gpus=$(tr "\n" " " <"$gpu_tmp")
  fi
  rm -f "$gpu_tmp"
else
  gpu_state=NO_NVIDIA_SMI
  gpus=
fi
echo "__SCAN_RESULT__${host}|${cpu}|${la}|${mem}|${gpu_state}|${gpus}"
'"""


def _get_gpu_thresholds() -> tuple[int, int]:
    util = int(os.getenv("IDLE_GPU_FREE_UTIL", str(DEFAULT_GPU_FREE_UTIL)))
    mem = int(os.getenv("IDLE_GPU_FREE_MEM_MIB", str(DEFAULT_GPU_FREE_MEM_MIB)))
    return util, mem


def _host_rank(hosts: list[str], host: str) -> int:
    try:
        return hosts.index(host)
    except ValueError:
        return len(hosts)


def _parse_gpu_rows(gpus_s: str) -> list[dict[str, Any]]:
    gpu_free_util, gpu_free_mem_mib = _get_gpu_thresholds()
    gpus: list[dict[str, Any]] = []
    for row in [r for r in gpus_s.split(";") if r.strip()]:
        parts = [p.strip() for p in row.split(",")]
        if len(parts) < 5:
            continue
        idx = int(float(parts[0]))
        name = parts[1]
        mem_used = int(float(parts[2]))
        mem_total = int(float(parts[3]))
        util = int(float(parts[4]))
        is_free = util <= gpu_free_util and mem_used <= gpu_free_mem_mib
        gpus.append(
            {
                "index": idx,
                "name": name,
                "util_pct": util,
                "mem_used_mib": mem_used,
                "mem_total_mib": mem_total,
                "free": is_free,
            }
        )
    return gpus


def run_one(host: str) -> dict[str, Any]:
    cmd = ["ssh", *SSH_BASE_OPTS, host, REMOTE_CMD]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return {"host": host, "ok": False, "status": "unreachable", "error": "timeout"}

    if out.returncode != 0:
        err = out.stderr.strip() or "ssh failed"
        return {"host": host, "ok": False, "status": "unreachable", "error": err}

    marker = "__SCAN_RESULT__"
    lines = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    marked = next((line for line in reversed(lines) if line.startswith(marker)), "")
    if not marked:
        return {"host": host, "ok": False, "status": "parse_error", "error": "no marker in ssh output"}

    actual_host, cpu_s, la_s, mem_s, gpu_state, gpus_s = marked[len(marker) :].split("|", 5)
    cpu = int(float(cpu_s))
    la1 = float(la_s)
    mem_used_pct = float(mem_s)
    record: dict[str, Any] = {
        "host": host,
        "actual_host": actual_host,
        "ok": True,
        "status": "ok",
        "cpu_cores": cpu,
        "load1": la1,
        "mem_used_pct": mem_used_pct,
        "gpu_state": gpu_state,
        "gpus": [],
        "free_gpus": 0,
    }

    if gpu_state == "OK":
        gpus = _parse_gpu_rows(gpus_s)
        record["gpus"] = gpus
        record["free_gpus"] = sum(1 for g in gpus if g["free"])
    elif gpu_state == "DRIVER_ERROR":
        record["status"] = "gpu_driver_error"
        record["error"] = gpus_s.strip()
    elif gpu_state == "NO_NVIDIA_SMI":
        record["status"] = "no_nvidia_smi"

    idle_score = (la1 / max(cpu, 1)) * 0.6 + (mem_used_pct / 100.0) * 0.4
    if record["gpus"]:
        max_gpu_util = max(g["util_pct"] for g in record["gpus"])
        idle_score = idle_score * 0.8 + (max_gpu_util / 100.0) * 0.2
    record["idle_score"] = round(idle_score, 4)
    return record


def scan_all(hosts: list[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    with cf.ThreadPoolExecutor(max_workers=min(32, max(8, len(hosts)))) as ex:
        for result in ex.map(run_one, hosts):
            results.append(result)
    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]
    return {"ok": ok, "bad": bad}


def print_human(summary: dict[str, Any], hosts: list[str], sort_by: str) -> None:
    ok = list(summary["ok"])
    bad = list(summary["bad"])
    if sort_by == "idle":
        ok.sort(key=lambda r: (r.get("free_gpus", 0) == 0, r.get("idle_score", 1e9), r["host"]))
    else:
        ok.sort(key=lambda r: (_host_rank(hosts, r["host"]), r["host"]))
    bad.sort(key=lambda r: (_host_rank(hosts, r["host"]), r["host"]))

    for record in ok + bad:
        print(f"=== {record['host']} ===")
        if not record.get("ok"):
            print(f"status: {record.get('status', 'unreachable')}   error: {record.get('error', '')}")
            print("")
            continue
        base = (
            f"status: {record['status']}   load1/cpu: {record['load1']:.2f}/{record['cpu_cores']}   "
            f"mem_used: {record['mem_used_pct']:.1f}%   gpu_state: {record['gpu_state']}"
        )
        if record["gpus"]:
            base += f"   GPUs: {len(record['gpus'])}   free_gpus: {record['free_gpus']}"
        print(base)
        if record.get("error"):
            print(f"error: {record['error']}")
        for gpu in record["gpus"]:
            free_tag = "[FREE]" if gpu["free"] else "      "
            print(
                f"  GPU{gpu['index']:>2} {gpu['name']:<28} util {gpu['util_pct']:>3}%   "
                f"mem {gpu['mem_used_mib']:>6}/{gpu['mem_total_mib']:<6} MiB  {free_tag}"
            )
        print("")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument(
        "--only-gpu-free",
        action="store_true",
        help="Only include reachable hosts with at least one free GPU.",
    )
    parser.add_argument(
        "--sort-by",
        choices=("host", "idle"),
        default="host",
        help="Sort human-readable output by host name or idle score.",
    )
    parser.add_argument(
        "--hosts",
        nargs="+",
        default=DEFAULT_HOSTS,
        help="Host aliases to scan.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    hosts = list(dict.fromkeys(args.hosts))
    summary = scan_all(hosts)
    if args.only_gpu_free:
        summary["ok"] = [r for r in summary["ok"] if r.get("free_gpus", 0) > 0]
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print_human(summary, hosts, args.sort_by)


if __name__ == "__main__":
    main()
