"""Self-registration: POST the manifest to the NVR scenario catalog on boot.

Backed by the shared SDK NvrClient (same backoff/retry). `load_manifest` and
`register_on_boot` keep their names so app.py is unchanged.
"""
from __future__ import annotations

import json

from vizor_sdk import NvrClient

from config import MANIFEST_PATH, SCENARIO_SLUG, VIZOR_API_KEY, VIZOR_BASE_URL


def load_manifest() -> dict:
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    m["slug"] = SCENARIO_SLUG
    return m


def register_on_boot() -> None:
    NvrClient(VIZOR_BASE_URL, VIZOR_API_KEY, SCENARIO_SLUG).register_manifest(MANIFEST_PATH)
