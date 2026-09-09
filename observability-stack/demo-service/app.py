"""A toy 'payments-api'-style service, deliberately built to mirror the bad-deploy
mock scenario (app/fixtures/scenarios/bad_deploy.py) so a live investigation and the
mocked one are telling structurally the same story with real signal instead of a
fixture. It exposes:

- Prometheus metrics at /metrics (request count, latency, error rate, a pool-in-use
  gauge mirroring the mock's db_pool_in_use metric)
- Structured JSON logs to stdout (shipped to Loki by Promtail via the docker socket)
- Error reporting to GlitchTip via its Sentry-compatible SDK
- POST /admin/break, which live-shrinks the simulated connection pool exactly the
  way bad-deploy's PR #4821 does in the mock world — the real trigger for a real
  investigation to have something to find.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel

SENTRY_DSN = __import__("os").environ.get("GLITCHTIP_DSN", "")
if SENTRY_DSN:
    sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0)

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
logger = logging.getLogger("payments-api")


def log_json(level: str, message: str, **fields: object) -> None:
    logger.info(json.dumps({"level": level, "message": message, "service": "payments-api", **fields}))


REQUESTS = Counter("http_requests_total", "Total requests", ["endpoint", "status"])
LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["endpoint"])
POOL_IN_USE = Gauge("db_pool_in_use", "Simulated DB connections currently in use")
POOL_SIZE = Gauge("db_pool_size_configured", "Simulated DB pool size (the config value)")

# The "bad deploy": starts healthy (size 20), /admin/break drops it to 5 to reproduce
# the exact regression the mock scenario models.
pool_size = 20
pool_semaphore = asyncio.Semaphore(pool_size)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_json("info", "payments-api starting", pool_size=pool_size)
    yield


app = FastAPI(lifespan=lifespan)


class BreakRequest(BaseModel):
    pool_size: int = 5


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/charge")
async def charge() -> dict[str, str]:
    start = time.monotonic()
    # Captured once, locally, at request start: /admin/break reassigns the module-level
    # pool_semaphore to a brand-new Semaphore object. An in-flight request that re-read
    # the global mid-request could acquire one semaphore instance and release a
    # DIFFERENT one after a break happens mid-flight — corrupting its internal counter
    # (observed as a negative db_pool_in_use during testing). Every acquire/release in
    # this request now consistently uses the one object captured here.
    sem = pool_semaphore
    configured_size = pool_size
    try:
        try:
            await asyncio.wait_for(sem.acquire(), timeout=0.3)
        except TimeoutError as e:
            REQUESTS.labels(endpoint="/charge", status="500").inc()
            log_json(
                "error",
                "QueuePool limit reached, connection timed out",
                pool_size=configured_size,
                trace="sqlalchemy.exc.TimeoutError",
            )
            if SENTRY_DSN:
                sentry_sdk.capture_exception(
                    TimeoutError(
                        f"QueuePool limit of size {configured_size} overflow 0 reached, "
                        "connection timed out, timeout 30"
                    )
                )
            raise HTTPException(status_code=500, detail="db pool exhausted") from e

        POOL_IN_USE.set(configured_size - sem._value)  # noqa: SLF001 - demo instrumentation only
        try:
            await asyncio.sleep(0.4)  # simulated work - long enough that pool_size=5 under
            # concurrent load actually queues past the 0.3s acquire timeout above
        finally:
            sem.release()
            POOL_IN_USE.set(configured_size - sem._value)  # noqa: SLF001

        REQUESTS.labels(endpoint="/charge", status="200").inc()
        return {"status": "charged"}
    finally:
        LATENCY.labels(endpoint="/charge").observe(time.monotonic() - start)


@app.post("/admin/break")
async def admin_break(req: BreakRequest) -> dict[str, object]:
    """Simulates deploying bad-deploy's PR #4821: shrinks the pool live, under load,
    exactly like a real bad deploy would. This is the only 'mutation' endpoint on
    this toy service and only exists to give a live investigation something real
    to find — it is not part of the AI SRE Investigator's own API surface."""
    global pool_size, pool_semaphore
    old_size = pool_size
    pool_size = req.pool_size
    pool_semaphore = asyncio.Semaphore(pool_size)
    POOL_SIZE.set(pool_size)
    log_json(
        "warn",
        f"Reduce DB pool size to cut idle connection cost: {old_size} -> {pool_size}",
        old_pool_size=old_size,
        new_pool_size=pool_size,
    )
    return {"old_pool_size": old_size, "new_pool_size": pool_size}


@app.post("/admin/restore")
async def admin_restore() -> dict[str, object]:
    global pool_size, pool_semaphore
    old_size = pool_size
    pool_size = 20
    pool_semaphore = asyncio.Semaphore(pool_size)
    POOL_SIZE.set(pool_size)
    log_json("info", f"Restored DB pool size: {old_size} -> {pool_size}")
    return {"old_pool_size": old_size, "new_pool_size": pool_size}


POOL_SIZE.set(pool_size)
