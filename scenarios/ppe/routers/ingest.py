"""Third-party PPE event ingest router — built from the shared Vizor SDK.

build_ingest_router wires POST /ingest/event against the singleton settings store
(ingest key gate) and the per-scenario ingest() callable, which records the posted
event via the shared record_event path. Gated by the operator-minted ingest key
(header x-scn-ingest-key).
"""
from __future__ import annotations

from vizor_sdk import build_ingest_router

from db.public_store import ingest, store

router = build_ingest_router(store, ingest, key_header="x-scn-ingest-key")
