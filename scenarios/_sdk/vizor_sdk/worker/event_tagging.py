"""Standardised metadata tags for every emitted Event.

Every scenario should stamp its events with a small, consistent set
of routing/debug fields so downstream consumers (UI, reports,
contract tests, audit) can branch on them without each scenario
inventing its own shape.

Tags we standardise:

  * ``frame_id``      — UUID generated once per processed frame; lets
                         the UI correlate multi-event frames.
  * ``model_version`` — Triton plan / engine identifier (e.g.
                         ``"scrfd_2.5g@fp16"``). Stamped per-event so a
                         canary model swap is visible in the event
                         stream.
  * ``scenario_name`` / ``scenario_version`` — pulled from the pipeline.

This module gives a single :func:`tag_event` helper that mutates an
already-built Event in place. Scenarios call it just before yielding.

Why not put these on the base ``Event`` model? The pydantic model is
shared with the backend; bumping it without coordinating both repos
breaks. Stamping into ``data["meta"]`` keeps the wire format additive
and the backend can ignore unknown keys.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from .protocol import Event

logger = logging.getLogger("vizor.worker.event_tagging")


def new_frame_id() -> str:
    """Return a fresh frame UUID. Callers should generate ONE per
    processed frame and reuse it for every event that frame produces."""
    return uuid.uuid4().hex


def tag_event(
    event: Event,
    *,
    frame_id: Optional[str] = None,
    model_version: Optional[str] = None,
    scenario_name: Optional[str] = None,
    scenario_version: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> Event:
    """Attach standard metadata under ``event.data["meta"]``.

    Mutates ``event`` and returns it for convenience. Missing fields
    are left untouched so partial calls (only ``frame_id``, only
    ``model_version``) are valid.
    """
    if event.data is None:
        event.data = {}
    meta = event.data.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        event.data["meta"] = meta
    if frame_id is not None:
        meta["frame_id"] = frame_id
    if model_version is not None:
        meta["model_version"] = model_version
    if scenario_name is not None:
        meta["scenario_name"] = scenario_name
    if scenario_version is not None:
        meta["scenario_version"] = scenario_version
    if extra:
        meta.update(extra)
    return event
