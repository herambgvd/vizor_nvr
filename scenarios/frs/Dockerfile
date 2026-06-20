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

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Shared Vizor Scenario SDK (own layer — caches well).
COPY _sdk /sdk
RUN pip install --no-cache-dir "/sdk[app,triton,vectors]"

COPY frs/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application — thin entrypoint + one package per concern.
COPY frs/scenario.json frs/app.py ./
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
