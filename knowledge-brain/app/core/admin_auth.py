from fastapi import HTTPException

from app.core.config import get_settings
from app.core.middleware import get_current_user_id


def require_admin() -> None:
    """FastAPI dependency: reject any request whose caller isn't a configured admin.

    A minimal, explicit allowlist — not real RBAC — pulling forward a
    small slice of real auth (build-order item 14) rather than building
    it in full or leaving admin routes open, the same proportionate
    trade-off this project already made for MCP's shared secret
    (ADR-017). Every other page here scopes data to the caller's own —
    this is the one place that reads across every user, so it's the
    one place that needs its own lock.
    """
    settings = get_settings()
    admin_ids = {uid.strip() for uid in settings.admin_user_ids.split(",") if uid.strip()}

    if get_current_user_id() not in admin_ids:
        raise HTTPException(status_code=403, detail="Admin access required")
