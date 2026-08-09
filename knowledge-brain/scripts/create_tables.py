import asyncio

from app.core.database import Base, engine
from app.models import audit_log, document, document_permission  # noqa: F401  (import registers the tables with Base)


async def main() -> None:
    """Create every table defined by our models, if it doesn't already exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created.")


if __name__ == "__main__":
    asyncio.run(main())
