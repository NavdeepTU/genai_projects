import asyncio
import json
import uuid
from pathlib import Path

from app.core.database import AsyncSessionLocal
from app.core.graph_database import driver
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.repositories.tenant_repository import TenantRepository
from app.services.ingestion_service import IngestionService
from app.services.retrieval_service import RetrievalService
from eval.judge import judge_correctness, judge_faithfulness

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DATASET_PATH = Path(__file__).parent / "dataset.json"

# A fixed identity for the eval harness's own fixture documents — not a real
# person, but every query is tagged with who asked for tracing purposes.
EVAL_USER_ID = "eval-harness"

# A dedicated tenant for the eval harness's fixture documents (ADR-046) —
# registered once, reused on every run, kept separate from any real tenant
# so eval fixtures never mix into a real user's document pool.
EVAL_TENANT_NAME = "Eval Harness"


async def ensure_eval_tenant(tenant_repository: TenantRepository) -> uuid.UUID:
    """Return the eval harness's own tenant id, registering it on the first run."""
    existing = await tenant_repository.get_tenant_by_name(EVAL_TENANT_NAME)
    if existing is not None:
        return existing.id

    tenant = await tenant_repository.create_tenant(EVAL_TENANT_NAME)
    return tenant.id


async def ensure_fixtures_ingested(
    repository: DocumentRepository, tenant_id: uuid.UUID
) -> dict[str, uuid.UUID]:
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
        document = await ingestion.create_document(fixture_path.name, content, tenant_id)
        await ingestion.process_document(document.id, fixture_path.name, content)
        filename_to_document_id[fixture_path.name] = document.id

    return filename_to_document_id


async def run_one_case(
    service: RetrievalService,
    case: dict,
    filename_to_document_id: dict[str, uuid.UUID],
    tenant_id: uuid.UUID,
) -> dict:
    """Run one test case through the real pipeline and score all three dimensions."""
    state = await service.run_query(case["question"], EVAL_USER_ID, str(tenant_id))

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
        tenant_id = await ensure_eval_tenant(TenantRepository(db_session))
        filename_to_document_id = await ensure_fixtures_ingested(
            DocumentRepository(db_session), tenant_id
        )

    results = []
    async with AsyncSessionLocal() as db_session, driver.session() as graph_session:
        service = RetrievalService(DocumentRepository(db_session), GraphRepository(graph_session))
        for i, case in enumerate(dataset):
            if i > 0:
                # Voyage's free tier caps unpaid accounts at 3 requests/minute;
                # each case makes a rerank call, so pace them to stay under it.
                await asyncio.sleep(20)
            result = await run_one_case(service, case, filename_to_document_id, tenant_id)
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
