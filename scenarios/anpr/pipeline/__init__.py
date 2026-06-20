"""ANPR pipeline — the ported POC plate logic + Milesight-parity features.

  * types        — Detection dataclass + YOLO letterbox / un-letterbox.
  * voting       — per-track plate consensus (VehicleSession.vote, ported verbatim;
                   multi-track manager fixes the POC single-lane bug).
  * plate_text   — normalize + configurable PLATE_REGEX gate (ported).
  * enhance      — CLAHE low-light enhancement (ported).
  * roi          — per-camera capture-zone gating on the plate box.
  * motion       — direction (LineCrossCounter) + speed ESTIMATE (calibrated only).
"""
from .enhance import enhance_lowlight, is_low_light  # noqa: F401
from .motion import MotionEstimator  # noqa: F401
from .plate_text import compile_regex, gate_read, normalize  # noqa: F401
from .roi import build_roi, plate_in_roi  # noqa: F401
from .types import Detection, letterbox, unletterbox_box  # noqa: F401
from .voting import TrackVoteManager, VehicleSession  # noqa: F401
