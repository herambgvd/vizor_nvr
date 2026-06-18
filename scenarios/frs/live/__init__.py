"""Live recognition — per-camera RTSP workers driven by the NVR's enabled-camera
catalogue. Turning the scenario ON for a camera starts a worker that pulls frames
from go2rtc, recognises faces, and emits FRS events + attendance in real time."""
from .manager import start_live_manager  # noqa: F401
