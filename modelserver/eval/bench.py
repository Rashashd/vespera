"""Throughput and latency benchmark for classify and embed (FR-021 / D11).

Not CI-gated — run manually from repo root to validate performance characteristics.

Usage:
    uv run python modelserver/eval/bench.py

Env vars:
    MODELSERVER_URL    — default http://localhost:8001
    MODELSERVER_TOKEN  — service token (required)
    BENCH_BATCH_SIZE   — texts per request, default 32
    BENCH_ROUNDS       — number of requests, default 20
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time

import httpx

URL = os.environ.get("MODELSERVER_URL", "http://localhost:8001")
TOKEN = os.environ.get("MODELSERVER_TOKEN", "")
BATCH_SIZE = int(os.environ.get("BENCH_BATCH_SIZE", "32"))
ROUNDS = int(os.environ.get("BENCH_ROUNDS", "20"))

SAMPLE_TEXTS = [
    "patient developed acute liver failure after starting drug X",
    "no adverse events were observed during the 12-week clinical trial",
    "severe hepatotoxicity following treatment with the compound",
    "the medication was well tolerated by all study participants",
]


def _make_texts(n: int) -> list[str]:
    return [SAMPLE_TEXTS[i % len(SAMPLE_TEXTS)] for i in range(n)]


async def _bench_endpoint(client: httpx.AsyncClient, path: str, rounds: int, batch: int) -> None:
    texts = _make_texts(batch)
    payload = {"texts": texts}
    latencies: list[float] = []

    # Warmup
    await client.post(path, json=payload)

    for _ in range(rounds):
        t0 = time.perf_counter()
        r = await client.post(path, json=payload)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            print(f"  WARN: {path} returned {r.status_code}")
            continue
        latencies.append(elapsed_ms)

    if not latencies:
        print(f"  {path}: no successful responses")
        return

    latencies.sort()
    p50 = statistics.median(latencies)
    p95_idx = int(len(latencies) * 0.95)
    p95 = latencies[min(p95_idx, len(latencies) - 1)]
    throughput = (len(latencies) * batch) / (sum(latencies) / 1000)

    print(f"  {path}  batch={batch}  rounds={len(latencies)}")
    print(f"    p50={p50:.1f}ms  p95={p95:.1f}ms  throughput={throughput:.0f} texts/s")


async def main() -> None:
    if not TOKEN:
        print("ERROR: MODELSERVER_TOKEN env var is required")
        return

    print(f"Benchmarking {URL}  batch={BATCH_SIZE}  rounds={ROUNDS}")
    headers = {"X-Service-Token": TOKEN}
    async with httpx.AsyncClient(base_url=URL, headers=headers, timeout=60.0) as client:
        # Check readiness
        r = await client.get("/ready")
        if r.status_code != 200:
            print(f"Service not ready: {r.status_code} {r.text}")
            return

        await _bench_endpoint(client, "/classify", ROUNDS, BATCH_SIZE)
        await _bench_endpoint(client, "/embed", ROUNDS, BATCH_SIZE)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
