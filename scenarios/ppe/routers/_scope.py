"""Camera-scope helper shared by the read routers (S1 camera-scope auth)."""
from __future__ import annotations

from typing import Optional


from sqlalchemy import or_


def apply_camera_scope(conds: list, column, requested, allowed: Optional[list[str]]) -> bool:
    """Constrain a query to cameras the operator may read.

    `allowed` comes from the proxy (deps.allowed_camera_ids):
      None  → no scoping (called outside the proxy) — apply only the requested filter.
      []    → scoped to nothing → signal "return no rows" (returns False).
      [...] → intersect the requested cameras with the allowed set.
    Returns False when the effective scope is empty (route should short-circuit).

    Video-upload events use a synthetic camera_id of the form "video:<job_id>" — they
    are not real NVR cameras and so never appear in `allowed`, but the operator who ran
    the analysis must see them. They are always in-scope (OR'd in) unless a specific
    camera filter was requested that excludes them."""
    req = list(requested) if requested else None
    if allowed is None:
        if req:
            conds.append(column.in_(req))
        return True
    effective = [c for c in req if c in set(allowed)] if req else list(allowed)
    # Always allow video-job events through (operator's own uploads), unless the request
    # explicitly filters to specific non-video cameras.
    include_video = not req or any(str(c).startswith("video:") for c in req)
    if not effective and not include_video:
        return False
    clause = column.in_(effective) if effective else None
    if include_video:
        vid = column.like("video:%")
        clause = or_(clause, vid) if clause is not None else vid
    conds.append(clause)
    return True
