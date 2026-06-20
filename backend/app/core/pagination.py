# =============================================================================
# Pagination — one standard for every list endpoint.
# =============================================================================
# Every paginated list endpoint takes the SAME query params and returns the SAME
# envelope, so the frontend has a single contract:
#
#   GET /api/<resource>?limit=50&offset=0   ->   {
#       "items":  [...],
#       "total":  123,        # total rows matching the filter (for the count)
#       "limit":  50,         # echoed page size
#       "offset": 0,          # echoed start offset
#   }
#
# Use `PageParams` as a FastAPI dependency for the query params, and `Page[T]`
# (or `paginated(...)`) to build the response.
# =============================================================================
from __future__ import annotations

from typing import Generic, List, Sequence, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")

# Sensible bounds — protect the DB from unbounded scans.
DEFAULT_LIMIT = 50
MAX_LIMIT = 1000


class PageParams:
    """Standard pagination query params. Use as a dependency:

        @router.get("/things")
        async def list_things(page: PageParams = Depends()):
            ...
    """

    def __init__(
        self,
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description="Page size"),
        offset: int = Query(0, ge=0, description="Rows to skip"),
    ):
        self.limit = limit
        self.offset = offset


class Page(BaseModel, Generic[T]):
    """Standard list envelope returned by every paginated endpoint."""

    items: List[T]
    total: int
    limit: int
    offset: int


def paginated(items: Sequence[T], total: int, params: PageParams) -> dict:
    """Build the standard envelope as a plain dict (works with or without a
    response_model)."""
    return {
        "items": list(items),
        "total": int(total),
        "limit": params.limit,
        "offset": params.offset,
    }
