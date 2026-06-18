from __future__ import annotations

from fastapi import Header, HTTPException

from config.settings import VIZOR_SERVICE_TOKEN


def require_service_token(x_vizor_service_token: str | None = Header(None)) -> None:
    if VIZOR_SERVICE_TOKEN and x_vizor_service_token != VIZOR_SERVICE_TOKEN:
        raise HTTPException(401, "invalid service token")
