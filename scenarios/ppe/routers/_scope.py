"""Camera-scope helper shared by the read routers (S1 camera-scope auth)."""
from __future__ import annotations

from typing import Optional


def apply_camera_scope(conds: list, column, requested, allowed: Optional[list[str]]) -> bool:
    """Constrain a query to cameras the operator may read.

    `allowed` comes from the proxy (deps.allowed_camera_ids):
      None  → no scoping (called outside the proxy) — apply only the requested filter.
      []    → scoped to nothing → signal "return no rows" (returns False).
      [...] → intersect the requested cameras with the allowed set.
    Returns False when the effective scope is empty (route should short-circuit)."""
    req = list(requested) if requested else None
    if allowed is None:
        if req:
            conds.append(column.in_(req))
        return True
    effective = [c for c in req if c in set(allowed)] if req else list(allowed)
    if not effective:
        return False
    conds.append(column.in_(effective))
    return True
