import json

from backend.store import canonical, crc32
from scripts.simulate import VirtualDevice, evaluate


def response(enabled=True, version=1):
    raw = canonical({
        "schema_version": 1, "version": version, "plan_id": "test",
        "occurrence_id": f"test:{version}" if enabled else "", "enabled": enabled,
        "ramp_start_ms": 10000, "wake_at_ms": 20000, "hold_until_ms": 30000,
        "peak_percent": 80,
    })
    return {"snapshot_json": raw, "snapshot_crc32": crc32(raw), "server_time_ms": 15000}


def test_offline_device_continues_cached_plan(tmp_path):
    virtual = VirtualDevice(tmp_path / "device.json")
    virtual.accept(response())
    assert evaluate(virtual.snapshot, 15000, virtual.clock_valid, virtual.completed) == ("ramping", 40)
    # No further HTTP calls: these transitions use the cached plan only.
    assert evaluate(virtual.snapshot, 25000, virtual.clock_valid, virtual.completed) == ("holding", 80)
    assert evaluate(virtual.snapshot, 30000, virtual.clock_valid, virtual.completed) == ("done", 0)


def test_restart_requires_time_and_keeps_completed_guard(tmp_path):
    path = tmp_path / "device.json"
    first = VirtualDevice(path)
    first.accept(response())
    first.completed = "test:1"
    first.persist()
    restarted = VirtualDevice(path)
    assert restarted.clock_valid is False
    assert restarted.report()["state"] == "needs_time"
    restarted.accept(response())
    assert restarted.report()["state"] == "done"


def test_cancelled_snapshot_turns_output_off(tmp_path):
    virtual = VirtualDevice(tmp_path / "device.json")
    virtual.accept(response())
    virtual.accept(response(enabled=False, version=2))
    assert virtual.report()["state"] == "idle"
    assert virtual.report()["brightness"] == 0
    assert json.loads(virtual.raw)["version"] == 2
