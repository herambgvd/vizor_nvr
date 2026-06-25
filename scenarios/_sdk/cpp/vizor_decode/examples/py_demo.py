#!/usr/bin/env python3
"""py_demo — open RTSP via vizor_decode C++ module, decode N frames.

Usage:
    python3 examples/py_demo.py <rtsp_url> [--frames 50] [--no-hwaccel]
    python3 examples/py_demo.py <rtsp_url> --save first.png

Validates:
    1. Module imports
    2. Decoder opens RTSP
    3. next_frame returns numpy ndarray of correct shape + dtype
    4. NVDEC path active when --no-hwaccel NOT set
    5. Optional: writes first frame to PNG (needs OpenCV)
"""

import argparse
import sys
import time
from typing import Optional

import numpy as np

import vizor_decode as vd


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--frames", type=int, default=50)
    ap.add_argument("--no-hwaccel", action="store_true")
    ap.add_argument("--save", type=str, default="",
                    help="path to save first frame as PNG (needs cv2)")
    args = ap.parse_args(argv)

    print(f"[py_demo] opening {args.url} hwaccel={not args.no_hwaccel}")
    dec = vd.Decoder(args.url, hwaccel=not args.no_hwaccel)
    print(f"[py_demo] decoder ready hw={dec.is_hw_decoder}")

    saved = not args.save
    t0 = time.monotonic()
    got = 0

    for _ in range(args.frames):
        frame = dec.next_frame()
        if frame is None:
            print("[py_demo] EOF")
            break
        # First sanity check — confirm zero-copy + shape.
        if got == 0:
            print(f"[py_demo] first frame shape={frame.shape} "
                  f"dtype={frame.dtype} contiguous={frame.flags['C_CONTIGUOUS']}")
        got += 1

        if not saved:
            try:
                import cv2  # noqa: WPS433
                cv2.imwrite(args.save, frame)
                print(f"[py_demo] saved {args.save}")
                saved = True
            except ImportError:
                print("[py_demo] cv2 not available — skip save")
                saved = True

        if got % 30 == 0:
            elapsed = time.monotonic() - t0
            print(f"[py_demo] frames={got} fps={got/elapsed:.1f} "
                  f"packets={dec.packets_read}")

    elapsed = time.monotonic() - t0
    print(f"[py_demo] DONE frames={got} fps={got/elapsed:.1f} "
          f"hw={dec.is_hw_decoder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
