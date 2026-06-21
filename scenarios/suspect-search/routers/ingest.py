"""Third-party Suspect Search ingest router — built from the shared Vizor SDK.

build_ingest_router wires POST /ingest/event against the settings store (ingest
key gate) and the per-scenario ingest() callable, which records an external
sighting into the SS `results` table. Gated by the operator-minted ingest key
(header x-scn-ingest-key).

Note: SS ingest is a best-effort convenience (SS is a forensic search tool, not a
live event feed); see db/public_store.ingest for the honesty caveat.
"""
from __future__ import annotations

from vizor_sdk import build_ingest_router

from db.public_store import ingest, store

router = build_ingest_router(store, ingest, key_header="x-scn-ingest-key")
