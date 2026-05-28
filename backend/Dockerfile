# =============================================================================
# GVD NVR — Backend Dockerfile
# =============================================================================
# Multi-stage build: smaller final image without build tools

FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Strip stubs, caches, and test directories from site-packages (saves 30–80 MB)
RUN find /install/lib/python3.12/site-packages -name '*.pyi' -delete \
 && find /install/lib/python3.12/site-packages -depth -type d -name '__pycache__' -exec rm -rf {} + \
 && find /install/lib/python3.12/site-packages -depth -type d -name 'tests' -exec rm -rf {} + \
 && find /install/lib/python3.12/site-packages -depth -type d -name 'test' -exec rm -rf {} +


# =============================================================================
# Final image
# =============================================================================
FROM python:3.12-slim

# Do not write .pyc files or __pycache__ at runtime
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Runtime system dependencies — curl dropped; healthcheck uses python urllib
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

# Create data directories
RUN mkdir -p data/recordings data/thumbnails data/exports data/hls

# Create a non-root user (entrypoint fixes /data perms before dropping
# privileges, so we stay root for ENTRYPOINT but uvicorn runs as nvr).
RUN useradd --uid 1001 --create-home nvr && chown -R nvr:nvr /app

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health').read()" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --loop asyncio"]
