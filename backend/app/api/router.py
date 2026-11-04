"""Versioned API router."""

from fastapi import APIRouter, Depends

from app.api.artifacts import router as artifacts_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.plans import router as plans_router
from app.api.risk import router as risk_router
from app.api.safety import router as safety_router
from app.api.sandbox import router as sandbox_router
from app.api.sources import router as sources_router
from app.api.workflows import router as workflows_router
from app.services.auth import require_api_principal, require_engineer

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(health_router)
protected = [Depends(require_api_principal)]
engineer = [Depends(require_engineer)]
api_router.include_router(sources_router, dependencies=protected)
api_router.include_router(plans_router, dependencies=[*protected, *engineer])
api_router.include_router(risk_router, dependencies=[*protected, *engineer])
api_router.include_router(artifacts_router, dependencies=[*protected, *engineer])
api_router.include_router(sandbox_router, dependencies=[*protected, *engineer])
api_router.include_router(safety_router, dependencies=[*protected, *engineer])
api_router.include_router(workflows_router, dependencies=protected)
