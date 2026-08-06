from collections.abc import AsyncGenerator

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from app.core.config import get_settings

settings = get_settings()

driver: AsyncDriver = AsyncGraphDatabase.driver(
    settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
)


async def get_graph_session() -> AsyncGenerator[AsyncSession, None]:
    """Give one request a Neo4j session, and close it when the request ends.

    Mirrors get_db() in database.py: FastAPI calls this for any route
    that declares it as a dependency, and the session is scoped to
    exactly one request, not shared across requests.
    """
    async with driver.session() as session:
        yield session
