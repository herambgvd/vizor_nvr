"""Server-side text-to-speech.

Browser SpeechSynthesis is unreliable across kiosks/voice-packs, so the spoken FRS
alerts ("Authorized Heramb Mishra", etc.) are synthesised on the server with
espeak-ng and streamed back as WAV. The frontend just plays the returned audio via
a normal <audio> element (allowed after the operator's first gesture), so it works
the same on every browser regardless of installed voices.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, Query, Response

router = APIRouter()

_CACHE = Path(os.getenv("FRS_TTS_CACHE", "/tmp/frs_tts"))
_CACHE.mkdir(parents=True, exist_ok=True)
_VOICE = os.getenv("FRS_TTS_VOICE", "en-us")
_ESPEAK = shutil.which("espeak-ng") or shutil.which("espeak")


@router.get("/tts")
def tts(text: str = Query(..., max_length=300)) -> Response:
    """Synthesise `text` to a WAV. Cached by content hash so repeated phrases
    ("Authorized <name>") don't re-synthesise every event."""
    text = (text or "").strip()
    if not text:
        return Response(status_code=204)
    if _ESPEAK is None:
        # No engine in the image — tell the client so it can beep instead.
        return Response(status_code=503)
    key = hashlib.sha1(f"{_VOICE}:{text}".encode()).hexdigest()[:20]
    out = _CACHE / f"{key}.wav"
    if not out.exists():
        try:
            subprocess.run(
                [_ESPEAK, "-v", _VOICE, "-s", "165", "-w", str(out), text],
                check=True, timeout=10,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001
            return Response(status_code=503)
    try:
        data = out.read_bytes()
    except Exception:  # noqa: BLE001
        return Response(status_code=503)
    return Response(content=data, media_type="audio/wav",
                    headers={"Cache-Control": "public, max-age=86400"})
