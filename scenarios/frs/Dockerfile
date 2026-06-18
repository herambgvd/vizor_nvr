# Slim base — the plugin is now a thin Triton CLIENT (no in-process GPU
# inference), so it needs no CUDA libs. Inference runs on the shared Triton
# server. onnxruntime (CPU) stays only as a dev fallback when INFERENCE_BACKEND
# is not 'triton'.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application — thin entrypoint + one package per concern.
COPY scenario.json app.py ./
COPY config ./config
COPY db ./db
COPY schemas ./schemas
COPY qdrant ./qdrant
COPY recognition ./recognition
COPY registration ./registration
COPY deps ./deps
COPY live ./live
COPY routers ./routers

EXPOSE 8093
CMD ["python", "app.py"]
