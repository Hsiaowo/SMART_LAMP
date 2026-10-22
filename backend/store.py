"""One active plan, durable versions, and device acknowledgements in SQLite."""

from __future__ import annotations

import json
import sqlite3
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4


def canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def crc32(text: str) -> int:
    return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF


class Conflict(Exception):
    pass


class NotFound(Exception):
    pass


class InvalidTime(Exception):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError(f"Unsupported database schema: {version}")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS current (
                    id INTEGER PRIMARY KEY CHECK (id=1), snapshot TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requests (
                    request_id TEXT PRIMARY KEY, operation TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, response TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY, seen_ms INTEGER NOT NULL,
                    report TEXT NOT NULL
                );
                PRAGMA user_version=1;
            """)
            db.execute(
                "INSERT OR IGNORE INTO current VALUES (1, ?)",
                (canonical(self.empty_snapshot()),),
            )

    @staticmethod
    def empty_snapshot() -> dict:
        return {
            "schema_version": 1, "version": 0, "plan_id": "",
            "occurrence_id": "", "enabled": False,
            "ramp_start_ms": 0, "wake_at_ms": 0,
            "hold_until_ms": 0, "peak_percent": 0,
        }

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        # Always close the connection, including failed transactions.
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _read(db: sqlite3.Connection) -> dict:
        return json.loads(db.execute("SELECT snapshot FROM current WHERE id=1").fetchone()[0])

    def snapshot(self) -> dict:
        with self.connection() as db:
            return self._read(db)

    def save_plan(self, payload: dict, plan_id: str | None, now_ms: int) -> tuple[dict, bool]:
        operation = f"update:{plan_id}" if plan_id else "create"
        fingerprint = canonical(payload)
        with self.connection() as db:
            # Serialize version allocation and idempotency together.
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM requests WHERE request_id=?", (payload["request_id"],)
            ).fetchone()
            if previous:
                if previous["operation"] != operation or previous["fingerprint"] != fingerprint:
                    raise Conflict("request_id already used for a different request")
                return json.loads(previous["response"]), True
            # Validate new requests after replay lookup: retrying a completed
            # request tomorrow must never create a new event or fail as a new date.
            if not now_ms < payload["wake_at_ms"] <= now_ms + 7 * 24 * 3600 * 1000:
                raise InvalidTime("wake_at must be in the next seven days")
            old = self._read(db)
            if plan_id and (old["plan_id"] != plan_id or not old["enabled"]):
                raise NotFound("Active plan not found")
            identifier = plan_id or str(uuid4())
            version = old["version"] + 1
            wake = payload["wake_at_ms"]
            snapshot = {
                "schema_version": 1, "version": version, "plan_id": identifier,
                "occurrence_id": f"{identifier}:{version}", "enabled": True,
                "ramp_start_ms": wake - payload["ramp_seconds"] * 1000,
                "wake_at_ms": wake,
                "hold_until_ms": wake + payload["hold_seconds"] * 1000,
                "peak_percent": payload["peak_percent"],
            }
            db.execute("UPDATE current SET snapshot=? WHERE id=1", (canonical(snapshot),))
            db.execute(
                "INSERT INTO requests VALUES (?, ?, ?, ?)",
                (payload["request_id"], operation, fingerprint, canonical(snapshot)),
            )
            return snapshot, False

    def cancel(self, plan_id: str) -> dict:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            snapshot = self._read(db)
            if snapshot["plan_id"] != plan_id:
                raise NotFound("Current plan not found")
            if snapshot["enabled"]:
                snapshot = {
                    **self.empty_snapshot(), "plan_id": plan_id,
                    "version": snapshot["version"] + 1,
                }
                db.execute("UPDATE current SET snapshot=? WHERE id=1", (canonical(snapshot),))
            return snapshot

    def record_device(self, device_id: str, report: dict, now_ms: int) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO devices VALUES (?, ?, ?) ON CONFLICT(device_id) "
                "DO UPDATE SET seen_ms=excluded.seen_ms, report=excluded.report",
                (device_id, now_ms, canonical(report)),
            )

    def devices(self) -> dict:
        with self.connection() as db:
            return {
                row["device_id"]: {"seen_ms": row["seen_ms"], **json.loads(row["report"])}
                for row in db.execute("SELECT * FROM devices")
            }

