from __future__ import annotations

from fastapi import APIRouter

from services.runtime import (
    cancel_job,
    create_index_job,
    create_search_job,
    get_job,
    get_results,
    list_jobs,
    result_thumbnail,
    search_similar,
)

router = APIRouter(tags=["jobs"])
router.add_api_route("/jobs", list_jobs, methods=["GET"])
router.add_api_route("/jobs/index", create_index_job, methods=["POST"])
router.add_api_route("/jobs/search", create_search_job, methods=["POST"])
router.add_api_route("/jobs/{job_id}", get_job, methods=["GET"])
router.add_api_route("/jobs/{job_id}", cancel_job, methods=["DELETE"])
router.add_api_route("/jobs/{job_id}/results", get_results, methods=["GET"])
router.add_api_route("/results/{result_id}/search-similar", search_similar, methods=["POST"])
router.add_api_route("/results/{result_id}/thumbnail", result_thumbnail, methods=["GET"])
