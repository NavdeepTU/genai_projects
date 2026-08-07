import asyncio
import json
import uuid
from pathlib import Path

from app.core.database import AsyncSessionLocal
from app.core.graph_database import driver
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.services.ingestion_service import IngestionService
from app.services.retrieval_service import RetrievalService
from eval.judge import judge_correctness, judge_faithfulness

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DATASET_PATH = Path(__file__).parent / "dataset.json"


async def ensure_fixtures_ingested(repository: DocumentRepository) -> dict[str, uuid.UUID]:
    """Make sure every fixture document exists, ingesting any that don't yet.

    Returns a mapping from filename to its document ID, so each test case
    can check whether the *correct* document was actually retrieved.
    """
    ingestion = IngestionService(repository)
    filename_to_document_id: dict[str, uuid.UUID] = {}

    for fixture_path in sorted(FIXTURES_DIR.glob("*.txt")):
        existing = await repository.get_document_by_filename(fixture_path.name)
        if existing is not None:
            filename_to_document_id[fixture_path.name] = existing.id
            continue

        content = fixture_path.read_bytes()
        document = await ingestion.ingest_document(fixture_path.name, content)
        filename_to_document_id[fixture_path.name] = document.id

    return filename_to_document_id


async def run_one_case(
    service: RetrievalService, case: dict, filename_to_document_id: dict[str, uuid.UUID]
) -> dict:
    """Run one test case through the real pipeline and score all three dimensions."""
    state = await service.run_query(case["question"])

    expected_document_id = filename_to_document_id[case["source_fixture"]]
    retrieval_ok = any(
        chunk.document_id == expected_document_id for chunk in state["reranked_chunks"]
    )

    context_chunks = [chunk.text for chunk in state["reranked_chunks"]] + state["graph_context"]
    faithful = await judge_faithfulness(state["answer"], context_chunks)
    correct = await judge_correctness(case["question"], state["answer"], case["reference_answer"])

    return {
        "id": case["id"],
        "retrieval_ok": retrieval_ok,
        "faithful": faithful,
        "correct": correct,
        "answer": state["answer"],
    }


async def main() -> None:
    dataset = json.loads(DATASET_PATH.read_text())

    async with AsyncSessionLocal() as db_session:
        filename_to_document_id = await ensure_fixtures_ingested(DocumentRepository(db_session))

    results = []
    async with AsyncSessionLocal() as db_session, driver.session() as graph_session:
        service = RetrievalService(DocumentRepository(db_session), GraphRepository(graph_session))
        for i, case in enumerate(dataset):
            if i > 0:
                # Voyage's free tier caps unpaid accounts at 3 requests/minute;
                # each case makes a rerank call, so pace them to stay under it.
                await asyncio.sleep(20)
            result = await run_one_case(service, case, filename_to_document_id)
            results.append(result)
            print(
                f"[{result['id']}] retrieval={result['retrieval_ok']} "
                f"faithful={result['faithful']} correct={result['correct']}"
            )

    total = len(results)
    print(f"\nRetrieval:    {sum(r['retrieval_ok'] for r in results)}/{total}")
    print(f"Faithfulness: {sum(r['faithful'] for r in results)}/{total}")
    print(f"Correctness:  {sum(r['correct'] for r in results)}/{total}")

    await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
