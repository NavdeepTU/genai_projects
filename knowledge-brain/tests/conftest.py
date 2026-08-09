from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.database import Base
from app.models import audit_log, document, document_permission  # noqa: F401  (import registers the tables with Base)

settings = get_settings()

# Same host, port, and credentials as the real dev database — just a
# different database name, so tests never touch real data.
TEST_DATABASE_URL = settings.database_url.rsplit("/", 1)[0] + "/knowledge_brain_test"

# NullPool: open a fresh connection for every use instead of reusing a
# pooled one. Each test function gets its own event loop from
# pytest-asyncio, but a pooled connection stays tied to whichever loop
# opened it — reusing it under a different test's loop is what
# actually causes the failure below. No pooling means no stale
# connection can ever cross that boundary.
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
async def create_test_tables() -> AsyncGenerator[None, None]:
    """Create every table once before any test runs, drop them all when the run ends."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Give one test a real database session, then wipe every table clean.

    Tests call repository/service code that commits on its own, so a
    plain rollback wouldn't undo anything — the data is already
    persisted. Deleting every row after the test runs is what actually
    guarantees the next test starts from empty tables.
    """
    async with TestSessionLocal() as session:
        yield session

    async with TestSessionLocal() as cleanup_session:
        for table in reversed(Base.metadata.sorted_tables):
            await cleanup_session.execute(table.delete())
        await cleanup_session.commit()
