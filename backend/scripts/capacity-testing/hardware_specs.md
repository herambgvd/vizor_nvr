# GVD NVR — Hardware Recommendations

> Derived from the capacity testing framework and real-world FFmpeg / go2rtc / PostgreSQL resource modelling.
> All figures assume **H.264** recording with `-c copy` (no re-encoding) unless privacy masks or codecs require otherwise.

---

## Assumptions

| Parameter | Value |
|-----------|-------|
| Segment duration | 15 min (900 s) |
| Bitrate — 1080p | ~4 Mbps |
| Bitrate — 4K | ~8–12 Mbps |
| Codec | H.264 (main profile) |
| Recording mode | Continuous |
| Audio | None (video-only) |
| Go2RTC overhead | ~5–10% CPU per active stream pair |
| FFmpeg overhead | ~1–3% CPU per stream (copy mode) |

---

## Tier 1 — 16 Cameras (1080p@25 fps, H.264 ~4 Mbps each)

**Total ingress:** 64 Mbps (~8 MB/s)  
**Daily storage:** ~675 GB  
**Ideal for:** Small office, retail store, home estate

| Component | Recommendation |
|-----------|----------------|
| **CPU** | 4 cores / 8 threads, ≥ 2.5 GHz (Intel i3 / AMD Ryzen 3 or better) |
| **RAM** | 8 GB DDR4 |
| **Network** | 1 Gbps NIC (onboard is fine); ~7% utilisation at peak |
| **Storage** | 1× 4 TB WD Purple / Seagate SkyHawk (surveillance HDD) or 1 TB SATA SSD for hot storage + NAS for archive |
| **RAID** | Not strictly required; enable daily backups to external NAS |
| **OS** | Ubuntu 22.04/24.04 LTS, Debian 12, or RHEL 9 |
| **Docker limits** | `memory: 1.5g`, `cpus: '3.0'` for backend + go2rtc combined |

**Docker Compose snippet:**
```yaml
backend:
  deploy:
    resources:
      limits:
        cpus: "3.0"
        memory: 1536M
go2rtc:
  deploy:
    resources:
      limits:
        cpus: "1.0"
        memory: 512M
```

---

## Tier 2 — 32 Cameras (1080p@25 fps, H.264 ~4 Mbps each)

**Total ingress:** 128 Mbps (~16 MB/s)  
**Daily storage:** ~1.35 TB  
**Ideal for:** Medium office, school, small warehouse

| Component | Recommendation |
|-----------|----------------|
| **CPU** | 6 cores / 12 threads, ≥ 3.0 GHz (Intel i5-12xxx / AMD Ryzen 5 5600X or better) |
| **RAM** | 16 GB DDR4-3200 |
| **Network** | 1 Gbps NIC dedicated to camera VLAN; ~15% utilisation |
| **Storage** | 2× 4 TB WD Purple in RAID 1 (mirror) for redundancy, or 1× 2 TB NVMe SSD for 7-day hot retention + spinning archive |
| **RAID** | RAID 1 (mirror) minimum; RAID 10 if budget allows |
| **OS** | Ubuntu 22.04/24.04 LTS (recommended), Debian 12, AlmaLinux 9 |
| **Docker limits** | `memory: 3g`, `cpus: '5.0'` for backend; `memory: 1g` for go2rtc |

**Docker Compose snippet:**
```yaml
backend:
  deploy:
    resources:
      limits:
        cpus: "5.0"
        memory: 3g
go2rtc:
  deploy:
    resources:
      limits:
        cpus: "1.5"
        memory: 1g
db:
  deploy:
    resources:
      limits:
        cpus: "1.0"
        memory: 1g
```

---

## Tier 3 — 64 Cameras (Mixed: 48× 1080p + 16× 4K)

**Total ingress:** ~320 Mbps (~40 MB/s)  
**Daily storage:** ~3.4 TB  
**Ideal for:** Large office, hotel, factory floor, parking complex

| Component | Recommendation |
|-----------|----------------|
| **CPU** | 8 cores / 16 threads, ≥ 3.2 GHz (Intel i7-12xxx / AMD Ryzen 7 5800X or Xeon E-2388G) |
| **RAM** | 32 GB DDR4-3200 ECC (recommended if Xeon) |
| **Network** | 1× 2.5 Gbps NIC or dual 1 Gbps NICs in LAG/bond for camera VLAN; 2.5 Gbps for upstream playback clients |
| **Storage** | 4× 4–6 TB surveillance HDDs in RAID 10 (8–12 TB usable, ~400 MB/s seq write) **or** 2× 2 TB NVMe SSD in RAID 1 for hot 14-day retention + 4× HDD RAID 10 cold archive |
| **RAID** | RAID 10 strongly recommended; RAID 6 acceptable if write penalty is acceptable |
| **OS** | Ubuntu 24.04 LTS (recommended), Rocky Linux 9 |
| **Docker limits** | `memory: 6g`, `cpus: '7.0'` for backend; `memory: 2g` for go2rtc |

**Notes:**
- At this scale go2RTC begins to consume noticeable CPU for WebRTC transcoding. If live viewing is required for >10 concurrent users, consider a dedicated go2RTC node or GPU (see below).
- PostgreSQL connection pool (default 20 + 30 overflow) is sufficient, but watch for long-running queries during large exports.

**Docker Compose snippet:**
```yaml
backend:
  deploy:
    resources:
      limits:
        cpus: "7.0"
        memory: 6g
go2rtc:
  deploy:
    resources:
      limits:
        cpus: "2.0"
        memory: 2g
db:
  deploy:
    resources:
      limits:
        cpus: "2.0"
        memory: 2g
```

---

## Tier 4 — 128 Cameras (Mostly 1080p, some 4K)

**Typical mix:** 96× 1080p @ 4 Mbps + 32× 4K @ 10 Mbps  
**Total ingress:** ~700 Mbps (~88 MB/s)  
**Daily storage:** ~7.6 TB  
**Ideal for:** Campus, stadium, airport perimeter, large logistics hub

| Component | Recommendation |
|-----------|----------------|
| **CPU** | 16+ cores / 32 threads, ≥ 3.0 GHz (AMD Ryzen 9 5950X / Intel i9-12900K / Xeon W-3375 or dual Xeon Silver) |
| **RAM** | 64 GB DDR4-3200 ECC (mandatory for dual-socket) |
| **Network** | 1× 10 Gbps SFP+ NIC for camera VLAN; separate 1 Gbps for management; consider VLAN segregation |
| **Storage** | **Hot tier:** 4× 4 TB enterprise NVMe SSD (Samsung PM893 / WD SN640) in RAID 10 for 7-day hot retention (~1.6 GB/s write). **Cold tier:** 8× 8 TB HDD RAID 60 or ZFS RAIDZ2 for long-term archive. |
| **RAID** | Hot tier = RAID 10; Cold tier = RAID 6 / RAID 60 / ZFS RAIDZ2 |
| **OS** | Ubuntu 24.04 LTS or Rocky Linux 9 (kernel 5.15+ for io_uring performance) |
| **Docker limits** | `memory: 12g`, `cpus: '14.0'` for backend; `memory: 4g`, `cpus: '4.0'` for go2rtc |

**Optional hardware accelerators:**
- **NVIDIA GPU** (Tesla T4 / A2 / RTX A2000): offload H.264/H.265 encoding when privacy masks force re-encode. One T4 can handle ~40–50 concurrent 1080p encode streams.
- **Intel Quick Sync** (UHD P630 / Arc A380): excellent H.264/H.265 encode, ~20–30 streams per chip.

**Docker Compose snippet:**
```yaml
backend:
  deploy:
    resources:
      limits:
        cpus: "14.0"
        memory: 12g
  # If using NVIDIA GPU for privacy-mask re-encode:
  runtime: nvidia
  environment:
    - NVIDIA_VISIBLE_DEVICES=all
    - HARDWARE_TRANSCODING=nvenc
go2rtc:
  deploy:
    resources:
      limits:
        cpus: "4.0"
        memory: 4g
db:
  deploy:
    resources:
      limits:
        cpus: "3.0"
        memory: 4g
  # Consider mounting fast SSD for PGDATA
  volumes:
    - pg_fast:/var/lib/postgresql/data
```

---

## General Recommendations

### Disk I/O Sustained Throughput Targets

| Cameras | Required Seq Write | Recommended Disk Config |
|---------|-------------------|------------------------|
| 16 | 8 MB/s | Single SATA SSD or surveillance HDD |
| 32 | 16 MB/s | 2× HDD RAID 1 or 1× NVMe SSD |
| 64 | 40 MB/s | 4× HDD RAID 10 or 1× NVMe SSD |
| 128 | 88 MB/s | 4× NVMe SSD RAID 10 or 8× HDD RAID 10 |

### PostgreSQL Tuning (high camera counts)

Add to `postgresql.conf` or via Docker `command`:
```ini
shared_buffers = 2GB          # 25% of RAM for DB container
effective_cache_size = 6GB
max_connections = 100
work_mem = 16MB
maintenance_work_mem = 512MB
wal_buffers = 64MB
random_page_cost = 1.1        # For SSD/NVMe; use 4.0 for HDD
```

### Network Architecture

- Place cameras on a dedicated **VLAN** / subnet.
- Use a **managed switch** with IGMP snooping if multicast RTSP is used.
- For >64 cameras, consider **two 1 Gbps NICs bonded** (LACP) or a single 2.5/10 Gbps NIC.
- Bandwidth headroom: keep camera ingress ≤ 60% of link capacity to allow for burst segments, export jobs, and live playback.

### OS Tuning

```bash
# Increase file descriptor limits
sysctl -w fs.file-max=2097152

# Increase network buffers
sysctl -w net.core.rmem_max=134217728
sysctl -w net.core.wmem_max=134217728
sysctl -w net.ipv4.tcp_rmem="4096 87380 134217728"
sysctl -w net.ipv4.tcp_wmem="4096 65536 134217728"

# Disable swap or set swappiness low
sysctl -w vm.swappiness=10
```

### Docker Host Sizing

When running all services on a single Docker host, sum the container limits and add 10–15% headroom for the kernel + container runtime:

| Tier | Containers CPU | Containers RAM | Host Minimum |
|------|---------------|----------------|--------------|
| 16 | 4.0 | 2.5 GB | 4 cores / 4 GB |
| 32 | 7.5 | 5.0 GB | 8 cores / 8 GB |
| 64 | 11.0 | 10.0 GB | 12 cores / 16 GB |
| 128 | 21.0 | 20.0 GB | 24 cores / 32 GB |
