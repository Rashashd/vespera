"""Authentication routes: custom rate-limited, audited login and stateless logout (spec 2).

Also includes self-service PATCH /auth/users/me for password change (FR-024).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import SYSTEM_ACTOR_ID
from app.auth.backend import current_active_user, get_jwt_strategy, password_helper
from app.auth.models import User
from app.auth.rate_limit import LOGIN_RATE_LIMIT, login_limiter
from app.core.dependencies import get_session
from app.domain.events import LoginFailed, UserLoggedIn

router = APIRouter(prefix="/auth/jwt", tags=["auth"])
_users_me_router = APIRouter(prefix="/auth/users", tags=["auth"])

# Generic, non-enumerating failure detail (FR-002): identical whether the email exists or not.
_BAD_CREDENTIALS = "LOGIN_BAD_CREDENTIALS"


@router.post("/login")
@login_limiter.limit(LOGIN_RATE_LIMIT)
async def login(
    request: Request,
    response: Response,
    credentials: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
    strategy=Depends(get_jwt_strategy),
) -> Response:
    """Authenticate (email+password) and return a bearer token; audit success and failure."""
    dispatcher = request.app.state.dispatcher
    email = credentials.username.strip().lower()
    user = await session.scalar(select(User).where(func.lower(User.email) == email))

    verified = False
    if user is not None:
        verified, _ = password_helper.verify_and_update(credentials.password, user.hashed_password)

    if user is None or not verified or not user.is_active:
        # Returning (not raising) a 400 lets the failed-login audit row commit (FR-012).
        if user is None:
            await dispatcher.dispatch(
                LoginFailed(
                    actor_id=SYSTEM_ACTOR_ID,
                    actor_type="system",
                    email=email,
                    reason="unknown_user",
                ),
                session,
            )
        else:
            await dispatcher.dispatch(
                LoginFailed(
                    actor_id=user.id,
                    actor_type="human",
                    client_id=user.client_id,
                    email=email,
                    reason="inactive" if verified else "bad_password",
                ),
                session,
            )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST, content={"detail": _BAD_CREDENTIALS}
        )

    token = await strategy.write_token(user)
    await dispatcher.dispatch(
        UserLoggedIn(
            actor_id=user.id,
            actor_type="human",
            client_id=user.client_id,
            user_id=user.id,
            email=email,
        ),
        session,
    )
    return JSONResponse(content={"access_token": token, "token_type": "bearer"})


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(_user: User = Depends(current_active_user)) -> Response:
    """Stateless logout: nothing to revoke server-side; the client discards the token."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Self-service password change (FR-024): PATCH /auth/users/me
# ---------------------------------------------------------------------------


class _PasswordUpdate(BaseModel):
    password: str


class _MeResponse(BaseModel):
    """Current-user identity the SPA needs to route by role (spec 10)."""

    id: int
    email: str
    role: str | None
    user_type: str
    client_id: int | None
    is_active: bool


@_users_me_router.get("/me", response_model=_MeResponse)
async def get_me(user: User = Depends(current_active_user)) -> _MeResponse:
    """Return the authenticated user's identity (drives SPA role routing, FR-002)."""
    return _MeResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        user_type=user.user_type,
        client_id=user.client_id,
        is_active=user.is_active,
    )


@_users_me_router.patch("/me", status_code=status.HTTP_200_OK)
async def update_me(
    body: _PasswordUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Allow any authenticated user to change their own password (FR-024)."""
    from app.auth.manager import validate_password_policy

    try:
        validate_password_policy(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    user.hashed_password = password_helper.hash(body.password)
    session.add(user)
    await session.commit()
    return {"id": user.id, "email": user.email}
