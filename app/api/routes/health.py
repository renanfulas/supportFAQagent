from fastapi import APIRouter, Depends, Request, Response, status

from app.health.service import HealthService
from app.core.security import verify_api_key


router = APIRouter(tags=["health"])


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(
    request: Request,
    response: Response,
    _: str = Depends(verify_api_key),
) -> dict[str, object]:
    snapshot = HealthService(request.app.state.database_runtime).readiness()
    if snapshot["status"] == "unavailable":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return snapshot
