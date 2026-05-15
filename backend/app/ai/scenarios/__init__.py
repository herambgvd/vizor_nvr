"""
Per-scenario Pydantic config validators.

Each scenario owns one schema. CameraAIConfig.config JSONB is validated
against the matching schema via `validate_config(slug, config)`.
"""

from __future__ import annotations

from typing import Any, Dict

from .people_counting import PeopleCountingConfig
from .frs import FRSConfig
from .ppe import PPEConfig

_REGISTRY: Dict[str, type] = {
    "people_counting": PeopleCountingConfig,
    "people_management": PeopleCountingConfig,  # alias used by seed.py
    "frs": FRSConfig,
    "face_recognition": FRSConfig,  # alias
    "ppe": PPEConfig,
    "ppe_compliance": PPEConfig,  # alias
}


def validate_config(slug: str, config: Any) -> Dict[str, Any]:
    """Return validated config dict for the scenario slug. Raises
    ValidationError on bad input."""
    cls = _REGISTRY.get(slug)
    if cls is None:
        # Unknown scenario — pass-through (frontend treats it generic)
        return config if isinstance(config, dict) else {}
    return cls(**(config or {})).model_dump(mode="json")


__all__ = ["validate_config", "PeopleCountingConfig", "FRSConfig", "PPEConfig"]
