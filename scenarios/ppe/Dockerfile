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
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

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
