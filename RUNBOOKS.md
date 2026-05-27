# GVD NVR — Operations Runbooks

Quick-reference incident response for the GVD NVR stack. Each section
starts with **Symptoms**, then **Diagnose**, then **Fix**, then
**Verify**. Optimized for on-call paging at 3 AM.

Service map:

| Service | Container | Critical? |
|---|---|---|
| Postgres + TimescaleDB | `gvd_db` | Yes — data plane |
| Backend (FastAPI) | `gvd_backend` | Yes — control plane |
| Frontend (nginx + React) | `gvd_frontend` | No — UI only |
| go2rtc (WebRTC live) | `gvd_go2rtc` | Yes — live view |
| Redis | `vizor-redis` (legacy net) | Yes — cache |
| RustFS (S3) | `vizor-rustfs` | Yes — recordings + photos |

---

## 1. Database down / unreachable

**Symptoms**
- Backend 5xx everywhere
- `/api/health` returns `{"status": "error", "db": "down"}`
- Logs: `sqlalchemy.exc.OperationalError: connection refused`

**Diagnose**
```bash
docker compose ps db
docker compose logs --tail=200 db
docker exec gvd_db pg_isready -U nvr -d gvd_nvr
df -h /var/lib/docker/volumes/vizor_nvr_db_data
```

**Fix**
- Stopped container → `docker compose up -d db`
- Out of disk → free space (`docker system prune`, rotate logs); volume runs on `/var/lib/docker`
- Corrupt WAL → restore from PITR backup (see §8)
- Connection pool exhausted on backend → restart backend, increase `DB_POOL_MAX` env

**Verify**
- `docker exec gvd_db psql -U nvr -d gvd_nvr -c "select 1"` returns row
- `/api/health` returns `db: ok`
- New writes succeed (create a test event via API)

---

## 2. Camera offline / no recording

**Symptoms**
- Camera health icon red in UI
- Recordings table empty for affected camera
- ffmpeg supervisor logs: repeated reconnect attempts

**Diagnose**
```bash
docker compose logs --tail=200 backend | grep <camera_id>
# Reach camera directly?
docker exec gvd_backend curl -m 5 -I rtsp://<cam-ip>:554/<path>
# go2rtc stream registered?
curl -s http://localhost:1984/api/streams | jq
```

**Fix**
- Wrong credentials → update via Camera detail page, ONVIF tab
- Camera reboot → wait 2 min, ffmpeg auto-reconnects (exp backoff to 30s)
- Wrong codec (camera sends H.265 we can't decode) → switch sub-stream to H.264
- Persistent → remove camera, re-add (drops state)

**Verify**
- `docker exec gvd_db psql -U nvr -d gvd_nvr -c "SELECT id, last_online_at FROM cameras WHERE id='<cam_id>'"`
  shows recent `last_online_at`
- Live preview loads in UI

---

## 3. go2rtc not serving WebRTC

**Symptoms**
- Live view stuck on "Connecting…"
- Browser console: `ICE connection failed`

**Diagnose**
```bash
docker compose logs --tail=200 go2rtc
curl -s http://localhost:1984/api/streams | jq 'keys'
# Verify NAT/STUN reachable
docker exec gvd_go2rtc curl -m 3 stun.l.google.com:19302
```

**Fix**
- Stream not registered → trigger `POST /api/cameras/{id}/sync-streams` (re-pushes camera to go2rtc)
- STUN unreachable → check `GO2RTC_CANDIDATES` env (must include public-reachable IP)
- Container crashed → `docker compose restart go2rtc`
- Sub-stream codec mismatch → check `go2rtc.yaml` config; remap source

**Verify**
- Live preview connects within 3s
- Browser shows `connected` ICE state in WebRTC inspector

---

## 4. Storage full

**Symptoms**
- Recordings stop, new files fail
- Alert: `vizor_storage_used_bytes > threshold`

**Diagnose**
```bash
df -h /data
docker exec gvd_backend du -sh /data/recordings/*
# Retention service running?
docker compose logs --tail=200 backend | grep retention_service
```

**Fix**
- Manual cleanup: `find /data/recordings -mtime +30 -delete` (cuts oldest 30 days)
- Retention service stuck → restart backend
- Move to bigger volume → `docker compose down; mv /data ...; docker compose up -d`
- TimescaleDB compression lagging → `docker exec gvd_db psql -U nvr -d gvd_nvr -c "SELECT add_compression_policy('events', INTERVAL '1 day')"` (tighter window)

**Verify**
- `df -h /data` shows free space
- New recordings appear
- Retention service logs `Pruned N segments`

---

## 5. Backend slow (high latency)

**Symptoms**
- p99 request latency > 2s in Grafana
- UI sluggish

**Diagnose**
```bash
# Check connection pool exhaustion
docker exec gvd_db psql -U nvr -d gvd_nvr -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state"
# Slow query log
docker exec gvd_db psql -U nvr -d gvd_nvr -c "SELECT query, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10"
# Prometheus
curl -s localhost:8000/metrics | grep http_request_duration
```

**Fix**
- Idle in transaction → kill (`SELECT pg_terminate_backend(pid)`), find leak
- Hot query missing index → add via ad-hoc migration
- ARQ queue stuck → restart backend
- Big query result (timeline?) → tighten time range, paginate

**Verify**
- p99 < 500ms
- No active queries > 30s in `pg_stat_activity`

---

## 6. API key compromised

**Symptoms**
- Suspicious `/api/events/ingest` from unexpected IP
- `api_keys.last_used_ip` shows odd source

**Fix**
```bash
# Revoke immediately
curl -X POST http://localhost:8000/api/admin/api-keys/<key_id>/revoke \
  -H "Authorization: Bearer <admin_jwt>"
# Issue replacement
curl -X POST http://localhost:8000/api/admin/api-keys \
  -H "Authorization: Bearer <admin_jwt>" \
  -d '{"name": "bridge-replacement", "scopes": ["events:ingest"]}'
# Update consumer, redeploy
```

**Verify**
- Old key rejects with 401
- New key flowing events
- Audit log entry for revocation

---

## 7. Secrets rotation

When rotating JWT_SECRET_KEY:
1. Generate new: `python -c "import secrets; print(secrets.token_hex(32))"`
2. Update encrypted env: `bash scripts/sops-bootstrap.sh edit backend/.sops.env`
3. Restart backend
4. All existing JWTs invalidate — operators must re-login

When rotating API keys: see §6.

When rotating DB password:
1. `docker exec gvd_db psql -U postgres -c "ALTER USER nvr PASSWORD 'new_pwd'"`
2. Update encrypted env + restart backend
3. Connection pool reconnects with new credentials

---

## 8. Disaster recovery — Postgres point-in-time restore

**Symptoms**
- Bad migration / accidental delete / hardware failure

**Prep (do BEFORE incident)**
- WAL archive enabled (TimescaleDB image has it via env)
- Off-host backup of `/var/lib/docker/volumes/vizor_nvr_db_data`

**Restore**
```bash
docker compose down db
# Mount fresh empty volume
docker volume rm vizor_nvr_db_data
docker volume create vizor_nvr_db_data
# Restore base + replay WAL up to target time
# (Use whatever backup tool you set up — pgBackRest, Barman, etc.)
docker compose up -d db
# Verify schema head matches
docker compose run --rm backend alembic current
```

**Verify**
- Sample rows from `events` exist
- Backend health green

---

## Common one-liners

```bash
# Tail every container's log at once
docker compose logs -f --tail=50

# Count events per source_service in last 24h
docker exec gvd_db psql -U nvr -d gvd_nvr -c \
  "SELECT source_service, count(*) FROM events WHERE triggered_at > NOW() - INTERVAL '24 hours' GROUP BY 1 ORDER BY 2 DESC"

# Check TimescaleDB chunk usage
docker exec gvd_db psql -U nvr -d gvd_nvr -c \
  "SELECT hypertable_name, num_chunks, compressed_total_size FROM timescaledb_information.hypertables_size"

# Manual ingest test (smoke /api/events/ingest)
curl -X POST http://localhost:8000/api/events/ingest \
  -H "X-Vizor-API-Key: vzn_..." \
  -H "Content-Type: application/json" \
  -d '{"events":[{"dedup_key":"smoke-1","event_type":"smoke","title":"smoke test","source_service":"manual"}]}'
```

---

## Escalation

- L1: on-call engineer (10 min response)
- L2: backend lead (30 min)
- L3: SRE lead (1 hr)
- L4: founder / CTO

Hardware loss (host) → page L3 immediately.
Data loss (DB corruption, RustFS) → page L4 immediately, freeze writes.
