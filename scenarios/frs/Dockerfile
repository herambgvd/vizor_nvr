# CUDA 12 + cuDNN 9 runtime base — required by onnxruntime-gpu 1.20's
# CUDAExecutionProvider. python:slim lacks these libs (libcublasLt / cuDNN) so
# ORT would silently fall back to CPU. Pin to a cudnn9 runtime tag.
FROM nvidia/cuda:12.6.2-cudnn-runtime-ubuntu22.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv ffmpeg libgl1 libglib2.0-0 \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip3 install --no-cache-dir --upgrade pip \
    && pip3 install --no-cache-dir -r requirements.txt

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
