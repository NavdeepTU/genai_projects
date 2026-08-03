from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.document import DocumentUploadResponse
from app.repositories.document_repository import DocumentRepository
from app.services.ingestion_service import IngestionService

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = (".pdf", ".txt")


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Accept one uploaded file and run it through the ingestion pipeline."""
    if not file.filename or not file.filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Only .pdf and .txt files are supported")

    content = await file.read()
    service = IngestionService(DocumentRepository(db))
    return await service.ingest_document(file.filename, content)
