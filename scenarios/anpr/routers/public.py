"""Public ANPR dashboard router — UNAUTHENTICATED, aggregate analytics only.

Built from the shared Vizor SDK: build_public_router wires GET /public/dashboard
+ /public/stream against the singleton settings store, the shared EventBus, and
the per-scenario build_dashboard callable. Both routes 404 when the public toggle
is off. No snapshots, no raw images. Plate text only when public_show_names.
"""
from __future__ import annotations

from vizor_sdk import build_public_router

from db.events import bus
from db.public_store import build_dashboard, store

router = build_public_router(store, bus, build_dashboard)
