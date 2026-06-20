# Scenario plugin image. Build CONTEXT must be the scenarios/ directory so the
# shared SDK (../_sdk) is reachable:
#
#   docker build -f scenarios/<slug>/Dockerfile -t vizor/<slug> scenarios/
#
# (The compose service sets `context: ./scenarios` + `dockerfile: <slug>/Dockerfile`.)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 1) Install the shared SDK first (its own layer — changes rarely, caches well).
COPY _sdk /sdk
RUN pip install --no-cache-dir "/sdk[app,triton]"

# 2) Scenario deps.  (Real scenarios: replace _template with your <slug> dir.)
COPY _template/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 3) Scenario code.
COPY _template/ ./

EXPOSE 8099
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8099"]
