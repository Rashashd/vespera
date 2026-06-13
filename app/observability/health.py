"""Public shallow liveness endpoint for the hosting platform's probe."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Return a bare liveness status (no auth, no dependency checks, no detail)."""
    return {"status": "ok"}
