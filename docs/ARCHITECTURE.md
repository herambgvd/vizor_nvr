# Architecture & Developer Guide

New here? Read this top to bottom once. It maps the repo, explains how the parts
talk, states the conventions every module follows, and shows the dev loop. After
this you should be able to find any feature and add one the same way.

---

## 1. What Vizor NVR is

A commercial Network Video Recorder (VMS): ingest IP cameras (RTSP/ONVIF),
record to disk, play back, live-view in the browser, alarm on events, and run
optional AI scenarios (face recognition, suspect search, PPE) as licensed
plug-ins. Single-tenant, Docker-first, self-hosted.

Stack: **FastAPI** (async SQLAlchemy + Alembic) · **React** (CRA) · **Postgres/
TimescaleDB** · **go2rtc** (RTSP restream) · **ffmpeg** (record) · **nginx**
(TLS + reverse proxy) · **Triton** (shared GPU inference for AI plug-ins).

---

## 2. Repo map

```
vizor_nvr/
├── backend/              FastAPI app
│   ├── app/
│   │   ├── <module>/     one folder per domain — see §3
│   │   ├── core/         cross-cutting: auth deps, audit, ssrf, pagination, crypto
│   │   ├── services/     long-running background services (camera_monitor, …)
│   │   ├── database.py   async engine + get_db dependency
│   │   └── main.py       app factory: mounts every <module>/router.py
│   └── migrations/       Alembic — the ONLY way the schema changes
├── frontend/
│   └── src/
│       ├── pages/        one folder/file per screen (routed in App.js)
│       ├── components/   reusable UI (shell/, nvr/, ui/)
│       ├── api/          thin fetch wrappers per backend module
│       ├── hooks/        data hooks (useLiveCameras, …)
│       ├── context/      React context providers (auth, theme, branding)
│       └── lib/          utils — friendlyError(), formatting, etc.
├── scenarios/            AI plug-ins (standalone FastAPI services)
│   ├── frs/              face recognition
│   ├── suspect-search/   attribute / ReID person search
│   └── ppe/              PPE detection
├── triton/               shared GPU inference — model_repository/<model>/config.pbtxt
├── nginx/                TLS termination + reverse proxy config
├── docs/                 this file + the topic docs (see §8)
└── docker-compose*.yml   base + .ai (scenarios+triton) + .dev (overlay)
```

---

## 3. Backend module anatomy (the pattern to copy)

Every domain is a self-contained folder under `backend/app/`. To understand or
add a feature, you only need these files:

```
backend/app/<module>/
├── router.py     HTTP endpoints. Thin — validate, call service, return.
├── service.py    Business logic + DB queries. No FastAPI imports.
├── models.py     SQLAlchemy ORM tables + Pydantic request/response schemas.
└── __init__.py
```

Rules every module follows:

- **Router is thin.** It does auth (a `Depends`), input validation (Pydantic),
  calls the service, shapes the response. Logic lives in `service.py`.
- **Auth via dependencies** from `core/dependencies.py`: `get_current_user`,
  `get_admin_user`, `require_permission("…")`. Never re-implement auth in a route.
- **DB session via dependency**: `db: AsyncSession = Depends(get_db)`.
- **Mutations are audited**: `await write_audit(db, action=…, …)` then
  `await db.commit()`. See `core/audit_logger.py`.
- **List endpoints are paginated the same way** — see §5.
- **Errors are clean**: raise `HTTPException(status, "operator-readable text")`.
  Never leak stack traces, SQL, or internal tech names to the operator UI.

`main.py` auto-mounts each `<module>/router.py`. Adding a module = create the
folder, write the four files, import+include the router in `main.py`.

---

## 4. Frontend anatomy

- **Pages** (`src/pages/`) are routed in `src/App.js`. One screen = one page
  file/folder. Lazy-loaded.
- **API layer** (`src/api/`) is the only place that calls `fetch`/axios. Pages
  call api functions, never raw fetch. This keeps auth headers + base URL in one
  place.
- **Errors**: wrap backend failures with `friendlyError(err, fallback)` from
  `src/lib/utils.js` — it maps HTTP status to clean operator copy. Never render a
  raw backend error string.
- **No tech-expose**: the operator UI never shows technology names, internal
  service names, stack traces, or config internals. (This is an enterprise
  requirement — see KNOWN_LIMITATIONS for the audit history.)

---

## 5. API conventions

**Pagination — one envelope, everywhere.** Every paginated list endpoint takes
`?limit=&offset=` (default 50, max 1000) and returns:

```json
{ "items": [...], "total": 123, "limit": 50, "offset": 0 }
```

Use `core/pagination.py` (`PageParams` dependency + `paginated(items, total,
params)` helper). The frontend reads `.items` + `.total` everywhere. Small fixed
sets (users, roles, webhook configs) stay plain arrays — don't paginate those.

**Errors**: `HTTPException(status, detail)` with operator-readable `detail`.
Frontend maps via `friendlyError`.

**Auth**: Bearer JWT in `Authorization`. A few download routes also accept
`?token=` (documented limitation in KNOWN_LIMITATIONS).

---

## 6. AI scenarios

Each scenario in `scenarios/<slug>/` is a **standalone FastAPI service** with its
own Postgres + Qdrant, registered via `scenario.json`, reached through the
licensed NVR proxy. In production they are thin **Triton** clients (no in-process
GPU). Full detail: [AI_INFERENCE.md](AI_INFERENCE.md).

---

## 7. Dev loop

The stack is three compose files — **always use all three in dev** (the `.dev`
overlay points the backend at the live source; without it the backend reverts to
the prod image and routes 404):

```bash
docker compose -f docker-compose.yml -f docker-compose.ai.yml -f docker-compose.dev.yml up -d
```

Validate before restarting:

```bash
python3 -m py_compile backend/app/**/*.py        # backend syntax
npx @babel/parser frontend/src/pages/Foo.js       # frontend JSX parse
```

Schema changes go through Alembic only (never `create_all`). After adding a
migration file:

```bash
docker exec gvd_backend alembic upgrade head
```

Restart one service: `docker compose -f … -f … -f … restart backend`.

---

## 8. Docs index

| Doc | What |
|-----|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | This file — start here. |
| [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) | Honest flags: partial/absent/gated features + GA checklist. |
| [AI_INFERENCE.md](AI_INFERENCE.md) | AI architecture, Triton model table, GPU profiles, tuning. |
| [INSTALL_LINUX.md](INSTALL_LINUX.md) | Production install. |
| [SIZING.md](SIZING.md) / [CAPACITY_TESTING.md](CAPACITY_TESTING.md) | Hardware sizing + load test. |
| [ONVIF_COMPLIANCE.md](ONVIF_COMPLIANCE.md) | ONVIF Profile S/G conformance. |
| [DR_RUNBOOK.md](DR_RUNBOOK.md) / [../RUNBOOKS.md](../RUNBOOKS.md) | Operations + recovery. |
| [SUSPECT_SEARCH_SCENARIO.md](SUSPECT_SEARCH_SCENARIO.md) / [FRS_SECURITY_DEPLOYMENT.md](FRS_SECURITY_DEPLOYMENT.md) | Per-scenario detail. |

---

## 9. Where to start for a common task

| I want to… | Look at |
|------------|---------|
| Add a REST endpoint | `backend/app/<module>/router.py` + `service.py` (§3) |
| Change the DB schema | new file in `backend/migrations/versions/` (§7) |
| Add a screen | `frontend/src/pages/` + route in `App.js` + api fn in `src/api/` |
| Change inference / GPU sizing | `triton/model_repository/<model>/config.pbtxt` + AI_INFERENCE.md |
| Fix an operator-facing error message | the endpoint's `HTTPException` + `friendlyError` in the page |
| Understand what's NOT done | KNOWN_LIMITATIONS.md |
