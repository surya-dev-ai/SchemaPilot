"""Versioned API router."""

from fastapi import APIRouter

from app.api.artifacts import router as artifacts_router
from app.api.health import router as health_router
from app.api.plans import router as plans_router
from app.api.risk import router as risk_router
from app.api.safety import router as safety_router
from app.api.sandbox import router as sandbox_router
from app.api.sources import router as sources_router
from app.api.workflows import router as workflows_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(sources_router)
api_router.include_router(plans_router)
api_router.include_router(risk_router)
api_router.include_router(artifacts_router)
api_router.include_router(sandbox_router)
api_router.include_router(safety_router)
api_router.include_router(workflows_router)
