def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split text into overlapping, word-based chunks.

    We split on whitespace-separated words, not raw characters, so we
    never cut a word in half. Each chunk repeats the last
    `chunk_overlap` words from the previous one, so an idea that spans
    a chunk boundary still appears whole in at least one chunk.
    """
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = end - chunk_overlap

    return chunks
