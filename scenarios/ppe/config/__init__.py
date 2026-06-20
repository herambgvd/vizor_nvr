"""Configuration package — re-exports every setting from settings.py so call
sites keep using `import config; config.X` (or `from config import X`)."""
from .settings import *  # noqa: F401,F403
from . import settings  # noqa: F401
