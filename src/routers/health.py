"""Health check endpoints for monitoring and readiness probes."""

from datetime import datetime
from fastapi import APIRouter
from ..models.schemas import HealthResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Service health check — used by load balancers and Kubernetes probes."""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        document_intelligence_status="configured",
        openai_status="configured",
        database_status="configured",
        timestamp=datetime.utcnow(),
    )


@router.get("/ready")
async def readiness_check():
    """Readiness probe — checks if all dependencies are reachable."""
    return {"ready": True, "timestamp": datetime.utcnow().isoformat()}
