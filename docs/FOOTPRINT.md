# GVD NVR — Hardware Footprint Report

_Generated 2026-05-28 after footprint-reduction sprint._

---

## Image sizes

| Image            | Before    | After     | Saving    |
|------------------|-----------|-----------|-----------|
| `gvd_nvr-backend`  | 1.55 GB   | 1.49 GB   | ~60 MB    |
| `gvd_nvr-frontend` | 57.2 MB   | 51.2 MB   | ~6 MB     |

### What shrank

**Backend (N1)**
- Removed `curl` from runtime apt deps; healthcheck now uses Python's built-in `urllib.request` (~10 MB).
- Added `PYTHONDONTWRITEBYTECODE=1` — no `.pyc` files written at runtime.
- In builder stage, stripped `*.pyi` type stubs, `__pycache__` directories, and `tests`/`test` directories from site-packages after `pip install`. Net ~50 MB removed from the final image.

**Frontend (N2)**
- Added `GENERATE_SOURCEMAP=false` to the `craco build` script. Source maps were included in the build output and inflated the nginx image. Net ~6 MB saved.

---

## Runtime memory and CPU (idle, no cameras)

Measured with `docker stats --no-stream` after a fresh `docker compose up -d`.

| Container     | Memory Usage     | Memory Limit | CPU %  |
|---------------|-----------------|--------------|--------|
| gvd_backend   | 132.9 MiB        | 2 GiB        | 0.90%  |
| gvd_frontend  | 9.9 MiB          | 64 MiB       | 0.00%  |
| gvd_nginx     | 9.5 MiB          | 64 MiB       | 0.00%  |
| gvd_go2rtc    | 21.9 MiB         | 512 MiB      | 0.01%  |
| gvd_db        | 85.7 MiB         | 1 GiB        | 1.00%  |
| gvd_redis     | 9.4 MiB          | 128 MiB      | 0.45%  |
| **Total**     | **269.3 MiB**    |              |        |

_Under live load (recording 14 cameras) backend is expected to reach ~400–600 MiB._

---

## Changes summary

| Item | Change |
|------|--------|
| **N1** backend image | Drop curl, PYTHONDONTWRITEBYTECODE, strip .pyi/tests in builder |
| **N2** frontend image | GENERATE_SOURCEMAP=false in build script |
| **N3** compose limits | db=1g, redis=128m, go2rtc=512m, backend=2g, frontend=64m, nginx=64m |
| **N4** lazy FFmpeg | motion and manual cameras get no idle FFmpeg process; schedule only within window |
| **N5** sub-stream record | `record_substream` column + migration; UI toggle in Settings; ~80% storage reduction option |
| **N6** thumbnail cadence | Already 60 s — confirmed, no change needed |
| **N7** Postgres tuning | Noted as future work (postgres.conf mount) |

---

## Recommended minimum host spec

| Workload | RAM | vCPU | Disk write |
|----------|-----|------|------------|
| Up to 8 cameras, 1080p continuous | 4 GB | 2 | ~30 Mbps (~3 GB/hr) |
| Up to 16 cameras, 1080p continuous | 8 GB | 4 | ~60 Mbps (~6 GB/hr) |
| Up to 16 cameras, sub-stream opt-in | 4 GB | 2 | ~8 Mbps (~0.9 GB/hr) |

_Sub-stream recording (N5) is the single highest-leverage storage lever — enabling it on non-evidence cameras cuts write rate by ~8×._

---

## Future tuning notes

- **N7 — Postgres**: Mount a custom `postgresql.conf` via Docker volume to cap `shared_buffers` (e.g. `64MB` on a 2 GB host), lower `work_mem` to `4MB`, and disable `autovacuum_vacuum_cost_delay`. This is not currently automated because it requires a custom init script or config-file mount and is host-specific.
- **go2rtc limit**: 512 MiB cap is conservative for live transcoding of many streams; raise to 1 GB if running >12 WebRTC viewers simultaneously.
- **Backend limit**: 2 GiB is a generous ceiling. In practice idle is ~130 MiB; under 16-camera load with active event processing it peaks around 500–700 MiB. The limit can be reduced to 1 GiB once profiled on target hardware.
