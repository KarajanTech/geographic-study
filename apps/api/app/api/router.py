"""API v1 router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import datasets, health, projects

API_V1_PREFIX = "/api/v1"

api_router = APIRouter(prefix=API_V1_PREFIX)
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(datasets.router)
