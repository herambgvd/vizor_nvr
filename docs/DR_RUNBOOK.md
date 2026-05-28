# Disaster Recovery Runbook — GVD NVR

> **Audience**: On-call operators and system administrators.  
> **Last updated**: 2026-05-28

---

## 1. Backup

### What the backup service produces

`backup_service` (run manually or via cron) creates a portable `.tar.gz` archive containing:

| File in archive | Description |
|---|---|
| `db_dump.sql` | Full `pg_dump` of the `nvr` database (plain-SQL format) |
| `settings.json` | Exported application settings rows (from `settings` table) |
| `.env` | Environment file (contains secrets — protect accordingly) |
| `certs/` | TLS certificate and key files from the `certs` Docker volume |
| `go2rtc.yaml` | go2rtc restreamer configuration |
| `recordings_index.csv` | Metadata CSV of all recording rows (NOT raw video files) |
| `manifest.json` | Timestamp, NVR version, alembic head, camera count |

**Raw video files are NOT included** — back those up separately via storage volume snapshots or an external NAS/S3 sync job.

### Running the backup

```bash
# From the repo directory on the NVR host:
docker compose exec backend python -m app.services.backup_service

# Output archive lands at:
ls -lh /var/lib/gvd-nvr/data/backups/gvd-nvr-backup-YYYYMMDD-HHMMSS.tar.gz
```

Or, if you prefer a one-liner that also copies the archive off-host:

```bash
docker compose exec backend python -m app.services.backup_service \
  && scp /var/lib/gvd-nvr/data/backups/$(ls -t /var/lib/gvd-nvr/data/backups | head -1) \
         backup-server:/nvr-backups/
```

### Automating backups (cron)

```cron
# Daily at 02:00, keep last 14 archives
0 2 * * * cd /opt/gvd-nvr && docker compose exec -T backend python -m app.services.backup_service && find /var/lib/gvd-nvr/data/backups -name "*.tar.gz" -mtime +14 -delete
```

---

## 2. Verify a Backup (Test-Restore on Scratch Host)

> **Rule**: never test-restore on production. Use a separate VM or container.

```bash
# On scratch host — clone repo, copy backup archive, then:
ARCHIVE=gvd-nvr-backup-20260528-020000.tar.gz

# 1. Extract archive
mkdir /tmp/nvr-restore && tar xzf $ARCHIVE -C /tmp/nvr-restore

# 2. Copy .env and certs
cp /tmp/nvr-restore/.env /opt/gvd-nvr/.env
mkdir -p /opt/gvd-nvr/nginx/certs
cp /tmp/nvr-restore/certs/* /opt/gvd-nvr/nginx/certs/
cp /tmp/nvr-restore/go2rtc.yaml /opt/gvd-nvr/go2rtc.yaml

# 3. Start Postgres only
docker compose up -d postgres

# 4. Wait, then restore the DB dump
sleep 5
docker compose exec -T postgres psql -U nvr nvr < /tmp/nvr-restore/db_dump.sql

# 5. Run migrations (idempotent — brings schema to latest)
docker compose run --rm migrate

# 6. Start remaining services
docker compose up -d

# 7. Smoke test
curl -k https://localhost/api/health
curl -k -X POST https://localhost/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<your-admin-password>"}'
```

Confirm: login succeeds, camera list is populated, settings are intact.

---

## 3. Postgres Corruption

### Option A — WAL replay (soft corruption)

```bash
# Stop backend first to prevent writes
docker compose stop backend

# Check cluster integrity
docker compose exec postgres pg_dumpall --globals-only > /dev/null && echo "globals OK"

# Attempt WAL replay by restarting Postgres with recovery mode
docker compose restart postgres

# Inspect logs for recovery messages
docker compose logs postgres | grep -E "FATAL|ERROR|recovery|checkpoint"
```

### Option B — `pg_dump` rescue (partial corruption)

```bash
# Try to dump whatever rows are readable
docker compose exec postgres pg_dump -U nvr --no-owner --no-acl nvr \
  > /tmp/partial_dump.sql 2>/tmp/pg_dump_errors.txt

# Inspect errors
cat /tmp/pg_dump_errors.txt

# Create fresh DB and restore partial dump
docker compose exec postgres psql -U nvr -c "CREATE DATABASE nvr_restored;"
docker compose exec postgres psql -U nvr nvr_restored < /tmp/partial_dump.sql
```

### Option C — Last resort: recreate from migrations + backup

```bash
# 1. Stop everything
docker compose down

# 2. Delete the corrupt DB volume
docker volume rm gvd_nvr_db_data

# 3. Bring Postgres back up (empty)
docker compose up -d postgres
sleep 5

# 4. Run migrations (creates schema from scratch)
docker compose run --rm migrate

# 5. Restore latest backup dump
docker compose exec -T postgres psql -U nvr nvr < /path/to/db_dump.sql

# 6. Start remaining services
docker compose up -d
```

---

## 4. Lost Admin Password

Connect directly to Postgres and update the bcrypt hash:

```bash
# Get a psql shell
docker compose exec postgres psql -U nvr nvr

-- Inside psql:
-- Install pgcrypto if needed (only required once)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Reset admin password to "Admin@12345"
UPDATE users
SET hashed_password = crypt('Admin@12345', gen_salt('bf', 12))
WHERE username = 'admin';

-- Confirm
SELECT id, username, email, is_active FROM users WHERE username = 'admin';
\q
```

> **Note**: If the backend uses its own bcrypt implementation (not pg_crypt), generate the hash in Python:
>
> ```bash
> docker compose exec backend python -c \
>   "from passlib.context import CryptContext; c=CryptContext(schemes=['bcrypt']); print(c.hash('Admin@12345'))"
> ```
> Then:
> ```sql
> UPDATE users SET hashed_password = '<hash>' WHERE username = 'admin';
> ```

---

## 5. Lost JWT Secret

### Implications

All active sessions and refresh tokens are immediately invalidated when `JWT_SECRET_KEY` changes. Every logged-in user will be signed out and must log in again.

### Rotation procedure

```bash
# 1. Generate new secret
NEW_SECRET=$(openssl rand -hex 32)

# 2. Update .env
sed -i "s/^JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$NEW_SECRET/" .env

# 3. Revoke all refresh tokens in DB (optional but recommended)
docker compose exec postgres psql -U nvr nvr \
  -c "UPDATE refresh_tokens SET revoked = true WHERE revoked = false;"

# 4. Restart backend to pick up new secret
docker compose restart backend

# 5. Notify users — all sessions have been invalidated
```

---

## 6. NVR Move to New Host

```bash
# === ON OLD HOST ===

# 1. Stop the stack gracefully
docker compose down

# 2. Snapshot all named volumes
docker run --rm \
  -v gvd_nvr_db_data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/db_data.tgz -C /data .

docker run --rm \
  -v gvd_nvr_certs:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/certs.tgz -C /data .

docker run --rm \
  -v gvd_nvr_recordings:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/recordings.tgz -C /data .

# 3. Copy archive files + config to new host
scp db_data.tgz certs.tgz recordings.tgz .env go2rtc.yaml docker-compose.yml \
    newhost:/opt/gvd-nvr/

# === ON NEW HOST ===

cd /opt/gvd-nvr

# 4. Pull images
docker compose pull

# 5. Restore volumes
docker volume create gvd_nvr_db_data
docker run --rm \
  -v gvd_nvr_db_data:/data \
  -v $(pwd):/backup \
  alpine sh -c "tar xzf /backup/db_data.tgz -C /data"

docker volume create gvd_nvr_certs
docker run --rm \
  -v gvd_nvr_certs:/data \
  -v $(pwd):/backup \
  alpine sh -c "tar xzf /backup/certs.tgz -C /data"

docker volume create gvd_nvr_recordings
docker run --rm \
  -v gvd_nvr_recordings:/data \
  -v $(pwd):/backup \
  alpine sh -c "tar xzf /backup/recordings.tgz -C /data"

# 6. Update NVR_PUBLIC_HOST in .env if the IP changed
nano .env

# 7. Start the stack
docker compose up -d

# 8. Run migrations (idempotent)
docker compose run --rm migrate
```

---

## 7. Full Disaster (Lost Host, No Volume Snapshots)

```bash
# 1. Provision new host, install Docker
curl -fsSL https://get.docker.com | sh

# 2. Clone repo
git clone https://github.com/your-org/gvd-nvr.git /opt/gvd-nvr
cd /opt/gvd-nvr

# 3. Run installer (creates .env, self-signed certs, starts stack, creates admin)
sudo bash install.sh

# 4. Restore latest DB backup (from off-host backup storage)
docker compose stop backend
docker compose exec -T postgres psql -U nvr nvr < /path/to/db_dump.sql
docker compose run --rm migrate
docker compose start backend

# 5. Re-import license file if applicable
curl -X POST https://localhost/api/system/license/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/license.json" -k

# 6. Verify
curl -k https://localhost/api/health
```

> **Data loss**: all recordings and events created after the last backup will be lost.

---

## 8. Camera Inventory Recovery Without DB Backup

If the database is unrecoverable and no backup exists, camera credentials are lost but cameras can be re-discovered:

```bash
# Trigger ONVIF discovery on the local subnet
curl -X POST https://localhost/api/cameras/discover \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{"subnet": "192.168.1.0/24"}' -k
```

1. Review the discovered camera list in the UI (`/cameras` → Discovery).
2. For each discovered camera, click **Add** and enter the ONVIF credentials (these are stored only in the NVR database and must be re-entered by the operator).
3. Re-configure recording mode, schedules, and motion zones per camera.
4. Re-assign cameras to users if role-based access is in use.

> **Tip**: Maintain a separate camera inventory spreadsheet (IP, MAC, ONVIF credentials) in a secure credential store (e.g. Bitwarden, KeePass) so credentials survive a DB loss.

---

## Recovery Time / Recovery Point Objectives

| Scenario | Typical RTO | Typical RPO | Notes |
|---|---|---|---|
| Postgres soft corruption (WAL replay) | 5–15 min | 0 (no data loss if WAL intact) | Most common; usually auto-recovers |
| Postgres partial corruption (pg_dump rescue) | 30–60 min | Minutes to hours | Depends on extent of corruption |
| Last-resort DB recreate from migrations + backup | 1–2 h | Age of last backup | Restore recordings index only; raw video unaffected |
| Lost admin password | 5 min | 0 | No data loss |
| Lost JWT secret | 2 min | 0 | All sessions invalidated; no data loss |
| NVR move to new host (planned) | 30–60 min | Near-zero (volume snapshot) | Schedule during low-activity window |
| Full disaster (lost host, backup available) | 2–4 h | Age of last backup | Recordings after last backup lost |
| Full disaster (no backup) | 4–8 h | 100% DB loss | Camera inventory re-entry required |
| Camera inventory recovery (no DB backup) | 1–4 h | All camera metadata lost | Re-enter credentials manually |
