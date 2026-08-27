from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.middleware import get_correlation_id, get_current_user_id
from app.models.analytics import AnalyticsResponse
from app.repositories.audit_repository import AuditRepository
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("", response_model=AnalyticsResponse)
async def get_analytics(db: AsyncSession = Depends(get_db)) -> AnalyticsResponse:
    """Return this user's 30-day query trends — volume, top questions, average latency."""
    user_id = get_current_user_id()
    service = AnalyticsService(AuditRepository(db))
    return await service.get_analytics(user_id, get_correlation_id())
