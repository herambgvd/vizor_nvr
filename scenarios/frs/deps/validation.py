"""Input-validation helpers (defence-in-depth, don't trust client-declared types)."""
from __future__ import annotations

# Magic-number signatures for the image formats we accept. A declared
# Content-Type header is trivially spoofable, so we verify the actual bytes
# before storing/processing an upload.
_IMAGE_SIGNATURES = (
    b"\xff\xd8\xff",                      # JPEG
    b"\x89PNG\r\n\x1a\n",                 # PNG
    b"RIFF",                             # WEBP (RIFF....WEBP — checked below)
)


def looks_like_image(data: bytes) -> bool:
    """True if `data` starts with a JPEG/PNG/WEBP signature."""
    if not data or len(data) < 12:
        return False
    if data[:3] == b"\xff\xd8\xff":                      # JPEG
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":                 # PNG
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":    # WEBP
        return True
    return False
