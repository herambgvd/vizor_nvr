"""Self-registration: POST the manifest to the NVR scenario catalog on boot.

Backed by the shared SDK NvrClient (same backoff/retry).
"""
from __future__ import annotations

from vizor_sdk import NvrClient

from config import MANIFEST_PATH, SCENARIO_SLUG, VIZOR_API_KEY, VIZOR_BASE_URL


def register_on_boot() -> None:
    NvrClient(VIZOR_BASE_URL, VIZOR_API_KEY, SCENARIO_SLUG).register_manifest(MANIFEST_PATH)
