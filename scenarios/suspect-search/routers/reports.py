from __future__ import annotations

from fastapi import APIRouter

from services.runtime import reports_summary

router = APIRouter(tags=["reports"])
router.add_api_route("/reports/summary", reports_summary, methods=["GET"])
