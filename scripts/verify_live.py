"""Exercise the running local backend and simulator; replaces the current test plan."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8"))
    with httpx.Client(base_url="http://127.0.0.1:8765", timeout=3,
                      headers={"Authorization": f"Bearer {config['admin_token']}"}) as client:
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        def get_device():
            state = request("GET", "/api/v1/state")
            device = next(item for item in state["devices"] if item["device_id"] == "sim-01")
            return state, device

        def wait_for(predicate, timeout=8):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                state, device = get_device()
                if predicate(state, device):
                    return state, device
                time.sleep(0.2)
            raise AssertionError("Live simulator did not reach the expected state")

        payload = {
            "request_id": "live_" + uuid4().hex,
            "wake_at": datetime.fromtimestamp(time.time() + 12, timezone.utc).isoformat(),
            "ramp_seconds": 6, "hold_seconds": 5, "peak_percent": 100,
        }
        created = request("POST", "/api/v1/wake-plans", json=payload)
        identifier = created["plan_id"]
        wait_for(lambda _, dev: dev["saved"] and dev["ack_version"] == created["version"])
        payload.update(request_id="live_" + uuid4().hex, peak_percent=60)
        updated = request("PATCH", f"/api/v1/wake-plans/{identifier}", json=payload)
        print(f"Created and updated live plan: version {updated['version']}, peak 60%", flush=True)
        observed = []
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            _, device = get_device()
            if device.get("ack_version") == updated["version"]:
                item = {"state": device["state"], "brightness": round(device["brightness"], 2)}
                if not observed or observed[-1] != item:
                    observed.append(item)
                    print(item, flush=True)
                if device["state"] == "done":
                    break
            time.sleep(0.2)
        assert {"armed", "ramping", "holding", "done"} <= {item["state"] for item in observed}
        assert any(0 < item["brightness"] < 60 for item in observed)
        assert any(item == {"state": "holding", "brightness": 60.0} for item in observed)
        payload.update(
            request_id="live_" + uuid4().hex,
            wake_at=datetime.fromtimestamp(time.time() + 20, timezone.utc).isoformat(),
        )
        changed = request("POST", "/api/v1/wake-plans", json=payload)
        wait_for(lambda _, dev: dev["saved"] and dev["ack_version"] == changed["version"])
        cancelled = request("DELETE", f"/api/v1/wake-plans/{changed['plan_id']}")
        final, device = wait_for(lambda _, dev: dev["saved"] and dev["state"] == "idle"
                                and dev["ack_version"] == cancelled["version"])
        result = {
            "tested_at": datetime.now(timezone.utc).isoformat(),
            "transport": "real HTTP on localhost, virtual device sim-01",
            "observed": observed, "cancel_version": cancelled["version"],
            "cancel_confirmed": device["saved"], "final_brightness": device["brightness"],
            "hardware_saved": final["hardware_saved"],
            "hardware_verified": False,
        }
        (ROOT / "data" / "live-verification.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("PASS: real HTTP create/update, acknowledged save, ramp/hold/done, cancel/off.", flush=True)


if __name__ == "__main__":
    main()
