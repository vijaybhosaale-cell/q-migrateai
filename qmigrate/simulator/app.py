"""Cloud simulator service (port 8001): synthetic multi-cloud crypto estates.

    uvicorn qmigrate.simulator.app:app --port 8001

GET /estate?profile=bank&seed=42&n=400&drift=0 returns {"assets": [...], "edges": [...]}.
All data is synthetic; no real organisation, system or person is modelled.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException, Query

from qmigrate.simulator.generator import PROFILES, generate

app = FastAPI(title="Q-MigrateAI Cloud Simulator", version="2.0.0",
              description="Synthetic AWS / Azure / GCP cryptographic inventories for demos. All data is synthetic.")


@lru_cache(maxsize=32)
def _estate(profile: str, seed: int, n: int, drift: int) -> dict:
    return generate(seed, n, profile, drift)


@app.get("/health")
def health() -> dict:
    return {"service": "simulator", "status": "ok", "profiles": list(PROFILES)}


@app.get("/estate")
def estate(profile: str = "generic", seed: int = Query(42, ge=0, le=10**6), n: int = Query(400, ge=40, le=2000),
           drift: int = Query(0, ge=0, le=50)) -> dict:
    if profile not in PROFILES:
        raise HTTPException(400, f"Unknown profile. Use one of: {', '.join(PROFILES)}")
    return _estate(profile, seed, n, drift)
