import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Ensure project root is in sys.path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from app.api.mvp_endpoints import router as mvp_router
from app.api.v1.health import router as health_router
from app.api.v1.incidents import router as incidents_router
from app.config import settings
from app.logging import logger


def create_app() -> FastAPI:
    """FastAPI Application Factory for NEXUS."""
    app = FastAPI(
        title="NEXUS Autonomous Operations Network",
        description="Backend API for Multimodal, Multi-Agent Emergency Operations and Simulation.",
        version=settings.service_version,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Cross-Origin Resource Sharing (CORS) Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request Logging & Latency Middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"
        response = await call_next(request)
        process_time_ms = (time.time() - start_time) * 1000.0
        logger.info(
            f"HTTP {request.method} {request.url.path} - "
            f"Status: {response.status_code} - "
            f"Latency: {process_time_ms:.2f}ms - IP: {client_ip}"
        )
        response.headers["X-Process-Time-Ms"] = f"{process_time_ms:.2f}"
        return response

    # Global Exception Handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            f"Unhandled exception processing {request.url.path}: {str(exc)}", exc_info=True
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "InternalServerError",
                "message": "An unexpected error occurred while processing the request.",
                "path": request.url.path,
            },
        )

    # Route Registrations
    app.include_router(health_router)
    app.include_router(incidents_router, prefix="/api/v1")
    app.include_router(mvp_router, prefix="/api")

    @app.get("/", summary="Root Welcome")
    async def root() -> dict[str, Any]:
        return {
            "message": "NEXUS Autonomous Real-World Response & Operations Network API",
            "version": settings.service_version,
            "status": "online",
            "documentation": "/docs",
        }

    return app


app = create_app()
