from __future__ import annotations

import secrets
import time
from pathlib import Path
from typing import Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from backend.store import Conflict, InvalidTime, NotFound, Store, canonical, crc32

ROOT = Path(__file__).resolve().parents[1]


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    wake_at: AwareDatetime
    ramp_seconds: int = Field(default=1200, ge=1, le=2700, strict=True)
    hold_seconds: int = Field(default=1200, ge=1, le=3600, strict=True)
    peak_percent: int = Field(default=100, ge=1, le=100, strict=True)


class DeviceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    boot_id: str = Field(min_length=1, max_length=64)
    ack_version: int = Field(ge=0)
    ack_crc32: int = Field(ge=0, le=0xFFFFFFFF)
    state: Literal["needs_time", "idle", "armed", "ramping", "holding", "done", "fault"]
    brightness: float = Field(ge=0, le=100, allow_inf_nan=False)
    clock_valid: bool
    storage_ok: bool
    completed_occurrence_id: str = Field(default="", max_length=100)
    last_error: str = Field(default="", max_length=160)


def create_app(
    db_path: Path,
    admin_token: str,
    device_config: dict,
    clock: Callable[[], int] | None = None,
) -> FastAPI:
    if len(admin_token) < 16 or not device_config:
        raise ValueError("Configure an admin token and at least one device")
    if any(len(item["token"]) < 16 for item in device_config.values()):
        raise ValueError("Device tokens must have at least 16 characters")
    now = clock or (lambda: time.time_ns() // 1_000_000)
    store = Store(db_path)
    app = FastAPI(title="Smart Lamp MVP", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.store = store

    def authorized(token: str, authorization: str | None) -> None:
        if not secrets.compare_digest(authorization or "", f"Bearer {token}"):
            raise HTTPException(401, "Invalid access token")

    def admin(authorization: str | None = Header(default=None)) -> None:
        authorized(admin_token, authorization)

    def status() -> dict:
        snapshot = store.snapshot()
        expected_crc = crc32(canonical(snapshot))
        reports = store.devices()
        devices = []
        for identifier, config in device_config.items():
            report = reports.get(identifier, {})
            seen = report.get("seen_ms")
            online = seen is not None and 0 <= now() - seen < 12_000
            saved = bool(
                report.get("storage_ok")
                and report.get("ack_version") == snapshot["version"]
                and report.get("ack_crc32") == expected_crc
            )
            devices.append({
                **report, "device_id": identifier, "kind": config["kind"],
                "online": online, "saved": saved,
                "ready": online and saved and bool(report.get("clock_valid")),
            })
        hardware = [item for item in devices if item["kind"] == "esp8266"]
        return {
            "server_time_ms": now(), "snapshot": snapshot, "devices": devices,
            "hardware_saved": sum(item["saved"] for item in hardware),
            "hardware_ready": sum(item["ready"] for item in hardware),
            "hardware_target": len(hardware),
            "simulator_ready": sum(item["ready"] for item in devices if item["kind"] == "simulator"),
        }

    def serialize_input(payload: PlanInput) -> dict:
        wake = round(payload.wake_at.timestamp() * 1000)
        return {
            "request_id": payload.request_id, "wake_at_ms": wake,
            "ramp_seconds": payload.ramp_seconds, "hold_seconds": payload.hold_seconds,
            "peak_percent": payload.peak_percent,
        }

    def save(payload: PlanInput, plan_id: str | None = None) -> dict:
        # Store validates replay before mutation; a replay never reinstalls an old plan.
        try:
            snapshot, replayed = store.save_plan(serialize_input(payload), plan_id, now())
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except InvalidTime as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "plan_id": snapshot["plan_id"], "version": snapshot["version"],
            "replayed": replayed, "superseded": store.snapshot()["version"] != snapshot["version"],
            "sync_url": f"/api/v1/wake-plans/{snapshot['plan_id']}/sync",
        }

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "web" / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/health")
    def health():
        store.snapshot()
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/v1/state", dependencies=[Depends(admin)])
    def get_state():
        return status()

    @app.post("/api/v1/wake-plans", status_code=202, dependencies=[Depends(admin)])
    def create_plan(payload: PlanInput):
        return save(payload)

    @app.patch("/api/v1/wake-plans/{plan_id}", status_code=202, dependencies=[Depends(admin)])
    def update_plan(plan_id: str, payload: PlanInput):
        # MVP updates supply the whole plan, not an ambiguous partial date/time.
        return save(payload, plan_id)

    @app.delete("/api/v1/wake-plans/{plan_id}", dependencies=[Depends(admin)])
    def cancel_plan(plan_id: str):
        try:
            snapshot = store.cancel(plan_id)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"plan_id": plan_id, "version": snapshot["version"], "enabled": False}

    @app.get("/api/v1/wake-plans/{plan_id}/sync", dependencies=[Depends(admin)])
    def get_sync(plan_id: str):
        result = status()
        if result["snapshot"]["plan_id"] != plan_id:
            raise HTTPException(404, "Plan has been replaced")
        return result

    @app.post("/api/v1/devices/{device_id}/sync")
    def device_sync(device_id: str, report: DeviceReport, authorization: str | None = Header(default=None)):
        config = device_config.get(device_id)
        if config is None:
            raise HTTPException(404, "Unknown device")
        authorized(config["token"], authorization)
        store.record_device(device_id, report.model_dump(), now())
        text = canonical(store.snapshot())
        return {"server_time_ms": now(), "snapshot_json": text, "snapshot_crc32": crc32(text)}

    return app

