#!/usr/bin/env python3
"""SQLite mirror store for local runtime state and event logs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

SHARED = Path(__file__).resolve().parent
DEFAULT_DB = SHARED / "email_triage.db"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream TEXT NOT NULL,
            source_path TEXT NOT NULL,
            ts TEXT NOT NULL,
            payload_hash TEXT,
            message_key TEXT,
            conversation_id TEXT,
            sender TEXT,
            subject TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
    if "payload_hash" not in columns:
        conn.execute("ALTER TABLE events ADD COLUMN payload_hash TEXT")
    migrate_missing_hashes(conn)
    dedupe_existing_events(conn)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_events_stream_ts
        ON events(stream, ts DESC)
        """
    )
    conn.execute("DROP INDEX IF EXISTS idx_events_dedupe")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedupe
        ON events(stream, source_path, payload_hash)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS state_snapshots (
            state_name TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def migrate_missing_hashes(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id, payload_json FROM events WHERE payload_hash IS NULL OR payload_hash = ''"
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            continue
        conn.execute(
            "UPDATE events SET payload_hash = ? WHERE id = ?",
            (payload_hash(payload), int(row["id"])),
        )


def dedupe_existing_events(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT stream, source_path, payload_hash, GROUP_CONCAT(id) AS ids
        FROM events
        WHERE payload_hash IS NOT NULL AND payload_hash != ''
        GROUP BY stream, source_path, payload_hash
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for row in rows:
        ids = [int(part) for part in str(row["ids"]).split(",") if part]
        ids.sort()
        for duplicate_id in ids[1:]:
            conn.execute("DELETE FROM events WHERE id = ?", (duplicate_id,))


def event_timestamp(row: dict[str, Any], *, fallback: str = "") -> str:
    for key in ("timestamp", "updated_at", "created_at", "moved_at"):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return fallback


def event_message_key(row: dict[str, Any]) -> str:
    for key in ("key", "conversation_id", "dom_id"):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    return ""


def mirror_jsonl_append(path: Path, row: dict[str, Any], *, db_path: Path = DEFAULT_DB) -> None:
    try:
        with connect(db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO events (
                    stream,
                    source_path,
                    ts,
                    payload_hash,
                    message_key,
                    conversation_id,
                    sender,
                    subject,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    path.stem,
                    str(path),
                    event_timestamp(row, fallback=now_iso()),
                    payload_hash(row),
                    event_message_key(row),
                    str(row.get("conversation_id", "")).strip(),
                    str(row.get("from", row.get("sender", ""))).strip(),
                    str(row.get("subject", "")).strip(),
                    json.dumps(row, ensure_ascii=False),
                ),
            )
            conn.commit()
    except Exception:
        # Mirror failures should never take down the primary mail workflow.
        return


def mirror_state(path: Path, payload: dict[str, Any], *, db_path: Path = DEFAULT_DB) -> None:
    try:
        updated_at = str(payload.get("updated_at", "")).strip() or now_iso()
        with connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO state_snapshots (state_name, source_path, updated_at, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(state_name) DO UPDATE SET
                  source_path=excluded.source_path,
                  updated_at=excluded.updated_at,
                  payload_json=excluded.payload_json
                """,
                (
                    path.stem,
                    str(path),
                    updated_at,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()
    except Exception:
        return


def backfill(shared_dir: Path, *, db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    event_files = sorted(shared_dir.glob("*.jsonl"))
    state_files = sorted(
        path for path in shared_dir.glob("*.json") if path.name.endswith("_state.json")
    )
    event_count = 0
    state_count = 0
    with connect(db_path) as conn:
        for path in event_files:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        row = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO events (
                            stream,
                            source_path,
                            ts,
                            payload_hash,
                            message_key,
                            conversation_id,
                            sender,
                            subject,
                            payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            path.stem,
                            str(path),
                            event_timestamp(row, fallback="1970-01-01T00:00:00+00:00"),
                            payload_hash(row),
                            event_message_key(row),
                            str(row.get("conversation_id", "")).strip(),
                            str(row.get("from", row.get("sender", ""))).strip(),
                            str(row.get("subject", "")).strip(),
                            json.dumps(row, ensure_ascii=False),
                        ),
                    )
                    event_count += max(0, int(cursor.rowcount))
        for path in state_files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            conn.execute(
                """
                INSERT INTO state_snapshots (state_name, source_path, updated_at, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(state_name) DO UPDATE SET
                  source_path=excluded.source_path,
                  updated_at=excluded.updated_at,
                  payload_json=excluded.payload_json
                """,
                (
                    path.stem,
                    str(path),
                    str(payload.get("updated_at", "")).strip() or now_iso(),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            state_count += 1
        conn.commit()
        stats = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM events) AS events,
              (SELECT COUNT(*) FROM state_snapshots) AS states
            """
        ).fetchone()
    return {
        "db_path": str(db_path),
        "backfilled_event_rows": event_count,
        "backfilled_state_rows": state_count,
        "total_events": int(stats["events"]),
        "total_states": int(stats["states"]),
    }


def status(*, db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    with connect(db_path) as conn:
        stats = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM events) AS events,
              (SELECT COUNT(*) FROM state_snapshots) AS states
            """
        ).fetchone()
        streams = [
            dict(row)
            for row in conn.execute(
                """
                SELECT stream, COUNT(*) AS count, MAX(ts) AS latest_ts
                FROM events
                GROUP BY stream
                ORDER BY latest_ts DESC
                LIMIT 12
                """
            ).fetchall()
        ]
    return {
        "db_path": str(db_path),
        "events": int(stats["events"]),
        "states": int(stats["states"]),
        "streams": streams,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite mirror store for email-triage runtime data.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--db", default=str(DEFAULT_DB))

    backfill_parser = subparsers.add_parser("backfill")
    backfill_parser.add_argument("--shared", default=str(SHARED))
    backfill_parser.add_argument("--db", default=str(DEFAULT_DB))

    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(status(db_path=Path(args.db)), ensure_ascii=False, indent=2))
        return 0
    if args.command == "backfill":
        print(
            json.dumps(
                backfill(Path(args.shared), db_path=Path(args.db)),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
