import logging

from azure.ai.textanalytics import PiiEntityCategory
from azure.ai.textanalytics.aio import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
client = TextAnalyticsClient(
    endpoint=settings.azure_language_endpoint,
    credential=AzureKeyCredential(settings.azure_language_key),
)
circuit_breaker = CircuitBreaker(name="azure_pii_detection")

# Azure's own hard cap on documents per PII-detection request — not ours to
# tune, unlike pii_max_chars_per_document, which is our own safety margin
# below Azure's 5,120-character-per-document limit.
MAX_DOCUMENTS_PER_REQUEST = 5

# An explicit allowlist, not Azure's full 173-category default set. Chosen
# after live testing showed Azure's PersonType category — not even in this
# filterable list — flags generic role words like "employee" or "customer"
# as PII on its own. Passing a specific list means only these categories
# ever come back, so PersonType (and every unrelated country's ID formats)
# is excluded by omission, not by trying to name it directly.
PII_CATEGORIES = [
    # Direct identity
    PiiEntityCategory.PERSON,
    PiiEntityCategory.PHONE_NUMBER,
    PiiEntityCategory.EMAIL,
    PiiEntityCategory.ADDRESS,
    PiiEntityCategory.AGE,
    # Financial
    PiiEntityCategory.CREDIT_CARD_NUMBER,
    PiiEntityCategory.US_BANK_ACCOUNT_NUMBER,
    PiiEntityCategory.INTERNATIONAL_BANKING_ACCOUNT_NUMBER,
    # US government IDs
    PiiEntityCategory.US_SOCIAL_SECURITY_NUMBER,
    PiiEntityCategory.US_INDIVIDUAL_TAXPAYER_IDENTIFICATION,
    PiiEntityCategory.US_DRIVERS_LICENSE_NUMBER,
    PiiEntityCategory.USUK_PASSPORT_NUMBER,
    # India government IDs
    PiiEntityCategory.IN_PERMANENT_ACCOUNT,
    PiiEntityCategory.IN_UNIQUE_IDENTIFICATION_NUMBER,
]


def _split_into_documents(text: str) -> list[str]:
    """Split text into pieces under Azure's per-document character limit.

    Splits on paragraph breaks, not a hard character cut — cutting
    mid-paragraph risks severing a name or address exactly the way
    sending the whole document as one piece was meant to avoid. Falls
    back to a hard cut only for a single paragraph longer than the
    limit on its own.
    """
    limit = settings.pii_max_chars_per_document
    paragraphs = text.split("\n\n")
    pieces: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph

        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            pieces.append(current)
            current = ""

        if len(paragraph) <= limit:
            current = paragraph
        else:
            for i in range(0, len(paragraph), limit):
                pieces.append(paragraph[i : i + limit])

    if current:
        pieces.append(current)

    return pieces


async def detect_pii(text: str) -> list[str]:
    """Return the categories of personal information Azure found in text, empty if none.

    Splits long text into pieces under Azure's per-document character
    limit, sends them in batches of up to 5 (Azure's own cap per
    request), and combines the categories found across every piece.
    """
    documents = _split_into_documents(text)
    categories: set[str] = set()

    for batch_start in range(0, len(documents), MAX_DOCUMENTS_PER_REQUEST):
        batch = documents[batch_start : batch_start + MAX_DOCUMENTS_PER_REQUEST]

        try:
            results = await circuit_breaker.call(
                lambda: client.recognize_pii_entities(batch, categories_filter=PII_CATEGORIES)
            )
        except HttpResponseError:
            logger.exception("PII detection call failed")
            raise

        for result in results:
            if result.is_error:
                raise RuntimeError(f"Azure PII detection returned an error: {result.error}")
            categories.update(entity.category for entity in result.entities)

    return list(categories)
