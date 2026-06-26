#!/usr/bin/env python3
"""Run FRS on a recorded video using the SAME platform engine (Triton scrfd/arcface,
qdrant gallery, FRS Postgres). Detects + recognises faces inside an ROI, saves a real
FRS event per recognised/unknown sighting, and writes an annotated MP4.

Runs INSIDE the frs container (so it shares the engine/gallery/DB):
    docker exec gvd_ai_frs python -m tools.video_frs \
        --video /work/test.mp4 --out /work/test_annotated.mp4 --roi /work/roi.json \
        --camera-id video-test --camera-name "SMCC Gate" --fps 5

ROI json is the draw_roi.py output (uses the `frac` block). Pass --no-roi for full frame.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime

import cv2
import numpy as np

sys.path.insert(0, "/app")
from db.engine import init_db
from recognition import service as svc
from db import session
from db.models import FRSEvent
from qdrant import store as qdrant_store


def roi_polygons(roi_path: str | None):
    if not roi_path:
        return None
    with open(roi_path) as f:
        r = json.load(f)
    fr = r["frac"]
    x, y, w, h = fr["x"], fr["y"], fr["w"], fr["h"]
    return [{"points": [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]}]


def sink_event(camera_id, camera_name, person_id, person_name, score, snap_path,
               event_type, ts, det_conf, bbox_frac):
    with session() as s:
        ev = FRSEvent(
            id=str(uuid.uuid4()),
            camera_id=camera_id,
            event_type=event_type,
            severity="info",
            person_id=person_id,
            confidence=float(score or 0.0),
            bbox=bbox_frac,
            snapshot_path=snap_path,
            attributes={
                "face_snapshot": snap_path,
                "camera_name": camera_name,
                "det_confidence": round(float(det_conf or 0.0), 3),
                "source": "video:test",
            },
            triggered_at=ts,
        )
        s.add(ev)
        s.commit()
        return ev.id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--roi", default=None)
    ap.add_argument("--no-roi", action="store_true")
    ap.add_argument("--camera-id", default="video-test")
    ap.add_argument("--camera-name", default="Video Test")
    ap.add_argument("--fps", type=float, default=5.0, help="analyse N frames/sec")
    ap.add_argument("--min-conf", type=float, default=0.45, help="match threshold")
    ap.add_argument("--min-face-px", type=int, default=40,
                    help="min face size px (CCTV faces are small; lower than live default 80)")
    ap.add_argument("--min-sharp", type=float, default=15.0)
    ap.add_argument("--det-conf", type=float, default=0.5)
    ap.add_argument("--cooldown", type=float, default=5.0,
                    help="seconds between repeat events for the same person")
    ap.add_argument("--save-events", action="store_true",
                    help="actually write FRS events to the DB")
    args = ap.parse_args()

    init_db()
    roi = None if args.no_roi else roi_polygons(args.roi)
    snap_dir = "/data/frs/snapshots"
    os.makedirs(snap_dir, exist_ok=True)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {args.video}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(src_fps / args.fps)))
    print(f"video {W}x{H} {src_fps:.0f}fps {total} frames; analysing every {step}th "
          f"frame; roi={'on' if roi else 'off'}; save_events={args.save_events}")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(args.out, fourcc, src_fps, (W, H))

    last_seen: dict[str, float] = {}
    n = 0
    recog = unknown = 0
    last_faces = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        vts = n / src_fps  # video timestamp (s)
        if n % step == 0:
            res = svc.analyze_frame(frame, min_conf=args.min_conf, roi=roi,
                                    gate_quality=True, det_conf=args.det_conf,
                                    min_face_px=args.min_face_px,
                                    min_sharpness=args.min_sharp)
            last_faces = []
            for fc in res.get("faces", []):
                bb = [int(round(v)) for v in fc["bbox_px"]]
                m = fc.get("match") or {}
                pid = m.get("person_id")
                pname = m.get("person_name")
                score = float(m.get("confidence") or 0.0)
                det = float(fc.get("confidence") or 0.0)
                etype = "face_recognized" if pid else "face_unknown"
                label = (f"{pname} {score*100:.0f}%" if pid
                         else f"Unknown {det*100:.0f}%")
                color = (0, 200, 0) if pid else (0, 165, 255)
                last_faces.append((bb, label, color))
                # event (cooldown per person/unknown)
                key = pid or "__unknown__"
                now_m = time.monotonic()
                if now_m - last_seen.get(key, 0) >= args.cooldown:
                    last_seen[key] = now_m
                    snap_path = ""
                    if args.save_events:
                        crop = frame[max(0, bb[1]):bb[3], max(0, bb[0]):bb[2]]
                        sid = str(uuid.uuid4())
                        fn = f"{sid}_face.jpg"
                        cv2.imwrite(os.path.join(snap_dir, fn), crop)
                        snap_path = f"/snapshot?key=live:{sid}_face"
                        ts = datetime.utcnow()
                        sink_event(args.camera_id, args.camera_name, pid, pname,
                                   score, snap_path, etype, ts, det,
                                   {"x": bb[0]/W, "y": bb[1]/H,
                                    "w": (bb[2]-bb[0])/W, "h": (bb[3]-bb[1])/H})
                    if pid:
                        recog += 1
                    else:
                        unknown += 1
        # draw the last analysis on EVERY frame (so output is smooth)
        if roi:
            for poly in roi:
                pts = np.array([[int(p[0]*W), int(p[1]*H)] for p in poly["points"]], np.int32)
                cv2.polylines(frame, [pts], True, (255, 255, 0), 2)
        for bb, label, color in last_faces:
            cv2.rectangle(frame, (bb[0], bb[1]), (bb[2], bb[3]), color, 2)
            cv2.rectangle(frame, (bb[0], bb[1]-26), (bb[0]+max(120, len(label)*11), bb[1]), color, -1)
            cv2.putText(frame, label, (bb[0]+4, bb[1]-7),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        writer.write(frame)
        n += 1
        if n % 250 == 0:
            print(f"  {n}/{total} frames | recog={recog} unknown={unknown}")

    cap.release()
    writer.release()
    print(f"DONE. frames={n} recognised_events={recog} unknown_events={unknown}")
    print(f"annotated video -> {args.out}")


if __name__ == "__main__":
    main()
