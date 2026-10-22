"""A clearly labelled virtual device using the same HTTP protocol as the ESP."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

from backend.store import crc32

ROOT = Path(__file__).resolve().parents[1]


def evaluate(snapshot: dict, now_ms: int, clock_valid: bool, completed: str) -> tuple[str, float]:
    if not clock_valid:
        return "needs_time", 0
    if not snapshot.get("enabled"):
        return "idle", 0
    if completed == snapshot["occurrence_id"]:
        return "done", 0
    if now_ms < snapshot["ramp_start_ms"]:
        return "armed", 0
    if now_ms < snapshot["wake_at_ms"]:
        ratio = (now_ms - snapshot["ramp_start_ms"]) / (
            snapshot["wake_at_ms"] - snapshot["ramp_start_ms"]
        )
        return "ramping", snapshot["peak_percent"] * ratio
    if now_ms < snapshot["hold_until_ms"]:
        return "holding", snapshot["peak_percent"]
    return "done", 0


class VirtualDevice:
    def __init__(self, path: Path):
        self.path = path
        self.snapshot: dict = {}
        self.raw = ""
        self.completed = ""
        self.clock_valid = False
        self.epoch = 0
        self.anchor = time.monotonic()
        self.boot_id = f"sim-{uuid4()}"
        self.error = ""
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.raw = saved["snapshot_json"]
            if crc32(self.raw) != saved["snapshot_crc32"]:
                raise ValueError("Corrupt simulator storage")
            self.snapshot = json.loads(self.raw)
            self.completed = saved.get("completed", "")

    def now_ms(self) -> int:
        return self.epoch + round((time.monotonic() - self.anchor) * 1000)

    def persist(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        pending = self.path.with_suffix(".tmp")
        pending.write_text(json.dumps({
            "snapshot_json": self.raw, "snapshot_crc32": crc32(self.raw),
            "completed": self.completed,
        }), encoding="utf-8")
        pending.replace(self.path)

    def accept(self, response: dict):
        raw = response["snapshot_json"]
        if crc32(raw) != response["snapshot_crc32"]:
            raise ValueError("Snapshot checksum mismatch")
        new = json.loads(raw)
        old_version = self.snapshot.get("version", 0)
        if new["version"] < old_version or (
            self.raw and new["version"] == old_version and raw != self.raw
        ):
            raise ValueError("Server version conflict")
        if not self.clock_valid:
            self.epoch = response["server_time_ms"]
            self.anchor = time.monotonic()
            self.clock_valid = True
        if not self.raw or new["version"] > old_version:
            old_raw, old_snapshot = self.raw, self.snapshot
            self.raw, self.snapshot = raw, new
            try:
                self.persist()
            except OSError:
                self.raw, self.snapshot = old_raw, old_snapshot
                raise
        self.error = ""

    def report(self) -> dict:
        state, brightness = evaluate(self.snapshot, self.now_ms(), self.clock_valid, self.completed)
        if state == "done" and self.completed != self.snapshot.get("occurrence_id"):
            self.completed = self.snapshot["occurrence_id"]
            self.persist()
        return {
            "boot_id": self.boot_id, "ack_version": self.snapshot.get("version", 0),
            "ack_crc32": crc32(self.raw) if self.raw else 0,
            "state": state, "brightness": brightness, "clock_valid": self.clock_valid,
            "storage_ok": True, "completed_occurrence_id": self.completed,
            "last_error": self.error,
        }


def main():
    parser = argparse.ArgumentParser(description="Simulate an LED; never counted as real hardware")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--id", default="sim-01")
    parser.add_argument("--state", type=Path, default=ROOT / "data" / "sim-01.json")
    args = parser.parse_args()
    config = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8"))
    entry = config["devices"][args.id]
    if entry["kind"] != "simulator":
        parser.error("Simulator must use an identity whose kind is simulator")
    virtual = VirtualDevice(args.state)
    previous = None
    with httpx.Client(timeout=1, headers={"Authorization": f"Bearer {entry['token']}"}) as client:
        while True:
            try:
                report = virtual.report()
                response = client.post(f"{args.url}/api/v1/devices/{args.id}/sync", json=report)
                response.raise_for_status()
                virtual.accept(response.json())
            except (httpx.HTTPError, OSError, ValueError) as exc:
                virtual.error = type(exc).__name__
            report = virtual.report()
            if report["state"] != previous:
                previous = report["state"]
                print(f"SIMULATOR {args.id}: {previous}, brightness={report['brightness']:.1f}%", flush=True)
            time.sleep(1)


if __name__ == "__main__":
    main()

