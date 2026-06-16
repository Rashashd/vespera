"""Service-credential authentication dependency (X-Service-Token header).

Missing token → 401; present-but-wrong → 403. Constant-time compare prevents timing attacks.
"""

import hmac
from typing import Annotated

from fastapi import Header, HTTPException, Request


async def require_service_token(
    request: Request,
    x_service_token: Annotated[str | None, Header(alias="X-Service-Token")] = None,
) -> None:
    """FastAPI dependency: validate the X-Service-Token against the loaded credential."""
    if x_service_token is None:
        raise HTTPException(status_code=401, detail="X-Service-Token required")

    expected: str | None = getattr(request.app.state, "service_token", None)
    if expected is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    if not hmac.compare_digest(x_service_token.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Invalid service token")
