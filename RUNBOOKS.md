# Vizor AI NVR — Operations Runbooks

Quick-reference incident response for the Vizor stack. Each section
starts with **Symptoms**, then **Diagnose**, then **Fix**, then
**Verify**. Optimized for on-call paging at 3 AM.

Service map:

| Service | Container | Critical? |
|---|---|---|
| Postgres + TimescaleDB | `gvd_db` | Yes — data plane |
| Backend (FastAPI) | `gvd_backend` | Yes — control plane |
| Frontend (nginx + React) | `gvd_frontend` | No — UI only |
| go2rtc (WebRTC live) | `gvd_go2rtc` | Yes — live view |
| Redis | `vizor-redis` (legacy net) | Yes — bridge + cache |
| RustFS (S3) | `vizor-rustfs` | Yes — recordings + photos |
| Qdrant | `vizor-qdrant` | Yes — FRS embeddings |
| Triton | `vizor-triton` | Yes for AI inference |
| (Future) VST | `gvd_vst` | Yes when shipped |
| (Future) Perception Microservice | `gvd_perception` | Yes when shipped |

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
- Corrupt WAL → restore from PITR backup (see §10)
- Connection pool exhausted on backend → restart backend, increase `DB_POOL_MAX` env

**Verify**
- `docker exec gvd_db psql -U nvr -d gvd_nvr -c "select 1"` returns row
- `/api/health` returns `db: ok`
- New writes succeed (create a test event via API)

---

## 2. Metropolis bridge stuck / DLQ growing

**Symptoms**
- `/metrics` shows `vizor_events_ingested_total` flat
- DLQ length climbing (Grafana: `redis_stream_length{stream="metropolis:events:dlq"}`)
- Backend logs: `Failed to ingest event with dedup_key=…`

**Diagnose**
```bash
# Bridge status
docker compose logs --tail=200 backend | grep -i metropolis
# DLQ size + sample
docker exec gvd_backend python scripts/dlq_replay.py list --limit 10
# Specific entry
docker exec gvd_backend python scripts/dlq_replay.py inspect <entry_id>
```

**Common reasons**
| Reason | Cause | Fix |
|---|---|---|
| `decode_error` | Upstream payload schema drift | Update `metropolis_to_ingest_event` translator |
| `ingest_failed` | Backend 5xx | Fix backend, then `dlq_replay.py replay --reason ingest_failed` |
| `ingest_failed` w/ 401 | API key revoked or expired | Issue new key, redeploy bridge env |

**Replay**
```bash
# Replay one
docker exec gvd_backend python scripts/dlq_replay.py replay <entry_id>
# Replay all of one kind
docker exec gvd_backend python scripts/dlq_replay.py replay --reason ingest_failed
# Clear (only after manual diagnosis)
docker exec gvd_backend python scripts/dlq_replay.py clear --yes
```

**Verify**
- DLQ length drops to 0 over next 30s
- `vizor_events_ingested_total` resumes climbing
- New events from cameras appear in NVR Events page

---

## 3. Camera offline / no recording

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

## 4. go2rtc not serving WebRTC

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

## 5. Storage full

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

## 6. GPU OOM / Triton OOM

**Symptoms**
- Inference workers crash on model load
- `nvidia-smi` shows 100% memory
- Logs: `CUDA out of memory`

**Diagnose**
```bash
nvidia-smi
docker exec vizor-triton tritonserver --model-status
```

**Fix**
- Restart Triton: `docker compose restart triton`
- Reduce batch size in model config files (`config.pbtxt`)
- Offload one model: `curl -X POST localhost:8000/v2/repository/models/<name>/unload`
- Acquire bigger GPU (L4 / T4) — RTX 4050 6GB caps at ~4-8 cameras for FRS

**Verify**
- `nvidia-smi` shows usage <90%
- Inference latency p99 back under SLA

---

## 7. Backend slow (high latency)

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

## 8. Person enrolled but never matched

**Symptoms**
- FRS person exists in `frs_persons`
- No `FaceMatch` events ever fire for them

**Diagnose**
```sql
SELECT id, name, last_seen_at FROM frs_persons WHERE name = '...';
SELECT * FROM frs_photos WHERE person_id = '...';
```
- Photos present?
- Qdrant point IDs valid? (`curl http://vizor-qdrant:6333/collections/frs_faces/points/<qdrant_point_id>`)

**Fix**
- No photos → re-enroll w/ photo upload
- Photo present but Qdrant 404 → embedding job failed; re-trigger
- Photo+Qdrant present but no match → tune `match_threshold` lower on the camera's FRS scenario config

**Verify**
- Test face appears in camera, event fires within 2s
- `person_id` field populated on event

---

## 9. API key compromised

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
# Update consumer (Metropolis bridge env), redeploy
```

**Verify**
- Old key rejects with 401
- New key flowing events
- Audit log entry for revocation

---

## 10. Disaster recovery — Postgres point-in-time restore

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

## 11. Secrets rotation

When rotating JWT_SECRET_KEY:
1. Generate new: `python -c "import secrets; print(secrets.token_hex(32))"`
2. Update encrypted env: `bash scripts/sops-bootstrap.sh edit backend/.sops.env`
3. Restart backend
4. All existing JWTs invalidate — operators must re-login

When rotating API keys: see §9.

When rotating DB password:
1. `docker exec gvd_db psql -U postgres -c "ALTER USER nvr PASSWORD 'new_pwd'"`
2. Update encrypted env + restart backend
3. Connection pool reconnects with new credentials

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

# Re-seed AI scenarios (e.g. after editing seed.py)
docker compose run --rm backend python -c \
  "import asyncio; from app.database import async_session_maker; from app.ai.seed import seed_ai_scenarios
asyncio.run((async def x():
    async with async_session_maker() as db:
        await seed_ai_scenarios(db))())"

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

Hardware loss (GPU/host) → page L3 immediately.
Data loss (DB corruption, RustFS) → page L4 immediately, freeze writes.
