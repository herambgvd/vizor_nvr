"""Public Suspect Search dashboard router — UNAUTHENTICATED, aggregate only.

Built from the shared Vizor SDK: build_public_router wires GET /public/dashboard
+ /public/stream against the (psycopg2-backed, SDK-compatible) settings store, the
shared EventBus, and the per-scenario build_dashboard callable. Both routes 404
when the public toggle is off. No snapshots, no raw images — aggregate counts only.
"""
from __future__ import annotations

from vizor_sdk import build_public_router

from db.public_store import build_dashboard, bus, store

router = build_public_router(store, bus, build_dashboard)
