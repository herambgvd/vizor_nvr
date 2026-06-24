# Build CONTEXT is scenarios/ (so the shared SDK at ../_sdk is reachable):
#   docker build -f ppe/Dockerfile scenarios/
# Compose sets context: ./scenarios + dockerfile: ppe/Dockerfile.
#
# CUDA runtime base (parity with FRS + vizor-gpu) so the GStreamer live decoder can
# use NVDEC (nvh264dec) on the GPU instead of a CPU core per camera. Inference still
# runs on the shared Triton server; the CUDA runtime here is only for GPU video decode.
FROM nvidia/cuda:12.5.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Python 3.11 + ffmpeg/libgl (cv2) + the full GStreamer stack. plugins-bad ships the
# nvcodec elements (nvh264dec) which light up because the CUDA runtime is present and
# the GPU is passed through at run time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates gnupg wget curl \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-dev python3.11-distutils \
        ffmpeg libgl1 libglib2.0-0 libsm6 libxext6 \
        libgirepository-1.0-1 libcairo2 \
        gstreamer1.0-tools \
        gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly \
        gstreamer1.0-libav gstreamer1.0-nice \
        libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 \
        gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
    && rm -rf /var/lib/apt/lists/* \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && curl -fsSL https://bootstrap.pypa.io/get-pip.py | python3.11 -

# PyGObject into 3.11. Pin 3.50.0 — newer needs girepository-2.0; ubuntu 22.04 ships
# girepository-1.0. Build deps purged after.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgirepository1.0-dev libcairo2-dev pkg-config gcc \
    && pip install --no-cache-dir "PyGObject==3.50.0" \
    && apt-get purge -y libgirepository1.0-dev libcairo2-dev pkg-config gcc \
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
