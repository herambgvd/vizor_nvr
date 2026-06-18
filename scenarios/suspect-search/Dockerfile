# Slim base — inference runs on the shared Triton server, so no CUDA libs in the
# plugin. onnxruntime (CPU) is only a dev fallback.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application — one package per concern.
COPY app.py scenario.json ./
COPY config ./config
COPY db ./db
COPY deps ./deps
COPY inference ./inference
COPY qdrant ./qdrant
COPY routers ./routers
COPY services ./services

EXPOSE 8091
CMD ["python", "app.py"]
