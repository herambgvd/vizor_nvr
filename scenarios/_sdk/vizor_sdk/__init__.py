"""Vizor Scenario SDK — shared plumbing for AI scenario plugins.

A scenario plugin imports from here instead of copy-pasting Triton clients, NVR
auth, frame pulling, tracking, and rule engines. Write only the scenario-specific
detect + logic; the SDK provides the rest.

Public API:
    TritonClient                 — shared GPU inference transport
    NvrClient                    — manifest registration, camera catalogue, events
    service_token_guard          — FastAPI dep gating routes behind the NVR token
    allowed_camera_ids           — FastAPI dep reading the proxy camera scope
    build_app                    — standardized FastAPI scaffold (health + register)
    BaseConfig, env_bool         — common plugin config
    ScenarioEvent, make_event    — uniform event schema

Optional (heavier deps, import directly to keep the surface lazy):
    vizor_sdk.frames.FramePuller     — go2rtc/RTSP + NVDEC decode (needs cv2)
    vizor_sdk.tracker.ByteTracker    — multi-object ByteTrack/Kalman (pure numpy)
    vizor_sdk.rules                  — Zone / LineCrossCounter / DwellTracker / ZoneRuleEngine
    vizor_sdk.qdrant.QdrantStore     — vector upsert/search (needs qdrant-client)
"""
from __future__ import annotations

from .config import BaseConfig, env_bool
from .events import make_event
from .nvr import NvrClient, allowed_camera_ids, service_token_guard
from .triton import TritonClient
# Pure-numpy, no heavy deps — safe to export eagerly.
from .tracker import ByteTracker, assign_track_ids
from .rules import DwellTracker, LineCrossCounter, Zone, ZoneRuleEngine

__all__ = [
    "TritonClient",
    "NvrClient",
    "service_token_guard",
    "allowed_camera_ids",
    "BaseConfig",
    "env_bool",
    "make_event",
    "ByteTracker",
    "assign_track_ids",
    "Zone",
    "LineCrossCounter",
    "DwellTracker",
    "ZoneRuleEngine",
]

# build_app + ScenarioEvent need fastapi/pydantic (the "app" extra). Import them
# lazily so the SDK is usable in non-app contexts (e.g. a worker process).
try:
    from .app import build_app  # noqa: F401
    from .events import ScenarioEvent  # noqa: F401
    # Generic public dashboard + third-party ingest (needs fastapi).
    from .public import (  # noqa: F401
        SettingsStore, EventBus, build_public_router, build_ingest_router,
    )

    __all__ += [
        "build_app", "ScenarioEvent",
        "SettingsStore", "EventBus", "build_public_router", "build_ingest_router",
    ]
except Exception:  # noqa: BLE001
    pass

__version__ = "1.0.0"
