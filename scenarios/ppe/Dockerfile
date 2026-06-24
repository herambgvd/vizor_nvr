# Build CONTEXT is scenarios/ (so the shared SDK at ../_sdk is reachable):
#   docker build -f ppe/Dockerfile scenarios/
# Compose sets context: ./scenarios + dockerfile: ppe/Dockerfile.
#
# Slim base — the plugin is a thin Triton CLIENT (no in-process GPU inference),
# so it needs no CUDA libs. Inference runs on the shared Triton server. ffmpeg +
# libgl/libglib are for go2rtc frame decode + opencv.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ffmpeg/libgl for the legacy FramePuller + cv2; GStreamer runtime + GI typelibs for
# the async worker's production decoder (PPE_LIVE_ASYNC). plugins-base/good cover
# rtspsrc + decodebin + videoconvert (software H.264/H.265); plugins-bad adds
# depayloaders; libav is the ffmpeg bridge. gir1.2-* are the Gst/GstApp typelibs.
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 \
        libgirepository-1.0-1 libcairo2 \
        gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
        gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
        gstreamer1.0-libav \
    && rm -rf /var/lib/apt/lists/*

# PyGObject into the image's interpreter. Pin 3.50.0 — newer releases require
# girepository-2.0 (gobject-introspection >=1.80), but the bookworm-slim base ships
# 1.74 (girepository-1.0). Build deps purged afterwards to keep the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgirepository1.0-dev libcairo2-dev pkg-config gcc python3-dev \
    && pip install --no-cache-dir "PyGObject==3.50.0" \
    && apt-get purge -y libgirepository1.0-dev libcairo2-dev pkg-config gcc python3-dev \
    && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Shared Vizor Scenario SDK (own layer — caches well). [app] = fastapi/pydantic,
# [triton] = tritonclient[http]. NO ultralytics/torch — inference is on Triton.
COPY _sdk /sdk
RUN pip install --no-cache-dir "/sdk[app,triton]"

COPY ppe/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application — thin entrypoint + one package per concern.
COPY ppe/scenario.json ppe/app.py ppe/alembic.ini ./
COPY ppe/config ./config
COPY ppe/db ./db
COPY ppe/schemas ./schemas
COPY ppe/inference ./inference
COPY ppe/pipeline ./pipeline
COPY ppe/registration ./registration
COPY ppe/deps ./deps
COPY ppe/live ./live
COPY ppe/routers ./routers
# DINOv2 verifier linear heads (tiny npz; the backbone is on Triton).
COPY ppe/models ./models

EXPOSE 8092
CMD ["python", "app.py"]
