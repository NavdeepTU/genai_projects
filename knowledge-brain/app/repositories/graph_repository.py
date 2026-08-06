import logging

from neo4j import AsyncSession

from app.core.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

circuit_breaker = CircuitBreaker(name="neo4j")


class GraphRepository:
    """All direct access to the document relationship graph lives here.

    Mirrors DocumentRepository's role for Postgres: other code asks this
    repository for graph data instead of writing Cypher queries itself.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_reference(self, source_document_id: str, target_document_id: str) -> None:
        """Record that one document explicitly references another.

        MERGE (not CREATE) throughout: running this twice for the same
        pair is safe and doesn't create duplicate nodes or edges.
        """
        query = """
        MERGE (source:Document {id: $source_id})
        MERGE (target:Document {id: $target_id})
        MERGE (source)-[:REFERENCES]->(target)
        """

        async def run_query() -> None:
            await self.session.run(query, source_id=source_document_id, target_id=target_document_id)

        await circuit_breaker.call(run_query)

    async def get_referenced_documents(self, document_id: str) -> list[str]:
        """Return the IDs of documents this document directly references.

        One hop only, by design: (this document) -> REFERENCES -> (another
        document), not references-of-references.
        """
        query = """
        MATCH (d:Document {id: $document_id})-[:REFERENCES]->(target:Document)
        RETURN target.id AS id
        """

        async def run_query() -> list[str]:
            result = await self.session.run(query, document_id=document_id)
            records = [record async for record in result]
            return [record["id"] for record in records]

        return await circuit_breaker.call(run_query)
