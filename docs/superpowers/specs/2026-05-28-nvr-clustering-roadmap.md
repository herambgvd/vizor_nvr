# NVR Clustering / Failover — Roadmap

**Status:** Deferred from the 2026-05-28 NVR-completion sprint. Documented here so the design choices stay durable.

## Why this is its own sprint

Multi-NVR clustering touches every subsystem (storage, recording, events, auth, camera ownership). Trying to land it alongside small UI features rushes the architectural choices that will be hard to reverse. A standalone sprint forces us to pick:

- Storage backend (NFS, iSCSI, Ceph, S3-as-primary)
- Leader election protocol (Raft via etcd, simple lease via Postgres advisory locks, app-level heartbeats)
- Camera ownership model (sticky to leader vs sharded vs replicated)
- Event replication semantics (last-write-wins vs CRDT vs single-writer)
- Network topology (private cluster VLAN vs same LAN as cameras)

Each of these has multi-week downstream consequences.

## Use cases to target (priority order)

1. **Hot-standby pair** — two NVRs, one active, one passive. On active failure, passive takes over within ~30 s. Cameras keep recording (after a short gap during failover). Operators see one logical NVR.
2. **Load-shared cluster** — N NVRs each own a subset of cameras. UI sees a unified camera list. No HA — losing one NVR means losing recording for its cameras until manual recovery.
3. **Full HA cluster** — N NVRs, any subset can fail, recordings continue from any surviving node. Requires shared/replicated storage and continuous camera-ownership rebalancing.

Recommend starting with (1). It covers the SMB / mid-enterprise use case and unblocks compliance asks ("must have failover"). (2) and (3) are enterprise tier.

## Architectural sketch (hot-standby)

```
                ┌────────────┐         ┌────────────┐
                │  NVR-A      │  ◀──▶  │  NVR-B      │
                │  (active)   │ heart  │  (standby)  │
                └─────┬───────┘  beat  └─────┬───────┘
                      │                       │
                      ▼                       ▼
                  ┌──────────────────────────────┐
                  │  Shared storage (NFS / S3)   │
                  │  Postgres (replication)       │
                  └──────────────────────────────┘
                      ▲
                      │
                  ┌──────────────────────────────┐
                  │  Cameras (RTSP)              │
                  │  ONVIF, motion, etc.         │
                  └──────────────────────────────┘
```

**Leader lease:** Postgres `pg_advisory_lock` claimed by the active node. Heartbeat every 5 s; lease TTL 15 s. When the standby observes a lost lease, it claims, starts recording, and announces itself on the LAN via ONVIF Probe.

**Camera ownership:** trivial — the active node owns all cameras. Standby keeps connections warm but does not record/transcode.

**Storage:** segments written to an NFS mount that both nodes can reach. Recording manifests live in Postgres; both nodes can read.

**Postgres HA:** out of scope for the NVR — operator provides a Patroni / managed Postgres / streaming replica. We document the requirement.

**go2rtc:** each node runs its own go2rtc; the active node registers streams. On failover the standby re-registers everything.

**ONVIF device-server:** active node advertises itself. Standby is silent until promoted.

## Phases

| Phase | Scope | Estimated effort |
|---|---|---|
| 0 | This roadmap (done) | — |
| 1 | Cluster config + heartbeat + read-only standby flag (no failover) | 3–4 days |
| 2 | Shared-storage abstraction (`StorageBackend` interface, NFS impl, S3 impl) — migrate recording writes through it | 4–6 days |
| 3 | Postgres advisory-lock-based leader election; standby promotion path | 3–4 days |
| 4 | Failover smoke test: kill leader → standby takes over within 30 s, recording resumes | 2–3 days |
| 5 | Operator UI: cluster status page, manual failover button, split-brain warnings | 2 days |
| 6 | Documentation: deployment guide, NFS sizing, Postgres replication setup | 1–2 days |

**Total:** ~3 weeks for a single-engineer build.

## Open questions to resolve before Phase 1

- Do we ship our own Postgres replication tooling, or document the operator's responsibility?
- For air-gapped sites without NFS, is S3 (MinIO) acceptable as the only shared backend?
- What's the recording-segment write pattern that survives node failover mid-segment? (Likely: switch from continuous append to short rotating segments — 30–60 s each — so the standby can pick up at the next boundary without losing > 60 s.)
- How do clients discover the active node? (Floating IP via VRRP / keepalived? DNS RR? Operator-managed?)

## Not in scope (separate work)

- Cross-region replication
- Multi-master active/active
- Camera roaming between sites
- Browser-side cluster awareness (the UI talks to a single floating-IP endpoint)

## Decision needed before Phase 1 starts

Pick one of:

1. **Postgres-lease HA** (this design) — simplest, requires Postgres replication.
2. **etcd / Raft** — more battle-tested, adds an operational dependency.
3. **App-level heartbeats over UDP multicast** — zero-dep but reinvents consensus poorly. Not recommended.
