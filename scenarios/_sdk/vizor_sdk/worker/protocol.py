"""Protocol schemas for the Vizor AI worker framework (single-tenant).

All messages between the control plane and the workers are Pydantic v2 models so
they validate, serialize and round-trip through Redis streams without ambiguity.

Streams (by convention):
    ai:{use_case}:control   — control plane -> worker (Command)
    ai:{use_case}:status    — worker -> control plane (Status heartbeat)
    ai:events               — worker -> bridge (Event, all use-cases)

Single-tenant note: vizor-gpu carried a `tenant_id` on every message for per-tenant
isolation. nvr is single-tenant, so it's dropped here — one camera namespace, fixed
collection/bucket names.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _JsonModel(BaseModel):
    """Base with compact JSON (de)serialization helpers for Redis XADD."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    def to_json(self) -> str:
        return self.model_dump_json()

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())

    @classmethod
    def from_json(cls, raw: str | bytes):
        return cls.model_validate_json(raw)

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        return cls.model_validate(data)


# ── Command — control plane -> worker ──────────────────────────────────────
CommandAction = Literal["start_camera", "stop_camera", "update_config", "reload"]


class Command(_JsonModel):
    """Control command. `config` is free-form per scenario (sub_features, roi,
    thresholds, fps, ...). `device_id` is the nvr camera_id."""

    action: CommandAction
    device_id: str
    rtsp_url: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    request_id: UUID = Field(default_factory=uuid4)
    issued_at: datetime = Field(default_factory=_utcnow)


# ── Event — worker -> bridge ───────────────────────────────────────────────
class EventMedia(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_key: str | None = None
    clip_key: str | None = None


class Event(_JsonModel):
    """A detection / recognition event. The events bridge maps this onto nvr's
    `record_event()` (FRSEvent + attendance + transit + SSE)."""

    use_case: str
    sub_feature: str
    device_id: str
    event_type: str
    timestamp: datetime
    data: dict[str, Any] = Field(default_factory=dict)
    media: EventMedia = Field(default_factory=EventMedia)
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=_utcnow)


# ── Status — worker -> control plane (heartbeat) ───────────────────────────
class Status(_JsonModel):
    worker_id: str
    use_case: str
    healthy: bool
    # "warming" | "healthy" | "degraded" | "unhealthy"
    phase: str = "healthy"
    active_cameras: list[str] = Field(default_factory=list)
    gpu_util: float | None = None
    emitted_at: datetime = Field(default_factory=_utcnow)


# ── ScenarioManifest — catalog entry ───────────────────────────────────────
ServiceRequirement = Literal["triton", "qdrant", "rustfs", "go2rtc", "redis"]


class SubFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    default_enabled: bool = False
    description: str = ""


class ScenarioManifest(_JsonModel):
    use_case: str
    slug: str
    display_name: str
    description: str
    icon: str
    sub_features: list[SubFeature] = Field(default_factory=list)
    control_stream: str
    worker_image: str
    requires: list[ServiceRequirement] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
