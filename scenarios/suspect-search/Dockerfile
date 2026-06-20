# Build CONTEXT is scenarios/ (so the shared SDK at ../_sdk is reachable):
#   docker build -f suspect-search/Dockerfile scenarios/
# Compose sets context: ./scenarios + dockerfile: suspect-search/Dockerfile.
#
# Slim base — inference runs on the shared Triton server, so no CUDA libs in the
# plugin. onnxruntime (CPU) is only a dev fallback.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Shared Vizor Scenario SDK (own layer — caches well). Installed into site-packages
# so it survives the dev source bind-mount that overlays /app.
COPY _sdk /sdk
RUN pip install --no-cache-dir "/sdk[app,triton,vectors]"

COPY suspect-search/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application — one package per concern.
COPY suspect-search/app.py suspect-search/scenario.json ./
COPY suspect-search/config ./config
COPY suspect-search/db ./db
COPY suspect-search/deps ./deps
COPY suspect-search/inference ./inference
COPY suspect-search/qdrant ./qdrant
COPY suspect-search/routers ./routers
COPY suspect-search/services ./services

EXPOSE 8091
CMD ["python", "app.py"]
