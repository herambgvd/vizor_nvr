# Remove AI Functionality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strip all AI/inference functionality from GVD NVR so the project ships as a focused, market-ready Network Video Recorder. Keep licensing (NVR-only) and repurpose events ingest/SSE for NVR events.

**Architecture:** This is primarily a deletion task with surgical edits at the seams: `app.ai/` and `metropolis_bridge.py` go entirely; `main.py`, `config.py`, `license/`, and `events/` shed their AI hooks; a new Alembic migration drops AI tables; the frontend loses its `pages/ai/`, `camera-detail/ai/`, related API modules, and nav entries.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, React, React Router.

**Reference spec:** `docs/superpowers/specs/2026-05-27-remove-ai-functionality-design.md`

**Plan style:** Standard TDD does not apply (the work is deletion). Each task ends with concrete verification commands (greps, build, boot) that must produce empty/clean output before commit.

---

## Task 1: Establish baseline — verify backend boots and tests pass before any changes

**Files:** none

- [ ] **Step 1: Confirm git working tree is clean**

Run: `git status --short`
Expected: empty output.

- [ ] **Step 2: Boot backend to confirm baseline**

Run from `backend/`: `python -c "from app.main import app; print('ok')"`
Expected: `ok` (imports succeed against existing AI surface).

- [ ] **Step 3: Run backend tests (baseline pass)**

Run from `backend/`: `pytest -x -q 2>&1 | tail -20`
Expected: tests pass (or known-failing tests are noted — record any failures so we don't blame our deletion).

- [ ] **Step 4: Frontend build baseline**

Run from `frontend/`: `npm run build 2>&1 | tail -20`
Expected: build succeeds.

(No commit — this is just baseline.)

---

## Task 2: Backend — delete `app/ai/` and `metropolis_bridge.py`

**Files:**
- Delete: `backend/app/ai/` (recursive)
- Delete: `backend/app/services/metropolis_bridge.py`

> NOTE: After this task `app.main` will fail to import until Task 3 removes the references. That is expected; do not attempt to boot between tasks 2 and 3.

- [ ] **Step 1: Delete the AI package**

Run: `git rm -r backend/app/ai`
Expected: many files staged for deletion.

- [ ] **Step 2: Delete the Metropolis bridge**

Run: `git rm backend/app/services/metropolis_bridge.py`
Expected: file staged for deletion.

- [ ] **Step 3: Verify nothing else imports from `app.ai` or `metropolis_bridge` that we haven't yet handled**

Run: `grep -rn "from app.ai\|app\.ai\.\|metropolis_bridge" backend/app --include="*.py"`
Expected output (only the known callers in `main.py` and `license/router.py`):
```
backend/app/main.py:56:            from app.ai.seed import seed_ai_scenarios
backend/app/main.py:166:        from app.services.metropolis_bridge import start_metropolis_bridge
backend/app/main.py:173:        from app.ai.people.counts_writer import start as start_counts_writer
backend/app/main.py:208:        from app.ai.people.counts_writer import stop as stop_counts_writer
backend/app/main.py:335:from app.ai.scenarios_router import router as ai_scenarios_router
backend/app/main.py:336:from app.ai.frs_router import router as ai_frs_router
backend/app/main.py:337:from app.ai.frs_photos_router import router as ai_frs_photos_router
backend/app/main.py:338:from app.ai.people.router import router as ai_people_router, control_router as ai_control_router
backend/app/main.py:339:from app.ai.frs.router import router as ai_frs_actions_router
backend/app/license/router.py:25:    from app.ai.models import CameraAIConfig
```
If any other matches appear, stop and add a task to handle them before proceeding.

- [ ] **Step 4: Commit deletion**

```bash
git commit -m "chore(ai): delete app/ai package and metropolis_bridge

Backend will not import until main.py and license/router.py are
updated in the next tasks.
"
```

---

## Task 3: Backend — remove AI hooks from `main.py`

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Remove `seed_ai_scenarios` block**

Find the try/except in the startup lifespan (around lines 55–59):
```python
        try:
            from app.ai.seed import seed_ai_scenarios
            await seed_ai_scenarios(db)
        except Exception as _e:
            logger.warning(f"AI scenario seeding failed: {_e}")
```
Delete the entire block.

- [ ] **Step 2: Remove Metropolis bridge startup**

Find the block around lines 163–169:
```python
    # Start Metropolis bridge (Redis Stream consumer -> /api/events/ingest)
    # No-op unless METROPOLIS_BRIDGE_ENABLED=true env var is set.
    try:
        from app.services.metropolis_bridge import start_metropolis_bridge
        await start_metropolis_bridge()
    except Exception as _e:
        logger.warning(f"Metropolis bridge startup skipped: {_e}")
```
Delete it.

- [ ] **Step 3: Remove `counts_writer` start**

Find the block around line 173 starting with `from app.ai.people.counts_writer import start as start_counts_writer` and delete the entire surrounding try/except (typically 4–6 lines including the call and error handler).

- [ ] **Step 4: Remove `counts_writer` stop**

Find the block around line 208 starting with `from app.ai.people.counts_writer import stop as stop_counts_writer` and delete the surrounding try/except.

- [ ] **Step 5: Remove AI router imports**

Delete lines that read:
```python
from app.ai.scenarios_router import router as ai_scenarios_router
from app.ai.frs_router import router as ai_frs_router
from app.ai.frs_photos_router import router as ai_frs_photos_router
from app.ai.people.router import router as ai_people_router, control_router as ai_control_router
from app.ai.frs.router import router as ai_frs_actions_router
```

- [ ] **Step 6: Remove AI `include_router` calls**

Delete lines:
```python
app.include_router(ai_scenarios_router)
app.include_router(ai_frs_router)
app.include_router(ai_frs_photos_router)
app.include_router(ai_people_router)
app.include_router(ai_control_router)
app.include_router(ai_frs_actions_router)
```

- [ ] **Step 7: Verify `main.py` has no `app.ai`/`metropolis_bridge` references**

Run: `grep -n "app\.ai\|metropolis_bridge\|seed_ai_scenarios\|counts_writer" backend/app/main.py`
Expected: empty output.

- [ ] **Step 8: Verify `main.py` imports cleanly**

Run from `backend/`: `python -c "from app.main import app; print('ok')"`
Expected: prints `ok` (may still fail if `license/router.py` still imports `CameraAIConfig` — if so, proceed to Task 4 then re-run).

- [ ] **Step 9: Commit**

```bash
git add backend/app/main.py
git commit -m "chore(ai): remove AI router/service wiring from main.py"
```

---

## Task 4: Backend — strip AI fields from licensing module

**Files:**
- Modify: `backend/app/license/router.py`
- Modify: `backend/app/license/service.py`

- [ ] **Step 1: Update `license/router.py` to drop AI counts**

Replace the `_counts` helper (around lines 22–35) so it returns only the camera total. Replace the existing function with:

```python
async def _counts(db: AsyncSession) -> int:
    cam_total = (await db.execute(select(func.count(Camera.id)))).scalar() or 0
    return int(cam_total)
```

Then in every call site, replace the tuple unpack pattern `cam, ai_cam = await _counts(db)` with `cam = await _counts(db)`, and replace `svc.snapshot(cam, ai_cam)` with `svc.snapshot(cam)`.

Remove the `from app.ai.models import CameraAIConfig` import.

- [ ] **Step 2: Update `license/service.py` LicensePayload**

In the dataclass (around lines 45–55), delete `ai_camera_limit` and `scenarios` fields. In `from_dict`, remove the lines that parse them. Update the logger format string (around line 120) to drop `ai=%s scenarios=%s` and the corresponding values.

- [ ] **Step 3: Update `snapshot()` and related accessors**

Change `snapshot(self, camera_count: int, ai_camera_count: int)` (line ~253) to `snapshot(self, camera_count: int)`. Remove the `ai_camera_limit` and `scenarios` keys from the returned dict (lines ~269–270). Delete the `ai_camera_limit` property (lines ~244–246) and the `scenario_allowed` / similar scenario-checking method around line 240 (`return slug in (self._payload.scenarios if self._payload else [])`).

- [ ] **Step 4: Find and fix any other callers of removed methods**

Run: `grep -rn "ai_camera_limit\|\.scenarios\b\|scenario_allowed" backend/app --include="*.py"`
Expected: empty (or only matches that we deleted).
If anything remains, fix the caller — likely by deletion since the AI surface is gone.

- [ ] **Step 5: Verify license import + main import**

Run from `backend/`:
```bash
python -c "from app.license.service import LicenseService, LicensePayload; print('ok')"
python -c "from app.main import app; print('ok')"
```
Expected: both print `ok`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/license/router.py backend/app/license/service.py
git commit -m "chore(ai): strip AI fields from licensing module

License payload now exposes only NVR seat/camera limits.
ai_camera_limit and scenarios fields removed.
"
```

---

## Task 5: Backend — purge AI env vars from `config.py`

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Delete the AI/Inference settings block**

Remove the entire block (lines ~117–128):
```python
    # ── AI / Inference ─────────────────────────────────────────────────
    QDRANT_URL: str = os.getenv("QDRANT_URL", "")
    TRITON_URL: str = os.getenv("TRITON_URL", "")
    # Bridge between DeepStream / Metropolis event streams and the
    # NVR's /api/events/ingest endpoint.
    METROPOLIS_BRIDGE_ENABLED: bool = (
        os.getenv("METROPOLIS_BRIDGE_ENABLED", "false").lower() == "true"
    )
    # Redis stream key the bridge listens on (DeepStream publishes here)
    AI_EVENT_STREAM: str = os.getenv("AI_EVENT_STREAM", "ai:events")
    AI_EVENT_GROUP: str = os.getenv("AI_EVENT_GROUP", "nvr-bridge")
```

- [ ] **Step 2: Verify no consumer references those settings**

Run: `grep -rn "QDRANT_URL\|TRITON_URL\|METROPOLIS_BRIDGE_ENABLED\|AI_EVENT_STREAM\|AI_EVENT_GROUP" backend/app --include="*.py"`
Expected: empty output.

- [ ] **Step 3: Boot test**

Run from `backend/`: `python -c "from app.config import settings; print(settings.DB_URL)"`
Expected: prints DB URL with no AttributeError.

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py
git commit -m "chore(ai): remove AI/Metropolis env settings from config"
```

---

## Task 6: Backend — repurpose events ingest + SSE routers for NVR-only

**Files:**
- Modify: `backend/app/events/sse_router.py`
- Modify: `backend/app/events/ingest_router.py`

- [ ] **Step 1: SSE router — drop AI-specific surface**

In `sse_router.py`:
- Remove the `scenario` query parameter from the streaming endpoint signature and from its `Query(...)` declaration.
- Remove the filter block `if scenario and payload.get("scenario") != scenario: continue`.
- Change the emitted event name from `"event": "ai_event"` to `"event": "event"` (or another neutral name such as `"nvr_event"`; pick one consistently and update the docstring).
- Update the module docstring at the top to describe NVR events (motion, ONVIF, system) — remove the `scenario=people_counting` example and replace with e.g. `event_type=motion&camera_id=...`.

- [ ] **Step 2: Ingest router — drop AI-specific fields**

In `ingest_router.py`:
- Remove the `person_id` field from the event Pydantic model (around line 67).
- Update the `source_service` field comment to drop the `vizor-gpu-frs` example (use NVR examples like `"nvr-motion-detector"`).
- Remove any scenario-specific validation. The event model should accept: `source_service`, `event_type`, `camera_id`, `timestamp`, `payload` (free-form dict), `dedup_key`.
- Update the module docstring.

- [ ] **Step 3: Find frontend / external consumers of the removed fields**

Run: `grep -rn "ai_event\|person_id.*frs\|scenario.*query" frontend/src backend 2>/dev/null`
Expected: only frontend code that will be deleted in later tasks. Note any non-deleted matches and add a task to clean them up.

- [ ] **Step 4: Boot + import check**

Run from `backend/`: `python -c "from app.events.sse_router import router; from app.events.ingest_router import router; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/events/sse_router.py backend/app/events/ingest_router.py
git commit -m "refactor(events): repurpose ingest/SSE routers for NVR events

Drop scenario filter, person_id field, and AI-specific examples.
Routers now serve generic motion / ONVIF / system events.
"
```

---

## Task 7: Backend — Alembic migration to drop AI tables

**Files:**
- Create: `backend/migrations/versions/20260527_000000_remove_ai_tables.py`

- [ ] **Step 1: Identify the current head revision**

Run from `backend/`: `alembic heads`
Expected: a single revision id. Record it as `PREV_REV`.

- [ ] **Step 2: Create the migration file**

Create `backend/migrations/versions/20260527_000000_remove_ai_tables.py`:

```python
"""remove AI tables

Revision ID: 20260527_000000
Revises: <PREV_REV>
Create Date: 2026-05-27

Drops all AI-related tables. Down-revision recreates them as empty
shells (no data preserved) so test rollback works.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260527_000000"
down_revision = "<PREV_REV>"  # replace with the id from `alembic heads`
branch_labels = None
depends_on = None


AI_TABLES = [
    # Drop in dependency order — children before parents.
    "frs_attendance",
    "frs_photos",
    "frs_investigations",
    "frs_persons",
    "frs_groups",
    "people_counts",
    "people_count_zones",
    "vq_captions",
    "vq_attributes",
    "inference_jobs",
    "model_deployments",
    "models",
    "webhook_deliveries",
    "webhook_subscriptions",
    "metropolis_services",
    "camera_ai_configs",
    "ai_scenarios",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for table in AI_TABLES:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    # Recreate as empty shells; we do not preserve AI data across the purge.
    # Each table gets only an `id` PK so the migration is reversible without
    # reimplementing the full original schema.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for table in reversed(AI_TABLES):
        if table not in existing:
            op.create_table(
                table,
                sa.Column("id", sa.Integer, primary_key=True),
            )
```

> Replace `<PREV_REV>` (in both the docstring and `down_revision`) with the revision id from Step 1.

- [ ] **Step 3: Confirm no app code references the dropped tables**

Run: `grep -rn "frs_persons\|frs_groups\|frs_photos\|people_counts\|ai_scenarios\|camera_ai_configs\|vq_captions\|vq_attributes" backend/app --include="*.py"`
Expected: empty (the ORM models were deleted in Task 2).

- [ ] **Step 4: Apply migration on a scratch DB**

Run from `backend/`:
```bash
rm -f /tmp/nvr_migration_test.db
DATABASE_URL=sqlite+aiosqlite:////tmp/nvr_migration_test.db alembic upgrade head
DATABASE_URL=sqlite+aiosqlite:////tmp/nvr_migration_test.db alembic downgrade -1
DATABASE_URL=sqlite+aiosqlite:////tmp/nvr_migration_test.db alembic upgrade head
```
Expected: all three commands succeed. (Use whatever env var the project actually reads for DB URL — check `app/config.py` and adjust.)

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/20260527_000000_remove_ai_tables.py
git commit -m "feat(db): migration to drop all AI tables

Drops frs_*, people_count*, ai_scenarios, camera_ai_configs,
models, model_deployments, inference_jobs, vq_*, webhook_*,
metropolis_services. Downgrade recreates empty shells only.
"
```

---

## Task 8: Backend — remove AI deps from `requirements.txt`

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Inspect current requirements for AI-only deps**

Run: `grep -niE "qdrant|triton|insightface|onnxruntime|deepstream|tensorrt|tritonclient" backend/requirements.txt`
Record the matching lines.

- [ ] **Step 2: Confirm those packages are unused elsewhere**

For each matched package, run e.g.:
```bash
grep -rn "import qdrant\|from qdrant" backend/app --include="*.py"
grep -rn "import tritonclient\|from tritonclient" backend/app --include="*.py"
grep -rn "import insightface\|from insightface" backend/app --include="*.py"
grep -rn "import onnxruntime\|from onnxruntime" backend/app --include="*.py"
```
Expected: all empty.

- [ ] **Step 3: Delete the matched lines from `backend/requirements.txt`**

Edit the file and remove the lines identified in Step 1. Do **not** remove `numpy`, `opencv-*`, or other libs that other modules might use without confirming with grep first.

- [ ] **Step 4: Re-resolve dependencies (optional but recommended)**

Run from `backend/`: `pip install -r requirements.txt` (in your venv) and ensure no error.

- [ ] **Step 5: Boot test**

Run from `backend/`: `python -c "from app.main import app; print('ok')"`
Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore(deps): drop AI-only Python dependencies"
```

---

## Task 9: Backend — final verification

**Files:** none

- [ ] **Step 1: Grep for any remaining AI references**

Run:
```bash
grep -rnE "app\.ai|metropolis_bridge|TRITON_URL|QDRANT_URL|seed_ai_scenarios|ai_scenarios_router|frs_router|counts_writer" backend/app --include="*.py"
```
Expected: empty.

- [ ] **Step 2: Run backend tests**

Run from `backend/`: `pytest -x -q 2>&1 | tail -30`
Expected: pass. Failing tests likely belong to AI surface — if so, delete those test files in a follow-up step (Step 3 below).

- [ ] **Step 3: Delete AI-only test files (if any)**

Run: `find backend/tests -path '*ai*' -o -name 'test_frs*' -o -name 'test_metropolis*' 2>/dev/null`
Delete any matches with `git rm`, then re-run `pytest -x -q`.

- [ ] **Step 4: Boot the app via uvicorn**

Run from `backend/`: `uvicorn app.main:app --port 18000 &` then `sleep 2 && curl -fsS http://localhost:18000/api/health && echo` then `kill %1`.
Expected: health endpoint returns 200/200-shaped JSON.

- [ ] **Step 5: Commit any test-file deletions**

```bash
git add -A backend/tests
git commit -m "chore(ai): drop AI-related test files" || echo "nothing to commit"
```

---

## Task 10: Frontend — delete AI pages and API modules

**Files:**
- Delete: `frontend/src/pages/ai/`
- Delete: `frontend/src/pages/camera-detail/ai/`
- Delete: `frontend/src/components/camera/CameraAITab.js`
- Delete: `frontend/src/hooks/useLiveDetections.js`
- Delete: `frontend/src/api/ai.js`, `frontend/src/api/frs.js`, `frontend/src/api/people.js`

> NOTE: After this task `npm run build` will fail until Task 11 removes the imports from `App.js`, `Layout.js`, and `LicensePage.js`. Expected.

- [ ] **Step 1: Delete the AI page trees**

Run:
```bash
git rm -r frontend/src/pages/ai
git rm -r frontend/src/pages/camera-detail/ai
```

- [ ] **Step 2: Delete components, hooks, and api modules**

Run:
```bash
git rm frontend/src/components/camera/CameraAITab.js
git rm frontend/src/hooks/useLiveDetections.js
git rm frontend/src/api/ai.js frontend/src/api/frs.js frontend/src/api/people.js
```

- [ ] **Step 3: Confirm only known callers reference these deletions**

Run: `grep -rn "pages/ai\|pages/camera-detail/ai\|CameraAITab\|useLiveDetections\|api/ai\|api/frs\|api/people" frontend/src`
Expected: matches confined to `frontend/src/App.js`, `frontend/src/pages/Layout.js`, `frontend/src/pages/camera-detail/CameraDetailLayout.js` (if it imports the AI tab), `frontend/src/pages/settings/LicensePage.js`, and `frontend/src/hooks/useLicense.js`. Anything else → add a task before continuing.

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(ai): delete frontend AI pages, components, hooks, APIs

App will not build until App.js / Layout.js are updated next.
"
```

---

## Task 11: Frontend — remove AI routes from `App.js`

**Files:**
- Modify: `frontend/src/App.js`

- [ ] **Step 1: Delete AI lazy imports**

In `App.js` remove every `lazy(() => import(...))` that references `./pages/ai/...` or `./pages/camera-detail/ai/...` (lines ~49–83 in the current file). Confirm with:

```bash
grep -n "pages/ai\|camera-detail/ai" frontend/src/App.js
```
Expected after edit: empty.

- [ ] **Step 2: Delete AI route declarations**

Remove:
- The `<Route path="ai" element={<CameraAILayout />}>` nested under `cameras/:cameraId` (around line 169) and its children.
- The whole `{/* AI Modules — system-wide scenario workspace */}` block (lines ~178–215) — `ai/modules`, `ai/modules/people_counting`, `ai/modules/frs`, `ai/modules/ppe`, `ai/modules/:slug`, plus the `<Navigate>` aliases for `ai/scenarios` and `ai/persons`.

- [ ] **Step 3: Verify**

Run: `grep -n "/ai/\|<AIModulesIndex\|<ScenarioLayout\|<FRS\|<PPE\|<CameraAILayout\|<CameraScenarioConfig\|<ScenarioStub\|<PeopleCounting" frontend/src/App.js`
Expected: empty.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.js
git commit -m "chore(ai): remove AI lazy imports and routes from App.js"
```

---

## Task 12: Frontend — remove AI from main nav and camera-detail tabs

**Files:**
- Modify: `frontend/src/pages/Layout.js`
- Modify: `frontend/src/pages/camera-detail/CameraDetailLayout.js` (only if it references the AI tab)

- [ ] **Step 1: Update Layout.js nav**

In `frontend/src/pages/Layout.js`:
- Update the top file comment from "5 primary nav items: Dashboard, Cameras, Events, AI Modules, Settings" → "4 primary nav items: Dashboard, Cameras, Events, Settings".
- Remove the second comment line referencing "under AI Modules".
- Remove the nav array entry that points to `/ai/modules` with label `"AI Modules"` (around lines 77–78), including its icon import if it is now unused.

- [ ] **Step 2: Update CameraDetailLayout (if needed)**

Run: `grep -n "ai\|AI" frontend/src/pages/camera-detail/CameraDetailLayout.js`
If the file contains an AI tab entry, remove it (the tab definition and the corresponding nested `Route` was already deleted in Task 11).

- [ ] **Step 3: Verify**

Run:
```bash
grep -n "ai/modules\|AI Modules" frontend/src/pages/Layout.js
grep -n "AI" frontend/src/pages/camera-detail/CameraDetailLayout.js
```
Expected: empty.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Layout.js frontend/src/pages/camera-detail/CameraDetailLayout.js
git commit -m "chore(ai): remove AI Modules nav entry and camera AI tab"
```

---

## Task 13: Frontend — strip AI fields from License page and hook

**Files:**
- Modify: `frontend/src/pages/settings/LicensePage.js`
- Modify: `frontend/src/hooks/useLicense.js`

- [ ] **Step 1: Inspect LicensePage**

Run: `grep -n "ai_camera_limit\|scenarios\|ai_cam" frontend/src/pages/settings/LicensePage.js`
For each match, remove the corresponding UI element (table row, badge, etc.). If a section becomes empty after removal, delete the section too.

- [ ] **Step 2: Inspect useLicense hook**

Run: `grep -n "ai_camera_limit\|scenarios\|ai_cam" frontend/src/hooks/useLicense.js`
Remove any destructuring / defaults / TypeScript-style annotations for those fields.

- [ ] **Step 3: Verify**

Run: `grep -rn "ai_camera_limit\|ai_cam\b" frontend/src`
Expected: empty.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/settings/LicensePage.js frontend/src/hooks/useLicense.js
git commit -m "chore(ai): drop AI license fields from settings UI"
```

---

## Task 14: Frontend — final verification

**Files:** none

- [ ] **Step 1: Grep for any remaining AI references**

Run:
```bash
grep -rnE "pages/ai|camera-detail/ai|CameraAITab|useLiveDetections|api/ai\b|api/frs|api/people|AI Modules|/ai/modules|ai_camera_limit" frontend/src
```
Expected: empty.

- [ ] **Step 2: Build**

Run from `frontend/`: `npm run build 2>&1 | tail -30`
Expected: build succeeds, no missing-module errors.

- [ ] **Step 3: Boot dev server and smoke-test in a browser**

Run from `frontend/`: `npm start` (or the project's dev command) and confirm:
- App loads at `/`.
- Nav shows exactly 4 items: Dashboard, Cameras, Events, Settings.
- Navigating to `/cameras`, `/events`, `/settings` works.
- `/ai/modules` (typed manually) gives the app's not-found handling (404 or redirect).
- Camera Detail tabs: Live, Recordings, ONVIF, Settings — no AI tab.

Stop the dev server when done.

- [ ] **Step 4: Commit any build-output cleanup if needed**

If `npm run build` revealed stray dead-import warnings that you fixed, commit those fixes:
```bash
git add -A frontend/src
git commit -m "chore(ai): clean up stray frontend imports after AI removal" || echo "nothing to commit"
```

---

## Task 15: End-to-end smoke test

**Files:** none

- [ ] **Step 1: Apply migrations on a fresh DB**

Run from `backend/` against a scratch DB:
```bash
rm -f /tmp/nvr_e2e.db
DATABASE_URL=sqlite+aiosqlite:////tmp/nvr_e2e.db alembic upgrade head
```
Expected: success.

- [ ] **Step 2: Boot backend + frontend together**

Start both via the project's standard dev commands (`docker-compose -f docker-compose.dev.yml up` if that's the entry point, otherwise `uvicorn app.main:app` + `npm start`).

- [ ] **Step 3: Walk through the NVR happy path**

Verify in the running app:
- Add a camera (real or mock) → it appears in the list.
- Live view streams.
- Start a recording, stop it, confirm it shows in Recordings.
- Bookmark a moment in playback.
- Add a notification target (webhook/SMTP), trigger a motion event, confirm delivery log.
- Activate a license, confirm camera limit shows correctly with no AI fields.

- [ ] **Step 4: Final repo-wide AI grep**

Run:
```bash
grep -rnE "app\.ai|pages/ai|camera-detail/ai|TRITON_URL|QDRANT_URL|metropolis_bridge|CameraAITab|ai_camera_limit|seed_ai_scenarios|frs_persons|frs_groups|people_counts\b" --include="*.py" --include="*.js" --include="*.jsx" --include="*.ts" --include="*.tsx" backend/app frontend/src
```
Expected: empty (or only matches inside the new migration file `20260527_000000_remove_ai_tables.py`, which is fine because it names the tables to drop).

- [ ] **Step 5: Final commit (if needed) and push**

```bash
git status
# If any pending fixes from the smoke test, commit them with a clear message.
```

---

## Self-Review Notes

- **Spec coverage:** All bullets from the spec map to tasks — backend deletes (Task 2), main.py edits (Task 3), license edits (Task 4), config edits (Task 5), events repurpose (Task 6), migration (Task 7), deps (Task 8), backend verify (Task 9), frontend deletes (Task 10), App.js (Task 11), Layout/CameraDetail (Task 12), LicensePage + useLicense (Task 13), frontend verify (Task 14), E2E (Task 15).
- **Placeholders:** Only `<PREV_REV>` in Task 7, explicitly flagged for substitution from `alembic heads` output. No "TBD" or "handle edge cases".
- **Inter-task consistency:** `_counts` returns `int` (Task 4 Step 1) and `snapshot(camera_count: int)` matches (Step 3). Migration table list (Task 7) covers every `__tablename__` discovered in `backend/app/ai/models.py` plus `metropolis_services`.
- **Known risk per spec:** License files in the wild may carry `ai_camera_limit`/`scenarios` keys — `from_dict` uses `.get(..., default)` so unknown extra keys are ignored by Python dataclass construction *only* because we remove the fields entirely. Verified in Task 4 Step 2 instructions.
