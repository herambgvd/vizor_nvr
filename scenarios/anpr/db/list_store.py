"""Whitelist / blacklist store + matcher.

PER-SCENARIO GLOBAL list (one list across all ANPR cameras). On each plate read
the live worker calls `match_plate(normalized)` to tag the read with its list
membership (whitelist / blacklist) and raise a high-severity event on a blacklist
hit. Plates are stored + matched normalised (uppercase, A-Z0-9 only)."""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import select

from db import session
from db.models import ANPRPlateList
from schemas import utcnow

_NORM_RE = re.compile(r"[^A-Z0-9]")


def normalize_plate(text: str) -> str:
    """Uppercase + strip everything that isn't A-Z/0-9. Single normalisation used
    everywhere (OCR output, list entries, matcher) so comparisons are exact."""
    return _NORM_RE.sub("", (text or "").upper())


def match_plate(plate: str, now=None) -> Optional[dict]:
    """Return the active list entry matching `plate` (already normalised), or None.

    Blacklist wins over whitelist if a plate is somehow on both. An entry only
    matches inside its [valid_from, valid_to] window (NULL bounds = unbounded)."""
    norm = normalize_plate(plate)
    if not norm:
        return None
    now = now or utcnow()
    with session() as s:
        rows = s.execute(
            select(ANPRPlateList).where(ANPRPlateList.plate == norm)
        ).scalars().all()
    best = None
    for r in rows:
        if r.valid_from is not None and now < r.valid_from:
            continue
        if r.valid_to is not None and now > r.valid_to:
            continue
        entry = {"id": r.id, "list_type": r.list_type, "label": r.label}
        if r.list_type == "blacklist":
            return entry  # blacklist takes precedence immediately
        best = best or entry
    return best
