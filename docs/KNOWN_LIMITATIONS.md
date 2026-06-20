# Vizor NVR — Known Limitations & Honest Flags

Status snapshot of features that are **partial, absent, or deployment-gated**, so
nothing is over-promised in a sale or demo. Each item: what it is, current state,
and what closing it requires.

Legend: ❌ not implemented · ⚠️ partial / backend-only · 🔒 deployment-gated ·
📋 documented design limit.

---

## AI / Recognition

| Item | State | Detail |
|------|-------|--------|
| 64-camera FRS at scale | 🔒 | Architecture ready (Triton shared inference, NVDEC decode, backpressure, per-camera workers). **Capacity not yet load-validated** — pending a 64-stream test on a server GPU (RTX 5070 / A6000). Real numbers TBD; do not quote a hard channel count until measured. |
| PPE compliance accuracy | ⚠️ | Pipeline ported from a proven POC (temporal grace, smoothing, occlusion re-link, body-zone assignment) on Triton (`ppe_yolo26`) + the DINOv2 second-stage verifier (now hosted on Triton as `dinov2_small`, wired + verified). **Not yet validated on real site footage in-platform.** The DINOv2 linear heads + thresholds are POC-tuned to one camera; expect a per-deployment re-tune. |
| ANPR licensing | 🔒 | `anpr` is now in the dev signed license (re-signed) so it licenses + enables. For a customer build, include `anpr` in that customer's signed license `scenarios` list. |
| ANPR OCR accuracy | ⚠️ | Stock PP-OCRv6 (not fine-tuned on Indian plates) ≈ 48% exact / 70% char. Per-track voting + regex gate raise effective accuracy, but the **Indian-plate fine-tune (accumulated crops = training data) is the #1 lever** and is deferred. OCR confidence scale is un-softmaxed (POC parity) — the gate threshold may need a one-time re-tune on real footage. |
| ANPR speed estimate | 📋 | Single-camera speed is an **estimate** requiring per-camera calibration (a line + real-world distance). Uncalibrated → speed is omitted, never faked. Validate against known-speed footage before operators trust the numbers. |
| ANPR vehicle-type | ⚠️ | Derived from the shared `yolo26` COCO classes (car/motorcycle/bus/truck) via enclosing-box match — not a dedicated classifier; two-wheelers bucket as motorcycle, omitted when no vehicle encloses the plate. |
| FRS live face accuracy in field | ⚠️ | Recognition is byte-identical to the proven vizor-app pipeline (enrolled faces match 1.0). Live accuracy depends on camera placement (frontal vs top-down). Not yet validated against real site footage. |
| Suspect Search clothing/attribute accuracy | ⚠️ | Clothing model is YOLOS-Fashionpedia (research-grade, MIT). Garment-type + RGB-color + gender/age extraction works; **accuracy on real top-down CCTV is unverified**. Gender/age on non-frontal crops is unreliable. |
| Suspect Search end-to-end on real footage | ⚠️ | Synthetic-image verified only. Full clip-index → attribute-search → results not yet run on real recordings. |
| FCM push notifications | ⚠️ | Backend dispatch works **only if** `firebase-adminsdk.json` is mounted. There is **no operator UI** to configure push, register devices, or send a test. Email / SMS / WhatsApp / webhook are fully UI-configurable; push is not. |
| ArcFace request batching | 📋 | Re-exported with a dynamic batch axis + Triton dynamic batching. Throughput gain real; final batch sizing to be tuned with load-test data. |

## VMS Core

| Item | State | Detail |
|------|-------|--------|
| System reboot / factory reset | ❌ | No backend endpoint, no UI. The System tab is health-info only. |
| Config backup / restore | ⚠️ | Backend endpoints exist (`/settings/backup`, `/settings/restore`) and are safe (cameras/pools opt-in), but there is **no frontend UI** — unreachable from the app today. |
| RAID array management | ⚠️ | RAID **monitoring** is real (parses `mdadm`/`lsblk`, feeds metrics). Array **create/remove** endpoints exist but have **no operator UI**; only a poll-interval setting is surfaced. |
| Scheduled recording timezone | 🔒 | Honors `RECORDING_TIMEZONE` (IANA). Operators can set it from Time & NTP; defaults to UTC if unset. |
| Two-way audio (FFmpeg fallback) | 📋 | The WebRTC backchannel path works. The legacy FFmpeg/RTSP-backchannel fallback only works when the camera's real ONVIF backchannel URI is known; otherwise it correctly reports "not supported" rather than faking success. |
| ONVIF Profile G (recording server) | ⚠️ | Replay + real segment metadata work. WS-Push event notifications are stubbed (only PullPoint), `SystemReboot` unsupported, audio/metadata media configs return empty — stricter Profile S/G conformance clients may see gaps. |
| Multi-camera synchronized export | 📋 | PlaybackConsole exports per-camera clips with status + download. There is no single combined/stitched multi-cam file. |

## High Availability / Cluster

| Item | State | Detail |
|------|-------|--------|
| Zero-dual-write HA | 📋 | Cluster failover via a Postgres advisory lock + heartbeats. Split-brain is **mitigated, not prevented** — there is a brief dual-write window on a partition and no fencing/quorum/STONITH. The lock arbiter is a single Postgres; if that Postgres isn't itself HA, the standby has a non-redundant arbiter. **Do not market zero-dual-write HA** until fencing exists. |
| Lease TTL enforcement | ❌ | A lease TTL field exists but is not enforced — a hung-but-TCP-alive leader can hold the lock. |

## Notifications

| Item | State | Detail |
|------|-------|--------|
| Quiet hours | ❌ | No quiet-hours / time-window suppression. Per-recipient rate-limiting (throttle) exists. |
| Push device registration UI | ❌ | See FCM push above. |

## Operator-bookmark capture

| Item | State | Detail |
|------|-------|--------|
| Bookmark label/category at creation | ⚠️ | Backend + display support label & category; the quick-bookmark hotkey creates a note-less bookmark. A capture dialog for label/category is not built. |
| Legacy bookmark seek | 📋 | New bookmarks store an absolute seek anchor and jump correctly. Pre-existing bookmarks (no anchor) open the camera with a notice instead of seeking. |

## Security follow-ups (non-blocking)

| Item | State | Detail |
|------|-------|--------|
| Download tokens in URL | 📋 | Export/recording/thumbnail downloads pass the JWT as `?token=` (functional, matches the recording-download pattern) — lands in proxy/access logs. A single-use signed download-token endpoint exists and could replace it in a hardening pass. |
| GDPR personal-data export | ⚠️ | The "GDPR export" dumps audit rows, not the data subject's full personal data, and has no erasure counterpart for the platform user (FRS biometric erasure is separate and complete). |

---

## Validation still outstanding before GA

1. 64-camera FRS load test on a server GPU (capacity numbers).
2. FRS live-face validation on real site footage.
3. Suspect Search real-footage end-to-end + attribute-accuracy tuning.
4. 24-hour soak (memory/thread/fd stability under load).
5. Cluster fencing before any zero-dual-write HA claim.

Everything not listed here is implemented and audited end-to-end.
