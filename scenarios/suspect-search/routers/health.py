from __future__ import annotations

from fastapi import APIRouter

from services.runtime import deep_health, health

router = APIRouter(tags=["health"])
router.add_api_route("/health", health, methods=["GET"])
router.add_api_route("/health/deep", deep_health, methods=["POST"])
