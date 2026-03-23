#!/usr/bin/env python3
"""Recommend a UVA compute target for a workload profile.

This helper converts the raw DPLab scan plus a lightweight Rivanna snapshot
into a placement recommendation. It is intended to answer:

- should this run go to DPLab or Rivanna?
- if DPLab, which hosts are the best current candidates?
- if Rivanna, is the target partition obviously congested?
"""

from __future__ import annotations

import argparse
import json
import subprocess
from typing import Any

from scan_idle_hosts import DEFAULT_HOSTS, scan_all


PROFILES = {
    "cpu-long": {
        "target": "rivanna",
        "reason": "Long CPU-heavy sweeps and preprocessing are better on a scheduled cluster.",
        "partition": "standard",
    },
    "preprocess": {
        "target": "rivanna",
        "reason": "ETL, cache building, and feature extraction are usually CPU-oriented and batch-friendly.",
        "partition": "standard",
    },
    "benchmark": {
        "target": "rivanna",
        "reason": "Large benchmark matrices are easier to manage and reproduce on scheduler-backed CPU resources.",
        "partition": "standard",
    },
    "gpu-short": {
        "target": "dplab",
        "reason": "Interactive neural debugging and short comparator runs are best on an actually idle DPLab GPU.",
        "partition": "gpu",
    },
    "gpu-long": {
        "target": "dplab-or-scheduled-gpu",
        "reason": "Long GPU runs can start on a free DPLab host, but scheduled GPU resources are safer for long or restart-sensitive jobs.",
        "partition": "gpu",
    },
}


def _run_ssh(host: str, remote_cmd: str, timeout: int = 20) -> tuple[bool, str]:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=5",
        host,
        remote_cmd,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if result.returncode != 0:
        return False, (result.stderr.strip() or result.stdout.strip() or "ssh failed")
    return True, result.stdout.strip()


def _rivanna_snapshot() -> dict[str, Any]:
    ok, out = _run_ssh(
        "rivanna",
        "bash -lc 'squeue -u nkp2mr -o \"%.18i %.9P %.20j %.8T %.10M %.6D %R\" | sed -n \"1,20p\"; echo \"---\"; sinfo -o \"%P %a %D %t %C\" | sed -n \"1,20p\"'",
    )
    if not ok:
        return {"ok": False, "error": out}
    lines = out.splitlines()
    split_idx = lines.index("---") if "---" in lines else len(lines)
    return {
        "ok": True,
        "squeue": lines[:split_idx],
        "sinfo": lines[split_idx + 1 :] if split_idx < len(lines) else [],
    }


def _free_gpu_hosts(summary: dict[str, Any]) -> list[dict[str, Any]]:
    hosts = [record for record in summary["ok"] if record.get("free_gpus", 0) > 0]
    hosts.sort(
        key=lambda r: (
            -r.get("free_gpus", 0),
            r.get("idle_score", 999.0),
            -max((gpu.get("mem_total_mib", 0) for gpu in r.get("gpus", [])), default=0),
            r["host"],
        )
    )
    return hosts


def _recommend(profile: str, dplab_summary: dict[str, Any], rivanna: dict[str, Any]) -> dict[str, Any]:
    spec = PROFILES[profile]
    free_hosts = _free_gpu_hosts(dplab_summary)
    recommendation: dict[str, Any] = {
        "profile": profile,
        "default_target": spec["target"],
        "reason": spec["reason"],
        "top_dplab_hosts": [
            {
                "host": record["host"],
                "free_gpus": record.get("free_gpus", 0),
                "gpu_names": sorted({gpu["name"] for gpu in record.get("gpus", []) if gpu.get("free")}),
                "idle_score": record.get("idle_score"),
            }
            for record in free_hosts[:4]
        ],
        "rivanna_ok": rivanna.get("ok", False),
        "rivanna_partition_hint": spec["partition"],
    }

    if profile in {"cpu-long", "preprocess", "benchmark"}:
        recommendation["recommended_target"] = "rivanna"
        recommendation["fallback_target"] = free_hosts[0]["host"] if free_hosts else None
    elif profile == "gpu-short":
        recommendation["recommended_target"] = free_hosts[0]["host"] if free_hosts else "rivanna-gpu"
        recommendation["fallback_target"] = "rivanna-gpu"
    else:
        if free_hosts:
            recommendation["recommended_target"] = free_hosts[0]["host"]
            recommendation["fallback_target"] = "rivanna-gpu"
        else:
            recommendation["recommended_target"] = "rivanna-gpu"
            recommendation["fallback_target"] = None
    return recommendation


def _print_human(result: dict[str, Any], rivanna: dict[str, Any]) -> None:
    print(f"profile: {result['profile']}")
    print(f"recommended_target: {result['recommended_target']}")
    if result.get("fallback_target"):
        print(f"fallback_target: {result['fallback_target']}")
    print(f"reason: {result['reason']}")
    print("")
    print("top_dplab_hosts:")
    if result["top_dplab_hosts"]:
        for record in result["top_dplab_hosts"]:
            gpu_names = ", ".join(record["gpu_names"]) if record["gpu_names"] else "unknown GPU"
            print(
                f"  - {record['host']}: free_gpus={record['free_gpus']} "
                f"idle_score={record['idle_score']} [{gpu_names}]"
            )
    else:
        print("  - none currently free")
    print("")
    print("rivanna_snapshot:")
    if not rivanna.get("ok"):
        print(f"  unavailable: {rivanna.get('error', 'unknown error')}")
        return
    for line in rivanna.get("squeue", [])[:6]:
        print(f"  {line}")
    print("  ---")
    for line in rivanna.get("sinfo", [])[:8]:
        print(f"  {line}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recommend a UVA compute target for a workload profile.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="gpu-short",
        help="Workload profile to place.",
    )
    parser.add_argument("--json", action="store_true", help="Emit structured JSON.")
    parser.add_argument(
        "--hosts",
        nargs="+",
        default=DEFAULT_HOSTS,
        help="DPLab host aliases to scan.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = scan_all(list(dict.fromkeys(args.hosts)))
    rivanna = _rivanna_snapshot()
    result = _recommend(args.profile, summary, rivanna)
    if args.json:
        print(json.dumps({"recommendation": result, "rivanna": rivanna}, ensure_ascii=False, indent=2))
    else:
        _print_human(result, rivanna)


if __name__ == "__main__":
    main()
