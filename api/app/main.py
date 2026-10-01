import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from prometheus_client import make_asgi_app
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import __version__, kv
from .config import LOCAL_ONLY, settings
from .db import get_session
from .metrics import REQUESTS
from .routes import admin, live, public



@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.require_secrets and LOCAL_ONLY in (settings.signing_key, settings.organizer_token):
        raise RuntimeError("TIXLAB_SIGNING_KEY and TIXLAB_ORGANIZER_TOKEN must be set (see tixlab-secrets)")
    kv.enable_expiry_events()
    yield


app = FastAPI(title="TixLab API", version=__version__, lifespan=lifespan)
app.mount("/metrics", make_asgi_app())


@app.middleware("http")
async def observe(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    if route is not None:  # skip 404s so unknown paths can't blow up label cardinality
        REQUESTS.labels(request.method, route.path, response.status_code).observe(time.perf_counter() - start)
    if request.url.path.startswith("/api/"):
        response.headers["X-Served-By"] = kv.POD
        kv.mark_pod_alive()
    return response


@app.get("/healthz")
def healthz():
    """Liveness: the process is up. Deliberately checks no dependencies."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response, session: Session = Depends(get_session)):
    """Readiness: take traffic only while Postgres and Valkey both answer."""
    checks = {}
    try:
        session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "down"
    try:
        checks["valkey"] = "ok" if kv.ping() else "down"
    except Exception:
        checks["valkey"] = "down"
    if "down" in checks.values():
        response.status_code = 503
    return checks


app.include_router(public.router)
app.include_router(live.router)
app.include_router(admin.router)
