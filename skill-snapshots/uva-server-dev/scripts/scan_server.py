#!/usr/bin/env python3
"""Scan a subnet slice for hosts with SSH open."""

from __future__ import annotations

import argparse
import socket
from concurrent.futures import ThreadPoolExecutor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan a /24-style prefix for hosts with SSH open."
    )
    parser.add_argument(
        "--prefix",
        default="128.143.71",
        help="IP prefix to scan (default: 128.143.71).",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Starting host index in the prefix (default: 1).",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=254,
        help="Ending host index in the prefix (default: 254).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=22,
        help="TCP port to test (default: 22).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.0,
        help="Per-host socket timeout in seconds (default: 1.0).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Concurrent worker count (default: 10).",
    )
    parser.add_argument(
        "--resolve",
        action="store_true",
        help="Attempt reverse DNS lookup for open hosts.",
    )
    parser.add_argument(
        "--banner",
        action="store_true",
        help="Attempt to read the SSH banner for open hosts.",
    )
    return parser.parse_args()


def test_ssh_connection(ip: str, port: int, timeout: float, resolve: bool, banner: bool) -> None:
    """Print hosts whose port accepts a TCP connection."""
    ptr = ""
    if resolve:
        try:
            ptr = socket.gethostbyaddr(ip)[0]
        except Exception:
            ptr = ""

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((ip, port))
        if result != 0:
            return
        extra = []
        if ptr:
            extra.append(ptr)
        if banner:
            try:
                sock.settimeout(min(timeout, 0.5))
                banner_text = sock.recv(128).decode("utf-8", "replace").strip()
            except Exception:
                banner_text = ""
            if banner_text:
                extra.append(banner_text)
        suffix = "" if not extra else " | " + " | ".join(extra)
        print(f"SSH is available on {ip}{suffix}")
    finally:
        sock.close()


def scan_ips() -> None:
    args = parse_args()
    ip_range = [f"{args.prefix}.{i}" for i in range(args.start, args.end + 1)]
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for ip in ip_range:
            executor.submit(
                test_ssh_connection,
                ip,
                args.port,
                args.timeout,
                args.resolve,
                args.banner,
            )


if __name__ == "__main__":
    scan_ips()
