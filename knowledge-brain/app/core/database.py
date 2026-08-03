from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Parent class for every database table model in this app.

    SQLAlchemy uses this to know which Python classes represent
    database tables, and to collect them all in one place so we can
    create every table with a single command.
    """


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Give one request a database session, and clean it up afterward.

    FastAPI calls this for any route that declares it as a dependency.
    We roll back on error so a failed request never leaves half-written
    changes sitting uncommitted in the session.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
