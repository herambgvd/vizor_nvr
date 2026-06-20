# Build CONTEXT is scenarios/ (so the shared SDK at ../_sdk is reachable):
#   docker build -f ppe/Dockerfile scenarios/
# Compose sets context: ./scenarios + dockerfile: ppe/Dockerfile.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Shared Vizor Scenario SDK (own layer — caches well).
COPY _sdk /sdk
RUN pip install --no-cache-dir "/sdk[app]"

COPY ppe/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY ppe/app.py ppe/scenario.json ./

EXPOSE 8092
CMD ["python", "app.py"]
