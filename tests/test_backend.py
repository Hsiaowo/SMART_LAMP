import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.store import Store, canonical, crc32

ADMIN = "admin-test-token-at-least-16"
DEVICE = "device-test-token-at-least-16"
SIM = "simulator-test-token-at-least-16"
AUTH = {"Authorization": f"Bearer {ADMIN}"}
CONFIG = {
    "lamp-a": {"token": DEVICE, "kind": "esp8266"},
    "sim-01": {"token": SIM, "kind": "simulator"},
}
BASE = round(datetime(2026, 10, 22, 14, tzinfo=timezone.utc).timestamp() * 1000)


@pytest.fixture
def rig(tmp_path):
    clock = [BASE]
    path = tmp_path / "test.sqlite3"
    app = create_app(path, ADMIN, CONFIG, lambda: clock[0])
    with TestClient(app) as client:
        yield client, clock, path


def payload(**changes):
    return {
        "request_id": "unit-test-001", "wake_at": "2026-10-23T07:00:00+07:00",
        "ramp_seconds": 1200, "hold_seconds": 1200, "peak_percent": 80,
        **changes,
    }


def create(client, **changes):
    return client.post("/api/v1/wake-plans", headers=AUTH, json=payload(**changes))


def state(client):
    response = client.get("/api/v1/state", headers=AUTH)
    assert response.status_code == 200
    return response.json()


def report(**changes):
    return {
        "boot_id": "test-boot", "ack_version": 0, "ack_crc32": 0,
        "state": "armed", "brightness": 0, "clock_valid": True, "storage_ok": True,
        **changes,
    }


def sync(client, identifier="lamp-a", **changes):
    token = CONFIG[identifier]["token"]
    return client.post(f"/api/v1/devices/{identifier}/sync",
                       headers={"Authorization": f"Bearer {token}"}, json=report(**changes))


def test_authentication_boundaries(rig):
    client, _, _ = rig
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/api/v1/state").status_code == 401
    assert client.get("/api/v1/state", headers={"Authorization": f"Bearer {DEVICE}"}).status_code == 401
    assert client.post("/api/v1/devices/lamp-a/sync", headers=AUTH, json=report()).status_code == 401


def test_timezone_and_snapshot(rig):
    client, _, _ = rig
    response = create(client)
    assert response.status_code == 202
    snapshot = state(client)["snapshot"]
    expected = round(datetime(2026, 10, 23, tzinfo=timezone.utc).timestamp() * 1000)
    assert snapshot["wake_at_ms"] == expected
    assert snapshot["ramp_start_ms"] == expected - 1200000
    assert snapshot["hold_until_ms"] == expected + 1200000
    assert snapshot["version"] == 1


@pytest.mark.parametrize("changes", [
    {"wake_at": "2026-10-23T07:00:00"},  # Missing timezone.
    {"wake_at": "2026-10-21T00:00:00Z"},
    {"wake_at": "2026-11-23T00:00:00Z"},
    {"ramp_seconds": 0}, {"ramp_seconds": 2701},
    {"hold_seconds": 0}, {"peak_percent": 101}, {"peak_percent": 5.5},
])
def test_reject_invalid_plans_without_mutation(rig, changes):
    client, _, _ = rig
    assert create(client, **changes).status_code == 422
    assert state(client)["snapshot"]["version"] == 0


def test_idempotency_and_request_conflict(rig):
    client, clock, _ = rig
    first = create(client).json()
    assert create(client).json()["replayed"] is True
    assert create(client, peak_percent=79).status_code == 409
    clock[0] += 10 * 24 * 3600 * 1000
    replay = create(client)
    assert replay.status_code == 202
    assert replay.json()["version"] == first["version"]
    assert state(client)["snapshot"]["version"] == 1


def test_update_and_cancel_are_versioned(rig):
    client, _, _ = rig
    identifier = create(client).json()["plan_id"]
    changed = client.patch(f"/api/v1/wake-plans/{identifier}", headers=AUTH,
                           json=payload(request_id="unit-test-002", peak_percent=30))
    assert changed.status_code == 202
    assert changed.json()["version"] == 2
    assert state(client)["snapshot"]["peak_percent"] == 30
    cancel = client.delete(f"/api/v1/wake-plans/{identifier}", headers=AUTH)
    assert cancel.json()["version"] == 3
    assert client.delete(f"/api/v1/wake-plans/{identifier}", headers=AUTH).json()["version"] == 3
    assert state(client)["snapshot"]["enabled"] is False
    assert client.patch(f"/api/v1/wake-plans/{identifier}", headers=AUTH,
                        json=payload(request_id="unit-test-003")).status_code == 404


def test_replaying_old_request_never_resurrects_cancelled_plan(rig):
    client, _, _ = rig
    identifier = create(client).json()["plan_id"]
    client.delete(f"/api/v1/wake-plans/{identifier}", headers=AUTH)
    response = create(client).json()
    assert response["superseded"] is True
    assert state(client)["snapshot"]["enabled"] is False


def test_replacement_does_not_reinstall_old_plan(rig):
    client, _, _ = rig
    old = create(client).json()
    new = create(client, request_id="unit-test-002").json()
    assert old["plan_id"] != new["plan_id"]
    assert create(client).json()["superseded"] is True
    assert state(client)["snapshot"]["plan_id"] == new["plan_id"]
    assert client.get(old["sync_url"], headers=AUTH).status_code == 404


def test_persisted_ack_required_and_simulator_not_hardware(rig):
    client, _, _ = rig
    create(client)
    reply = sync(client).json()
    snap = json.loads(reply["snapshot_json"])
    assert crc32(reply["snapshot_json"]) == reply["snapshot_crc32"]
    assert state(client)["hardware_saved"] == 0
    ack = {"ack_version": snap["version"], "ack_crc32": reply["snapshot_crc32"]}
    sync(client, "sim-01", **ack)
    assert state(client)["simulator_ready"] == 1
    assert state(client)["hardware_saved"] == 0
    sync(client, **ack, storage_ok=False)
    assert state(client)["hardware_saved"] == 0
    sync(client, **ack, clock_valid=False)
    assert state(client)["hardware_saved"] == 1
    assert state(client)["hardware_ready"] == 0
    sync(client, **ack)
    assert state(client)["hardware_ready"] == 1


def test_cancel_is_pending_until_new_ack_and_offline_is_visible(rig):
    client, clock, _ = rig
    identifier = create(client).json()["plan_id"]
    reply = sync(client).json()
    sync(client, ack_version=1, ack_crc32=reply["snapshot_crc32"])
    client.delete(f"/api/v1/wake-plans/{identifier}", headers=AUTH)
    assert state(client)["hardware_saved"] == 0
    reply = sync(client).json()
    sync(client, ack_version=2, ack_crc32=reply["snapshot_crc32"])
    assert state(client)["hardware_saved"] == 1
    clock[0] += 13000
    result = state(client)
    assert result["hardware_saved"] == 1  # Persisted and online are distinct.
    assert result["hardware_ready"] == 0


def test_bad_ack_never_counts_as_saved(rig):
    client, _, _ = rig
    create(client)
    sync(client, ack_version=9999, ack_crc32=0)
    assert state(client)["hardware_saved"] == 0
    sync(client, ack_version=1, ack_crc32=0)
    assert state(client)["hardware_saved"] == 0


def test_server_restart_preserves_version_and_idempotency(rig):
    client, clock, path = rig
    original = create(client).json()
    with TestClient(create_app(path, ADMIN, CONFIG, lambda: clock[0])) as restarted:
        assert state(restarted)["snapshot"]["version"] == 1
        assert create(restarted).json()["plan_id"] == original["plan_id"]
        assert create(restarted, request_id="unit-test-002").json()["version"] == 2


def test_concurrent_version_allocation(rig):
    client, _, _ = rig
    with ThreadPoolExecutor(max_workers=6) as pool:
        versions = list(pool.map(
            lambda i: create(client, request_id=f"parallel-{i:03d}").json()["version"], range(12)
        ))
    assert sorted(versions) == list(range(1, 13))
    assert state(client)["snapshot"]["version"] == 12


def test_unknown_database_schema_is_preserved(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(RuntimeError, match="Unsupported"):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99

