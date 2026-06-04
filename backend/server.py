# =============================================================================
# Vizor NVR — Server Entry Point (thin wrapper)
# =============================================================================
# The actual application lives in app/main.py
# Run with:  python server.py
#        or: uvicorn app.main:app --reload
# =============================================================================

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# Re-export the app so `uvicorn server:app` still works
from app.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("ENV", "development") == "development"

    logging.info(f"Starting Vizor NVR on {host}:{port}")
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=["app"] if reload else None,
        log_level="info",
    )
