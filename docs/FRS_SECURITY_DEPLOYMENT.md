# FRS Scenario — Security & Deployment Guide

Face Recognition (FRS) processes **biometric data** (face images, embeddings,
demographics). This is special-category / regulated data under GDPR Art. 9 and
BIPA. This document is the operator's reference for deploying FRS securely.

The product is **single-tenant**: one deployment = one organisation. There is no
cross-tenant isolation by design.

---

## 1. Encryption at rest (REQUIRED for biometric deployments)

Biometric data is stored in three places, all on local Docker volumes:

| Data | Location | Volume |
|------|----------|--------|
| Face photos (enrolled) | `/data/frs/persons/` | `frs_photos` |
| Live snapshots (sightings) | `/data/frs/snapshots/` | `frs_photos` |
| Face embeddings (vectors) | Qdrant storage | `qdrant_data` |
| Person PII + events | Postgres | `frs_db_data` |

Encryption at rest is enforced at the **disk/volume layer** (transparent, covers
all four stores, no application overhead, no impact on vector search). The
application does NOT encrypt at the file level — that is the wrong layer (it
cannot encrypt the searchable vectors, and disk encryption is the industry
standard).

### Option A — Encrypt the host disk (recommended, simplest)

Provision the host on an encrypted block device:

- **Bare metal / VM:** LUKS (dm-crypt) on the partition backing
  `/var/lib/docker`.
  ```bash
  cryptsetup luksFormat /dev/<disk>
  cryptsetup open /dev/<disk> cryptdocker
  mkfs.ext4 /dev/mapper/cryptdocker
  # mount at /var/lib/docker (or move the docker data-root there)
  ```
- **Cloud:** use an encrypted volume type — AWS EBS encryption, GCP CMEK
  persistent disks, Azure disk encryption. Enable at volume creation.

### Option B — Encrypt only the Docker volumes

If the whole disk can't be encrypted, back the FRS volumes with a LUKS-mapped
device and bind-mount it, or use a docker volume driver that encrypts
(e.g. `docker-volume-crypt`). Cover `frs_photos`, `qdrant_data`, `frs_db_data`.

### Key management

- Disk-encryption keys (LUKS / cloud KMS) are managed **outside** the
  application — by the OS keyring, a TPM, or the cloud KMS. Never store the
  disk key on the same disk.
- For cloud, prefer KMS-managed keys (CMEK) with rotation enabled.
- Document who holds the recovery key. Loss of key = loss of all biometric data
  (this is intended).

---

## 2. Service authentication

- The NVR ↔ plugin channel is gated by a shared **service token**
  (`AI_PLUGIN_SERVICE_TOKEN`). Set a **strong, random** value in production:
  ```bash
  export AI_PLUGIN_SERVICE_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
  ```
- The plugin **fails closed**: it refuses every request (503) if the token is
  unset or a known-insecure placeholder. The compose default token is for **dev
  only** — override it in production.
- The token is compared in constant time (no timing side-channel).
- The plugin port (8093) is **not** published to the host — it is reachable only
  on the internal Docker network, behind the NVR's licensed proxy.

## 3. Authorisation (RBAC)

Biometric actions require elevated role permissions (enforced at the NVR proxy):

| Action | Permission | Default roles |
|--------|-----------|---------------|
| Enroll / delete person / edit gallery | `manage_ai_faces` | admin |
| Investigate / recognize (search faces) | `search_ai_faces` | admin, operator |
| View events / attendance / tour | (camera-scoped) | per camera assignment |

Read routes are **camera-scoped**: an operator only sees faces/events from
cameras they are assigned to (`X-Vizor-Allowed-Camera-Ids`).

## 4. Audit logging

Every biometric access is audited (who, when, from where) in the NVR audit log:
`ai_face_enroll`, `ai_face_person_delete`, `ai_face_investigate`,
`ai_face_recognize`. Required for GDPR/BIPA access accountability.

## 5. Right to erasure (GDPR Art. 17)

Deleting a person purges **all** biometric traces in one transaction:
gallery vectors, live-sighting vectors, snapshot files, events, attendance,
photos, and the on-disk photo directory. If the vector store is briefly
unreachable, the pending erasure is recorded and retried by the retention
sweeper — erasure is not reported complete until vectors are gone.

## 6. Data retention (GDPR storage-limitation)

A background sweeper purges events + their snapshots + snapshot vectors older
than `FRS_RETENTION_EVENT_DAYS` (default 90). Enrolled gallery photos/persons
are never auto-purged. Set retention to match your policy:
```
FRS_RETENTION_EVENT_DAYS=90      # 0 = keep forever (not recommended)
FRS_RETENTION_SWEEP_HOURS=6
```

## 7. Input safety

- Uploads are verified by **magic-number** (real JPEG/PNG/WEBP), not the
  client-declared content type.
- Video-job source paths are confined to an allowlisted recordings root and
  ffmpeg is restricted to the `file` protocol (no SSRF / arbitrary file read).

## 8. Health & operations

- `GET /health` is a real liveness probe (DB, engine, live workers, disk). It
  returns **503 degraded** when the engine is down, no worker is decoding, or
  disk usage exceeds `FRS_DISK_WARN_PERCENT` (default 90) — so the orchestrator
  restarts a degraded container.
- All services have CPU + memory limits and `restart: unless-stopped`.
- Schema is managed by **Alembic migrations** (not `create_all`) — upgrades
  apply cleanly. Existing pre-Alembic installs are stamped to baseline on boot.

## 9. Scale model

- One deployment ("bundle") targets up to **64 channels / AI scenarios** on a
  single GPU node.
- Beyond 64 (→128, …), add another instance (bundle) and shard cameras across
  instances.
- Inference is served by a **shared Triton** instance across all AI scenarios
  (see the Triton migration). The GPU passthrough + `FRS_REQUIRE_GPU` settings
  fail loud if CUDA is not actually available, so a misconfigured host is caught
  at boot rather than silently crawling on CPU.

---

## Production checklist

- [ ] Disk / volume encryption enabled (Section 1)
- [ ] `AI_PLUGIN_SERVICE_TOKEN` set to a strong random value
- [ ] `FRS_REQUIRE_GPU=true` and GPU passthrough verified
- [ ] `FRS_RETENTION_EVENT_DAYS` set to your retention policy
- [ ] Roles reviewed (who has `manage_ai_faces` vs `search_ai_faces`)
- [ ] Audit log shipping / review process in place
- [ ] Backups of `frs_db_data` + `frs_photos` + `qdrant_data` (encrypted)
