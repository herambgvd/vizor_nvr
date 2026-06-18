"""Self-registration: POST the manifest to the NVR scenario catalog on boot."""
from __future__ import annotations

import json
import time

import requests

from config import MANIFEST_PATH, SCENARIO_SLUG, VIZOR_API_KEY, VIZOR_BASE_URL


def load_manifest() -> dict:
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    m["slug"] = SCENARIO_SLUG
    return m


def register_on_boot() -> None:
    if not VIZOR_API_KEY:
        print("[frs] VIZOR_API_KEY missing; manifest registration skipped", flush=True)
        return
    headers = {"Content-Type": "application/json", "X-Vizor-API-Key": VIZOR_API_KEY}
    url = f"{VIZOR_BASE_URL}/ai/scenarios/register"
    for attempt in range(1, 16):
        try:
            resp = requests.post(url, json=load_manifest(), headers=headers, timeout=10)
            resp.raise_for_status()
            print(f"[frs] registered manifest ({resp.status_code})", flush=True)
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[frs] registration attempt {attempt} failed: {exc}", flush=True)
            time.sleep(min(2 * attempt, 20))
