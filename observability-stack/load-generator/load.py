"""Continuous CONCURRENT baseline traffic against the demo service. Must be
concurrent, not sequential — the whole point is contending for the simulated
connection pool once /admin/break shrinks it, and a single sequential client
can never create contention no matter how fast it loops."""
from __future__ import annotations

import asyncio
import os

import httpx

TARGET = os.environ.get("TARGET_URL", "http://demo-service:8000")
CONCURRENCY = int(os.environ.get("CONCURRENCY", "15"))
RATE_HZ_PER_WORKER = float(os.environ.get("RATE_HZ_PER_WORKER", "5"))


async def worker(client: httpx.AsyncClient, worker_id: int) -> None:
    interval = 1.0 / RATE_HZ_PER_WORKER
    while True:
        try:
            await client.post(f"{TARGET}/charge")
        except httpx.HTTPError:
            pass  # expected once the pool is exhausted - that's the point
        await asyncio.sleep(interval)


async def main() -> None:
    async with httpx.AsyncClient(timeout=2.0) as client:
        await asyncio.gather(*(worker(client, i) for i in range(CONCURRENCY)))


if __name__ == "__main__":
    asyncio.run(main())
