# Build CONTEXT is scenarios/ (so the shared SDK at ../_sdk is reachable):
#   docker build -f frs/Dockerfile scenarios/
# Compose sets context: ./scenarios + dockerfile: frs/Dockerfile.
#
# Slim base — the plugin is a thin Triton CLIENT (no in-process GPU inference),
# so it needs no CUDA libs. Inference runs on the shared Triton server.
# onnxruntime (CPU) stays only as a dev fallback when INFERENCE_BACKEND != triton.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ffmpeg/libgl for the legacy FramePuller + cv2; GStreamer runtime + GI typelibs for
# the async worker's production decoder. plugins-base/good cover rtspsrc + decodebin +
# videoconvert (software H.264/H.265); plugins-bad adds depayloaders; libav is the
# ffmpeg bridge. gir1.2-* provide the Gst/GstApp GObject-introspection typelibs.
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
# 1.74 (girepository-1.0). Build deps are purged afterwards to keep the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgirepository1.0-dev libcairo2-dev pkg-config gcc python3-dev \
    && pip install --no-cache-dir "PyGObject==3.50.0" \
    && apt-get purge -y libgirepository1.0-dev libcairo2-dev pkg-config gcc python3-dev \
    && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Shared Vizor Scenario SDK (own layer — caches well).
COPY _sdk /sdk
RUN pip install --no-cache-dir "/sdk[app,triton,vectors]"

COPY frs/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application — thin entrypoint + one package per concern.
COPY frs/scenario.json frs/app.py frs/alembic.ini ./
COPY frs/config ./config
COPY frs/db ./db
COPY frs/schemas ./schemas
COPY frs/qdrant ./qdrant
COPY frs/recognition ./recognition
COPY frs/registration ./registration
COPY frs/deps ./deps
COPY frs/live ./live
COPY frs/routers ./routers

EXPOSE 8093
CMD ["python", "app.py"]
