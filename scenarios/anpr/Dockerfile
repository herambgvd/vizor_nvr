# Build CONTEXT is scenarios/ (so the shared SDK at ../_sdk is reachable):
#   docker build -f anpr/Dockerfile scenarios/
# Compose sets context: ./scenarios + dockerfile: anpr/Dockerfile.
#
# Slim base — the plugin is a thin Triton CLIENT (no in-process GPU inference),
# so it needs no CUDA libs. Inference (anpr_plate / ppocr_v6 / yolo26) runs on the
# shared Triton server. ffmpeg + libgl/libglib are for go2rtc frame decode + opencv.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Shared Vizor Scenario SDK (own layer — caches well). [app] = fastapi/pydantic,
# [triton] = tritonclient[http]. NO torch/openvino/onnxruntime — inference is on
# Triton; the client-side CTC decode is pure numpy.
COPY _sdk /sdk
RUN pip install --no-cache-dir "/sdk[app,triton]"

COPY anpr/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application — thin entrypoint + one package per concern. models/ ships the
# dict_v6.txt charset for the client-side PP-OCRv6 CTC decode.
COPY anpr/scenario.json anpr/app.py anpr/alembic.ini ./
COPY anpr/config ./config
COPY anpr/db ./db
COPY anpr/schemas ./schemas
COPY anpr/inference ./inference
COPY anpr/pipeline ./pipeline
COPY anpr/registration ./registration
COPY anpr/deps ./deps
COPY anpr/live ./live
COPY anpr/routers ./routers
COPY anpr/models ./models

EXPOSE 8094
CMD ["python", "app.py"]
