# =============================================================================
# DeepStream People Counting pipeline
# =============================================================================
# Per-camera GPU-decoded H.264 → YOLOv12m person detection on Triton →
# NvDCF tracker → custom line-crossing + crowd polygon probe → Redis
# Stream "ai:events".
#
# Bootstraps camera list + zones from backend on startup.
# Listens on Redis pub/sub "ai:control:reload" for hot config reload.
# =============================================================================
FROM nvcr.io/nvidia/deepstream:7.1-gc-triton-devel

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Python bindings for DeepStream
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip python3-gi python3-gi-cairo python3-gst-1.0 \
    libcairo2-dev libgirepository1.0-dev pkg-config \
 && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    redis>=5.0 \
    httpx>=0.27 \
    pyyaml>=6.0 \
    shapely>=2.0

WORKDIR /app
COPY . /app

ENTRYPOINT ["python3", "/app/pipeline.py"]
