import uuid

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.middleware import get_current_user_id
from app.repositories.user_repository import UserRepository


async def is_admin_user(db: AsyncSession) -> bool:
    """Return whether the current caller is a real admin, without raising.

    The plain check `require_admin` (below) wraps into a hard 403 — used
    directly wherever admin-ness is just one branch of a broader decision
    rather than the whole gate (e.g. the PII review workflow's ADR-048:
    a document held for review is visible to its own uploader *or* an
    admin, not exclusively one or the other).
    """
    user = await UserRepository(db).get_user_by_id(uuid.UUID(get_current_user_id()))
    return user is not None and user.is_admin


async def require_admin(db: AsyncSession = Depends(get_db)) -> None:
    """FastAPI dependency: reject any request whose caller isn't a real admin.

    Checks the User.is_admin column now that a real account backs every
    caller — the natural completion of what ADR-034 called "a small
    slice of real auth, pulled forward" when it started as an
    ADMIN_USER_IDS env-var allowlist, before real accounts existed at
    all. Every other page here scopes data to the caller's own — this
    is the one place that reads across every user, so it's the one
    place that needs its own lock.
    """
    if not await is_admin_user(db):
        raise HTTPException(status_code=403, detail="Admin access required")
