"""ANPR plugin configuration — re-export the env-bound module-level settings.

Mirrors the PPE plugin: `import config` gives a flat namespace of constants the
rest of the plugin reads (PORT, model names, thresholds, DB url, paths)."""
from .settings import *  # noqa: F401,F403
from .settings import (  # noqa: F401  explicit re-export for tooling
    ANPR_DATABASE_URL,
    DATA_PATH,
    MANIFEST_PATH,
    PORT,
    SCENARIO_SLUG,
    VERSION,
)
