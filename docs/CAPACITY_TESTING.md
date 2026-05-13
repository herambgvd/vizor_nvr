# Capacity Testing Guide

This document explains how to run capacity tests against the GVD NVR using the framework in `backend/scripts/capacity-testing/`.

---

## Prerequisites

### Hardware / Software

- A running GVD NVR stack (backend + go2rtc + PostgreSQL).
- **FFmpeg** installed on the machine that will run the simulated camera load.
- **Python 3.10+** with dependencies from `backend/requirements.txt` installed:
  ```bash
  cd backend
  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```
- The test scripts use `psutil`, `httpx`, and optionally `psycopg2-binary` (all listed in `requirements.txt`).

### Network Access

- The test runner must reach:
  - NVR API (default `http://localhost:8000`)
  - go2rtc RTSP server (default `rtsp://localhost:8554`)
  - PostgreSQL (optional, for direct DB metrics)

Inside Docker you may need to use `host.docker.internal` or service names instead of `localhost`.

---

## Quick Start (Local Dev)

### 1. Start the simulated camera streams

```bash
cd backend/scripts/capacity-testing
python simulate_camera_load.py --count 16
```

This launches 16 FFmpeg processes that push test-pattern video to `rtsp://localhost:8554/cap_test_cam_0000` … `cap_test_cam_0015`.

> **Tip:** Start this in a separate terminal — it runs until you press `Ctrl+C`.

### 2. Run the capacity test

In another terminal:

```bash
cd backend/scripts/capacity-testing
python capacity_test.py \
  --username admin \
  --password your_admin_password \
  --cameras 16 \
  --duration 600
```

The script will:
1. Log in to the NVR API.
2. Create 16 fake cameras pointing at the simulated streams.
3. Start recording on all of them simultaneously.
4. Collect metrics every **5 seconds** for **10 minutes**.
5. Stop recordings, delete the fake cameras, and print a summary.

Results are written to `./capacity-test-results/`:
- `metrics_YYYYMMDD_HHMMSS.jsonl` — raw time-series data
- `report_YYYYMMDD_HHMMSS.json` — aggregated summary

---

## Command-Line Reference

### `simulate_camera_load.py`

| Flag | Default | Description |
|------|---------|-------------|
| `--count` | `16` | Number of simulated RTSP streams |
| `--resolution` | `1920x1080` | Video resolution |
| `--fps` | `25` | Frame rate |
| `--bitrate` | `4M` | Video bitrate (e.g. `4M`, `8M`) |
| `--codec` | `h264` | Video codec (`h264` or `hevc`) |
| `--duration` | `0` | Stream duration in seconds (`0` = infinite) |
| `--rtsp-url` | `rtsp://localhost:8554` | Base RTSP URL to push to |
| `--prefix` | `cap_test_cam_` | Stream name prefix |
| `--hwaccel` | `none` | Hardware encoder (`nvenc`, `vaapi`, `videotoolbox`) |

#### Examples

```bash
# 32 cameras, 1080p25, 4 Mbps, infinite
python simulate_camera_load.py --count 32

# 8 cameras, 4K15, 8 Mbps, HEVC, for 20 minutes
python simulate_camera_load.py --count 8 --resolution 3840x2160 --fps 15 --bitrate 8M --codec hevc --duration 1200

# Push to remote go2rtc
python simulate_camera_load.py --count 16 --rtsp-url rtsp://192.168.1.50:8554

# Use NVIDIA NVENC to reduce CPU load on the load-generator machine
python simulate_camera_load.py --count 64 --hwaccel nvenc
```

### `capacity_test.py`

| Flag | Default | Description |
|------|---------|-------------|
| `--api-url` | `http://localhost:8000` | NVR API base URL |
| `-u`, `--username` | *(required)* | Admin username |
| `-p`, `--password` | *(required)* | Admin password |
| `--cameras` | `16` | Number of fake cameras to create |
| `--duration` | `600` | Test duration in seconds |
| `--rtsp-base` | `rtsp://localhost:8554` | Base RTSP URL the cameras will consume |
| `--db-url` | `DATABASE_URL` env var | PostgreSQL URL for direct DB metrics |
| `--output-dir` | `./capacity-test-results` | Where JSONL + report are saved |
| `--no-cleanup` | `False` | Keep fake cameras after the test |
| `--camera-prefix` | `cap_test_cam_` | Prefix for camera/stream names |

#### Examples

```bash
# Basic 16-camera / 10-minute test
python capacity_test.py -u admin -p secret --cameras 16

# 64 cameras, 30 minutes, keep cameras for manual inspection
python capacity_test.py -u admin -p secret --cameras 64 --duration 1800 --no-cleanup

# Inside Docker (backend container)
python capacity_test.py -u admin -p secret \
  --api-url http://localhost:8000 \
  --rtsp-base rtsp://host.docker.internal:8554 \
  --db-url postgresql+asyncpg://nvr:pass@db:5432/gvd_nvr \
  --cameras 32 --duration 600
```

---

## Understanding the Output

### JSONL Metrics (`metrics_*.jsonl`)

Each line is a JSON object captured every 5 seconds:

```json
{
  "timestamp": "2024-01-15T09:23:05+00:00",
  "system": {
    "cpu_percent": 45.2,
    "memory_percent": 38.1,
    "memory_used_mb": 3124.5,
    "memory_total_mb": 8192.0,
    "disk_percent": 22.0,
    "disk_used_gb": 220.5,
    "disk_total_gb": 1000.0
  },
  "ffmpeg": {
    "process_count": 16,
    "total_cpu_percent": 18.5,
    "total_rss_mb": 512.0,
    "processes": [
      {"pid": 12345, "cpu_percent": 1.2, "rss_mb": 32.0, "camera_id": "cap_test_cam_0000"}
    ]
  },
  "database": {
    "available": true,
    "connections": 8,
    "active_queries": 2,
    "xact_commit": 15420,
    "blks_hit": 98231
  },
  "api": {
    "available": true,
    "active_recordings": 16,
    "go2rtc_status": "connected",
    "cameras": {"total": 16, "online": 16, "offline": 0, "recording": 16}
  },
  "network": {
    "recv_mbps": 12.5,
    "sent_mbps": 0.8
  },
  "disk_io": {
    "read_mbps": 2.1,
    "write_mbps": 8.4
  }
}
```

You can stream-process this with `jq` or import into Grafana / pandas:

```bash
# Average CPU over the run
jq -s 'map(.system.cpu_percent) | add / length' metrics_*.jsonl

# Peak memory usage
jq -s 'map(.system.memory_percent) | max' metrics_*.jsonl
```

### Summary Report (`report_*.json`)

```json
{
  "test_config": { "camera_count_requested": 32, "duration_seconds": 600, ... },
  "summary": {
    "max_cameras_sustained": 32,
    "dropped_frames_estimate_percent": 2.1,
    "bottlenecks": ["CPU saturated (>90%)"]
  },
  "resource_peaks": {
    "cpu_percent": 94.5,
    "memory_percent": 71.2,
    "ffmpeg_process_count": 32,
    "ffmpeg_cpu_percent": 45.0,
    "disk_write_mbps": 42.3
  },
  "resource_averages": { ... }
}
```

**Key fields:**
- `max_cameras_sustained` — highest number of concurrent active recordings observed.
- `dropped_frames_estimate_percent` — rough estimate based on expected vs actual network throughput. A value >5% warrants investigation.
- `bottlenecks` — human-readable list of resource saturation points detected during the test.

---

## Running Inside Docker

### Option A: Run from the host

If the NVR stack is running via `docker compose`, the API and go2rtc are published on host ports:

```bash
# Host machine
python capacity_test.py --api-url http://localhost:8000 --rtsp-base rtsp://localhost:8554 ...
```

### Option B: Run inside the backend container

```bash
# Copy scripts into the container
docker cp backend/scripts/capacity-testing gvd_backend:/app/scripts/

# Exec into the container
docker exec -it gvd_backend bash

# Install deps (if not already present)
pip install psutil httpx psycopg2-binary

# Run the test
python /app/scripts/capacity-testing/capacity_test.py \
  -u admin -p secret \
  --api-url http://localhost:8000 \
  --rtsp-base rtsp://host.docker.internal:8554 \
  --db-url "$DATABASE_URL" \
  --cameras 32 --duration 600
```

> **Note:** `host.docker.internal` works on Docker Desktop and recent Docker Engine on Linux. On older Linux setups you may need `--add-host=host.docker.internal:host-gateway` or use the host IP directly.

---

## Interpreting Bottlenecks

| Bottleneck | Likely Cause | Mitigation |
|------------|--------------|------------|
| CPU saturated | Too many streams, privacy masks forcing re-encode, or motion detection on all cameras | Add CPU cores; enable hardware transcoding (`nvenc`, `vaapi`); reduce motion-detection resolution |
| RAM saturated | FFmpeg buffers, large connection pool, or many concurrent exports | Add RAM; reduce `pool_size` in `app/database.py`; limit export concurrency |
| Disk write throughput | Storage cannot keep up with segment writes | Upgrade to NVMe SSD; use RAID 10; spread cameras across storage pools |
| FFmpeg process count low | Processes crashing or failing to start | Check FFmpeg logs; verify RTSP streams are healthy; inspect `go2rtc` connectivity |
| Network recv low | Simulated streams not reaching go2rtc, or go2rtc not restreaming | Verify `go2rtc` health; check firewall / port 8554 |

---

## Hardware Recommendations

See [`backend/scripts/capacity-testing/hardware_specs.md`](../backend/scripts/capacity-testing/hardware_specs.md) for per-tier CPU, RAM, network, storage, and Docker resource limits.

---

## Troubleshooting

### "No streams started — check go2rtc is running"
- Verify go2rtc container is healthy: `docker compose ps go2rtc`
- Check go2rtc API: `curl http://localhost:1984/api/streams`
- Ensure port `8554` is not blocked by a firewall.

### "Failed to start recording for …"
- The camera's RTSP source may not be ready in go2rtc. Increase the `--duration` on `simulate_camera_load.py` so streams are already publishing before the capacity test starts.
- Check backend logs: `docker logs -f gvd_backend`

### DB metrics show `"available": false`
- `psycopg2-binary` may not be installed: `pip install psycopg2-binary`
- The `DATABASE_URL` may use `+asyncpg` — the script strips this automatically, but verify the credentials are correct.

### Test interrupts immediately
- Ensure the admin user has `manage_camera` and `control_recording` permissions.
- If the NVR has a license or camera-count cap, increase it in Settings or the license file before testing.

---

## Contributing

If you extend the framework (e.g., add Prometheus export, Grafana dashboard import, or ONVIF simulation), please update this document and keep the scripts compatible with both local virtual-env and Docker execution.
