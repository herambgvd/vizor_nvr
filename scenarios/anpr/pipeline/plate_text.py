"""Plate-text gating: normalize + regex match (ported from final_poc/anpr.py).

The POC, per OCR read, does:
    txt = re.sub(r"[^A-Z0-9]", "", txt.upper())
    m = PLATE_REGEX.search(txt)
    keep if m and conf >= ocr_conf
and uses m.group() (the matched substring) as the plate. PLATE_REGEX defaults to
the Indian format (incl. BH-series) but is CONFIGURABLE per scenario (region).

`gate_read` returns the accepted plate text (the regex match, or the normalized
raw text when allow_raw is set) or None when the read should be dropped."""
from __future__ import annotations

import re
from typing import Optional

_NORM_RE = re.compile(r"[^A-Z0-9]")


def normalize(text: str) -> str:
    """Uppercase + strip to A-Z0-9 (POC: re.sub(r"[^A-Z0-9]", "", txt.upper()))."""
    return _NORM_RE.sub("", (text or "").upper())


def compile_regex(pattern: str):
    """Compile the configured plate regex; fall back to None (no regex) on a bad
    operator-supplied pattern rather than crashing the worker."""
    try:
        return re.compile(pattern)
    except Exception:  # noqa: BLE001
        return None


def gate_read(text: str, conf: float, ocr_conf: float, regex,
              allow_raw: bool = False) -> Optional[str]:
    """Apply the POC gate to one OCR read. `conf` and `ocr_conf` are on the SAME
    scale (both 0..100 from the OCR, or both 0..1 — the worker keeps them aligned).

    Returns the accepted plate string or None:
      * conf below the OCR gate          -> None
      * regex matches                    -> the matched substring (m.group())
      * no match but allow_raw + nonempty -> the normalized raw text
      * otherwise                        -> None (dropped, POC behaviour)
    """
    norm = normalize(text)
    if not norm:
        return None
    if conf < ocr_conf:
        return None
    if regex is not None:
        m = regex.search(norm)
        if m:
            return m.group()
    if allow_raw:
        return norm
    return None
