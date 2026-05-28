# Host Sizing Guide — GVD NVR

> Target configuration: 1080p main stream + 480p sub-stream per camera, H.264 (unless noted).  
> All storage figures assume 30-day retention unless stated otherwise.

---

## Minimum Host Requirements by Camera Count

| Tier | Cameras | RAM | vCPU | NIC (ingress) | Disk Write IOPS | H.264 30-day storage | H.265 30-day storage |
|---|---|---|---|---|---|---|---|
| **Starter** | 8 | 8 GB | 4 | 100 Mbps | 200 | ~5.0 TB | ~2.6 TB |
| **Small** | 16 | 16 GB | 8 | 200 Mbps | 400 | ~10.1 TB | ~5.2 TB |
| **Medium** | 32 | 32 GB | 16 | 400 Mbps | 800 | ~20.2 TB | ~10.4 TB |
| **Large** | 64 | 64 GB | 32 | 1 Gbps | 1,600 | ~40.3 TB | ~20.7 TB |

> **RAM note**: figures include OS overhead (~2 GB), Postgres (~1 GB), go2rtc (~256 MB), and ~256 MB per active RTSP session for transcoding buffers.  
> **IOPS note**: assumes sequential writes to spinning disk (HDD) or SSD. HDDs in a RAID array can comfortably handle 200–400 IOPS; SSDs handle 10,000+ IOPS.

---

## Storage Math

```
bytes/day  =  bitrate_Mbps × 86400 (s/day) ÷ 8 (bits→bytes) × cameras
```

Or in TB for N days:

```
TB  =  bitrate_Mbps × 86400 × cameras × days ÷ 8 ÷ 1e12 × 1.1 (10% overhead)
```

### Worked Examples

#### Example A — 4 Mbps × 14 cameras × 30 days (H.264)

```
bytes/day  = 4 × 86400 ÷ 8 × 14  = 6,048,000,000 bytes/day ≈ 5.6 GB/day
30-day     = 5.6 × 30             = 168 GB  (+ 10% overhead = ~185 GB)
```

#### Example B — 4 Mbps × 32 cameras × 30 days (H.264)

```
bytes/day  = 4 × 86400 ÷ 8 × 32  = 13,824,000,000 bytes/day ≈ 12.9 GB/day
30-day     = 12.9 × 30            = 387 GB  (+ 10% overhead = ~426 GB)
```

#### Example C — 8 Mbps × 16 cameras × 30 days (H.264) — high-resolution deployment

```
bytes/day  = 8 × 86400 ÷ 8 × 16  = 13,824,000,000 bytes/day ≈ 12.9 GB/day
30-day     = 12.9 × 30            = 387 GB  (+ 10% overhead = ~426 GB)
```

#### Example D — 4 Mbps × 14 cameras × 30 days (H.265, ~50% smaller)

```
bytes/day  = 2 × 86400 ÷ 8 × 14  = 3,024,000,000 bytes/day ≈ 2.8 GB/day
30-day     = 2.8 × 30             = 84 GB   (+ 10% overhead = ~92 GB)
```

#### Example E — Sub-stream only recording (480p @ 512 kbps × 32 cameras × 30 days)

```
bytes/day  = 0.512 × 86400 ÷ 8 × 32 = 1,769,472,000 bytes/day ≈ 1.6 GB/day
30-day     = 1.6 × 30               = 48 GB   (+ 10% overhead = ~53 GB)
```

> **Tip**: GVD NVR supports sub-stream recording (`recording_mode=schedule` + sub-stream flag). For storage-constrained deployments, record the sub-stream continuously and the main stream only on motion.

---

## Hardware Acceleration Impact (NVENC vs CPU Encode)

GVD NVR uses ffmpeg for transcoding (thumbnail generation, HLS adaptive streaming). Live RTSP pass-through via go2rtc requires no transcoding.

| Workload | CPU encode (no GPU) | NVENC (NVIDIA GPU) | Improvement |
|---|---|---|---|
| HLS transcode overhead per camera | ~0.5 vCPU | ~0.05 vCPU | 10× |
| Max cameras before CPU saturation (16-core host) | ~28 cameras | ~200+ cameras | 7× |
| Power draw (transcoding 32 streams) | ~200 W (CPU only) | ~80 W CPU + ~40 W GPU | ~35% lower |
| Latency (transcode pipeline) | 1.5–3 s | 0.3–0.8 s | 4× |

To enable NVENC:
1. Install NVIDIA Container Toolkit on the host.
2. Add `deploy.resources.reservations.devices` to the `backend` service in `docker-compose.yml`.
3. Set `FFMPEG_HWACCEL=nvenc` in `.env`.
4. Verify: `GET /api/system/hwaccel` → `nvenc: true`.

**Additional cameras with NVENC**: On a 32-core / RTX 3060 host, you can support approximately 64+ cameras at 1080p vs ~30 without GPU.

---

## Network Sizing

### Ingress (Cameras → NVR)

Each 1080p main stream at 4 Mbps + 480p sub at 512 kbps ≈ 4.5 Mbps per camera.

| Cameras | Ingress bandwidth |
|---|---|
| 8 | ~36 Mbps |
| 16 | ~72 Mbps |
| 32 | ~144 Mbps |
| 64 | ~288 Mbps |

Use a dedicated NIC or VLAN for camera traffic. A gigabit NIC handles up to ~64 cameras at these bitrates.

### Live-View Egress (NVR → Browsers)

go2rtc streams via WebRTC to each viewer. A 1080p stream forwarded as-is ≈ 4 Mbps per viewer per camera.

| Concurrent viewers × cameras watched | Egress bandwidth |
|---|---|
| 4 viewers × 4 cameras | ~64 Mbps |
| 8 viewers × 8 cameras | ~256 Mbps |
| 16 viewers × 16 cameras | ~1,024 Mbps (~1 Gbps) |

> For large deployments with many concurrent viewers, consider HLS adaptive streaming (lower bitrate) or a CDN proxy for the RTSP streams.

### Recording Write Throughput

Recording pipeline writes to disk sequentially. At 4 Mbps average per camera:

| Cameras | Write throughput |
|---|---|
| 8 | ~4.5 MB/s |
| 16 | ~9 MB/s |
| 32 | ~18 MB/s |
| 64 | ~36 MB/s |

A single 7200 RPM HDD sustains ~100–150 MB/s sequential writes, easily supporting 32 cameras. For 64+ cameras, use RAID-5/6 or SSDs.

---

## Disk Selection Guide

| Use case | Recommended disk type | Min capacity (64 cams, 30 days, H.264) |
|---|---|---|
| Development / test | Any SSD or HDD | 500 GB |
| Production ≤ 32 cams | NAS/surveillance HDD (WD Purple, Seagate SkyHawk) | 10 TB |
| Production 32–64 cams | NAS HDD RAID-5 array or enterprise SSD | 20–40 TB |
| High availability | RAID-6 or ZFS RAIDZ2 | 40+ TB raw |

> **Surveillance HDDs** (WD Purple, Seagate SkyHawk) are optimized for continuous write workloads and have higher MTBF than desktop HDDs. Use them for production NVR deployments.
