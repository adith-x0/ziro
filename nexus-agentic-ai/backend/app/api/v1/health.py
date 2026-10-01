from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/health", tags=["Health & Status"])


@router.get("", summary="General Service Health")
async def health_check() -> dict[str, Any]:
    """Returns general health status of the NEXUS backend."""
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.service_version,
        "environment": settings.environment,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/ready", summary="Readiness Probe")
async def readiness_check() -> dict[str, Any]:
    """Readiness probe checking readiness for traffic."""
    # In scaffolding mode, returns ready with service configuration
    return {
        "status": "ready",
        "service": settings.service_name,
        "version": settings.service_version,
        "components": {
            "orchestrator": "initialized",
            "safety_gate": "active" if settings.safety_gate_strict_mode else "advisory",
            "database_configured": bool(settings.database_url),
            "redis_configured": bool(settings.redis_url),
            "llm_configured": bool(settings.gemini_api_key),
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/live", summary="Liveness Probe")
async def liveness_check() -> dict[str, Any]:
    """Liveness probe verifying event loop responsiveness."""
    return {
        "status": "alive",
        "service": settings.service_name,
        "timestamp": datetime.now(UTC).isoformat(),
    }
