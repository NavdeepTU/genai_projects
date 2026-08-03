import io

from pypdf import PdfReader


def extract_text(filename: str, content: bytes) -> str:
    """Pull plain text out of an uploaded file's raw bytes.

    We branch on the file extension because a PDF's bytes are a binary
    format (fonts, layout, images) that needs a real parser, while a
    .txt file's bytes already are the text we want.
    """
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if filename.lower().endswith(".txt"):
        return content.decode("utf-8")

    raise ValueError(f"Unsupported file type: {filename}")
