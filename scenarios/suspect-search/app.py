from __future__ import annotations

from fastapi import FastAPI

from routers.health import router as health_router
from routers.jobs import router as jobs_router
from routers.reports import router as reports_router
from services.runtime import PORT, _startup

app = FastAPI(title="Vizor Suspect Search", version="0.2.0")
app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(reports_router)


@app.on_event("startup")
def startup() -> None:
    _startup()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
