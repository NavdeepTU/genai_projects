import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.middleware import SESSION_COOKIE_NAME, get_correlation_id, get_current_user_id
from app.models.session import SESSION_LIFETIME
from app.models.user import LoginRequest, SignupRequest, UserResponse
from app.repositories.audit_repository import AuditRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import (
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    TenantNotFoundError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    """Attach the session cookie to a response.

    secure is off only in dev — a browser silently refuses to send a
    secure cookie back over plain http, which is exactly how the app
    runs locally. In staging/prod, traffic is https end to end, so the
    cookie is marked secure there.
    """
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.environment != "dev",
        samesite="lax",
        max_age=int(SESSION_LIFETIME.total_seconds()),
    )


@router.post("/signup", response_model=UserResponse, status_code=201)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)) -> UserResponse:
    """Create a new account in an already-registered tenant (ADR-046).

    Does not log the caller in — sign up, then log in separately.
    """
    correlation_id = get_correlation_id()
    auth_service = AuthService(UserRepository(db), SessionRepository(db), TenantRepository(db))

    try:
        user = await auth_service.sign_up(body.email, body.password, body.tenant_id)
    except EmailAlreadyRegisteredError:
        raise HTTPException(status_code=409, detail="An account with this email already exists") from None
    except TenantNotFoundError:
        raise HTTPException(status_code=400, detail="That tenant no longer exists. Please refresh and pick again.") from None

    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="user_signup",
        resource_type="user",
        resource_id=str(user.id),
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
    )

    return UserResponse(
        id=user.id, email=user.email, tenant_id=user.tenant_id, is_admin=user.is_admin, correlation_id=correlation_id
    )


@router.post("/login", response_model=UserResponse)
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)) -> UserResponse:
    """Verify credentials and start a new session, set as an httponly cookie."""
    correlation_id = get_correlation_id()
    auth_service = AuthService(UserRepository(db), SessionRepository(db), TenantRepository(db))

    try:
        user, session = await auth_service.log_in(body.email, body.password)
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="Incorrect email or password") from None

    _set_session_cookie(response, session.token)

    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="user_login",
        resource_type="user",
        resource_id=str(user.id),
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
    )

    return UserResponse(
        id=user.id, email=user.email, tenant_id=user.tenant_id, is_admin=user.is_admin, correlation_id=correlation_id
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> None:
    """End the current session and clear the cookie."""
    user_id = get_current_user_id()
    token = request.cookies.get(SESSION_COOKIE_NAME, "")

    await AuthService(UserRepository(db), SessionRepository(db), TenantRepository(db)).log_out(token)
    response.delete_cookie(key=SESSION_COOKIE_NAME)

    await AuditRepository(db).log_action(
        correlation_id=get_correlation_id(),
        action="user_logout",
        resource_type="user",
        resource_id=user_id,
        user_id=user_id,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(db: AsyncSession = Depends(get_db)) -> UserResponse:
    """Return the currently logged-in user's own account info."""
    user = await UserRepository(db).get_user_by_id(uuid.UUID(get_current_user_id()))
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    return UserResponse(
        id=user.id,
        email=user.email,
        tenant_id=user.tenant_id,
        is_admin=user.is_admin,
        correlation_id=get_correlation_id(),
    )
