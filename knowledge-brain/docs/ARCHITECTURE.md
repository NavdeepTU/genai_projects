# Knowledge Brain — Architecture Guide

## What this system does

Knowledge Brain lets a company upload its internal documents and then ask
questions about them in plain English. Think of it like a private search
engine that gives you answers instead of a list of links.

## The big picture — how the pieces fit together

Two things exist now: getting a document *into* the system, and asking a
question *about* it. Nothing beyond plain vector search exists yet — no
hybrid search, no reranking, no multi-step reasoning. That comes later.

**Getting a document in:** a user uploads a file → the API receives it →
the file's raw text is pulled out → that text is cut into small
overlapping pieces → each piece is turned into a list of numbers that
represents its meaning → those pieces and their numbers are saved in the
database. If anything goes wrong along the way, the document is marked as
failed rather than left in limbo.

**Asking a question:** a user sends a question → it's turned into a
meaning-vector using the same process as the chunks → the database finds
the handful of stored chunks whose vectors are closest in meaning → those
chunks, plus the original question, are handed to an LLM → the LLM answers
using only that retrieved text, and says it doesn't know rather than
guessing if the answer isn't there.

## The main components

**API route (`app/api/documents.py`)** — the "front door." Accepts an
uploaded file over the network, rejects unsupported file types immediately,
and hands the file off to the ingestion service. Talks to: the ingestion
service. If it disappeared, there'd be no way to get a file into the system
at all.

**Ingestion service (`app/services/ingestion_service.py`)** — the
conductor. Knows the *order* the pipeline steps must run in (extract, then
chunk, then embed, then save), and marks the document ready or failed at
the end. Talks to: extraction, chunking, embedding, and the repository. If
it disappeared, each individual step would still work, but nothing would
tie them together.

**Extraction (`app/services/extraction.py`)** — pulls plain text out of a
file's raw bytes. Different file types (PDF vs plain text) need different
extraction logic, since a PDF's bytes contain layout and font information
mixed in with the actual words.

**Chunking (`app/services/chunking.py`)** — cuts a long piece of text into
smaller, overlapping pieces. Necessary because embedding models work on
short passages, and because search works better on small, focused pieces
than on one giant block of text.

**Embedding (`app/services/embedding.py`)** — calls an external AI model
(OpenAI) that turns each chunk of text into a list of numbers representing
its meaning. This is what will eventually let us search "by meaning"
instead of just by exact keyword.

**Repository (`app/repositories/document_repository.py`)** — the only
place in the codebase that talks directly to the database. Everything else
asks the repository to save or update things, rather than writing its own
database queries.

**Retrieval service (`app/services/retrieval_service.py`)** — the
conductor for answering questions, mirroring the ingestion service's role.
Embeds the question, asks the repository for the closest chunks, then asks
the generation service to write an answer. Talks to: embedding, the
repository, and generation.

**Generation (`app/services/generation.py`)** — sends the question and the
retrieved chunks to an LLM, with instructions to answer only from that
text and admit uncertainty rather than guess. This is the piece that
actually turns "relevant text" into a readable answer.

**Database (Postgres + pgvector, running in Docker)** — stores documents
and their chunks, including each chunk's meaning-vector, in one place, and
now also answers "which chunks are closest in meaning to this vector?"
using pgvector's cosine similarity search.

## Key decisions we made and why

We run the pipeline synchronously (the user waits while their file is
processed) rather than using a background queue like Kafka, deliberately
starting simple and adding a queue later once we feel the pain of long
processing times. See ADR-001.

We chose Postgres + pgvector over a dedicated vector database (Qdrant) to
start, since it keeps document metadata and search vectors in one place
with one connection, and Qdrant is planned for later once we need
specialized, large-scale vector search. See ADR-002.

We run Postgres in Docker rather than installing it directly on the
developer's machine, to avoid it colliding with other software already
installed locally, and so the exact same setup works on any machine. See
ADR-003.

We instruct the answer-generation model explicitly to say it doesn't know
rather than guess, because an LLM's default tendency is to always produce
a confident-sounding answer — without that instruction, missing or
irrelevant retrieved context would likely lead to a made-up answer instead
of an honest "not found." See ADR-004.

## How data moves through the system

**Uploading a document:** a user sends a file to the upload address. The
system checks the file type is supported, creates a database record for
the document immediately (marked "pending"), then extracts its text,
splits that text into chunks, turns each chunk into a meaning-vector, and
saves everything to the database. If every step succeeds, the document is
marked "ready." If any step fails, the document is marked "failed" instead
of being left stuck partway through.

**Asking a question:** a user sends a question to the query address. The
question is turned into a meaning-vector using the same embedding model
used for chunks, so the two are comparable. Postgres finds the handful of
chunks whose vectors are closest to the question's vector, using cosine
similarity (a way of measuring how similar two vectors' meaning is,
regardless of text length). Those chunks and the question are sent to an
LLM, which writes an answer grounded only in that retrieved text.

## What could go wrong and how we handle it

**A scanned PDF with no real text** — some PDF pages are just a photograph
of a page, with no actual character data underneath. Extracting text from
a page like that returns nothing, so that page contributes no searchable
content. Not handled yet — a future improvement would add OCR (a
technology that reads text out of images) to cover this case.

**An embedding call fails partway through a large document** — because all
of a document's chunks are sent to the embedding model in a single batch
request, a failure there means none of that document's chunks get saved,
not a partial set. The whole document is marked "failed," and it would
need to be re-uploaded and reprocessed from scratch.

**No documents have been uploaded yet, or nothing relevant matches** — the
similarity search still returns *something* (it always returns the
closest chunks it can find, even if none are truly relevant), but the
generation step's instructions mean the LLM says it doesn't know rather
than forcing an answer out of unrelated context.

## Glossary

**Chunk** — a small piece of a larger document's text.

**Embedding / vector** — a list of numbers produced by an AI model that
represents what a piece of text means, used so similar meanings can be
found by comparing numbers instead of comparing exact words.

**pgvector** — an add-on to Postgres that lets it store and search
embedding vectors alongside normal data.

**Cosine similarity** — a way of comparing two vectors by the angle
between them, used to measure how similar in meaning two pieces of text
are, regardless of how long either one is.

**Retrieval-Augmented Generation (RAG)** — the pattern of finding relevant
text first, then handing it to an LLM to write an answer from, instead of
asking the LLM to answer purely from what it already knows.

**Hallucination** — when an LLM confidently states something false or
made-up, typically because it lacks real information and defaults to
guessing rather than admitting uncertainty.

**Repository** — the part of the code responsible only for reading and
writing to the database, with no business logic in it.

**Service** — the part of the code responsible for business logic — the
actual sequence of steps a feature performs.
