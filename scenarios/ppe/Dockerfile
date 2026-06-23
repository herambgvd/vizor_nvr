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

WORKDIR /app
# ffmpeg/libgl for the legacy FramePuller + cv2; GStreamer + PyGObject for the async
# worker's production decoder (gstreamer_frame_source). plugins-base/good cover
# rtspsrc + decodebin + videoconvert (software H.264/H.265); plugins-bad adds extra
# depayloaders. For NVDEC, base this image on an NVIDIA L4T/CUDA image with the
# nvcodec plugin and set GST_DECODER_BIN=nvh264dec — software decode works without it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg libgl1 libglib2.0-0 \
        python3-gi gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
        gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
        gstreamer1.0-libav \
    && rm -rf /var/lib/apt/lists/*

# Shared Vizor Scenario SDK (own layer — caches well). [app] = fastapi/pydantic,
# [triton] = tritonclient[http]. NO ultralytics/torch — inference is on Triton.
# PyGObject into THIS interpreter (the apt python3-gi targets the system python,
# which the slim image's pip python may not share). Needs the gobject-introspection
# + cairo dev headers at build time; runtime libs came from the apt block above.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgirepository1.0-dev libcairo2-dev pkg-config gcc \
    && pip install --no-cache-dir PyGObject \
    && apt-get purge -y libgirepository1.0-dev libcairo2-dev pkg-config gcc \
    && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

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
