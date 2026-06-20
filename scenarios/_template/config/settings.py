"""Scenario config — extend the SDK BaseConfig with your scenario's knobs."""
from __future__ import annotations

from pathlib import Path

from vizor_sdk.config import BaseConfig


class Config(BaseConfig):
    # Identity — CHANGE THIS.
    SLUG = "template"

    # Triton model name(s) this scenario calls (must match a dir in
    # triton/model_repository/). CHANGE THIS.
    DETECTOR_MODEL = "yolo26"

    # Scenario thresholds.
    MIN_CONFIDENCE = 0.5

    # Manifest path (scenario.json sits at the package root, next to app.py).
    MANIFEST_PATH = Path(__file__).resolve().parent.parent / "scenario.json"


config = Config()
