# Knowledge Brain — Interview Prep

A study sheet, not a spec. Read this before an interview to refresh why we
built things the way we did. Answers are written in plain language — the
goal is to say them back naturally, in your own words, not recite them.

---

## Feature 1: Document Ingestion Pipeline

**What does this feature do, in one sentence?**
It takes an uploaded file, pulls the text out of it, cuts that text into
small pieces, turns each piece into a list of numbers representing its
meaning, and saves everything to the database.

**Why did we process the file synchronously (the user waits) instead of
using a background queue like Kafka?**
Because it's simpler to build and reason about right now, and our
documents process in under a second. Kafka adds real complexity — a
separate worker process, a message broker, and handling "the upload
succeeded but processing is still happening elsewhere." We're deliberately
waiting to add that complexity until we actually feel the problem it
solves — specifically, once a large document makes someone wait 30+
seconds staring at a spinner.

**Why Postgres + pgvector instead of a dedicated vector database like
Qdrant?**
Because it keeps everything — a document's normal info (filename, status)
and its chunks' embedding vectors — in one database, one connection, one
query language. Saving a document and its chunks can happen as a single
all-or-nothing operation, which is harder to guarantee across two separate
databases. Qdrant is faster at large-scale vector search, but we're adding
it later, once pgvector's performance actually becomes a bottleneck.

**Why do we run Postgres in Docker instead of installing it directly on
the machine?**
A native install becomes part of the machine and can silently conflict
with other software — we actually hit this during setup, where a native
Postgres already on the machine intercepted our connections without any
error message. Docker keeps our database fully isolated, and anyone can
get the exact same setup with one command.

**What happens if something fails partway through processing a document —
say, the call to OpenAI times out?**
The document is marked `failed` in the database, instead of being left
stuck at `pending` forever. Without that, a failed document would look
identical to one still normally processing — no signal anything went
wrong, and no way to know if it's safe to retry.

**If a document has 50 chunks and the embedding call fails, does the
document end up with 49 saved chunks and 1 missing?**
No — all of a document's chunks are sent to the embedding model in a
single batch request, not one at a time. If that one request fails, zero
embeddings come back, so zero chunks get saved. It's all-or-nothing, not
partial.

**What happens if someone uploads a scanned PDF — basically a photograph
of a page?**
A PDF page can either contain real character data ("draw the letter H
here") or just one embedded photo covering the whole page, with no
character data at all — that's what a scan or phone photo produces. Our
text extraction finds nothing on a page like that, so it contributes no
searchable content. Not handled yet — the real fix would be OCR (a
technology that reads text out of images), which we haven't added.

**If this had to handle 10x the documents — thousands of large PDFs a
day — what breaks first?**
Not really "the embedding model is slow" — it's that our synchronous
design ties up a web server request for the *entire* time that slow call
takes. At high volume, thousands of concurrent uploads would each hold a
server worker hostage waiting on OpenAI, and we'd run out of available
workers long before OpenAI itself became the bottleneck. This is exactly
the scenario that would justify finally adding Kafka.

---

## Feature 2: Retrieval + Answer Generation

**What does this feature do, in one sentence?**
It takes a question, turns it into the same kind of meaning-vector as our
stored chunks, finds the chunks whose meaning is closest to the question,
and asks an LLM to answer using only those chunks.

**Why do we compare vectors instead of just comparing the question's raw
text against each chunk's raw text?**
Comparing raw text can only really catch matching keywords. Vectors
capture *meaning* — so two chunks phrased completely differently but
saying the same thing will still be found as similar. That gives much
better, more relevant matches than keyword matching.

**The chunk's text lives in Postgres, and its embedding lives in
pgvector — how are the two linked together?**
They're not actually two separate things needing to be linked. pgvector
is just an extension that adds a new column type to Postgres itself — the
chunk's text and its embedding vector are two columns sitting right next
to each other in the exact same row, in the one `chunks` table. There's no
separate system, so there's nothing to map.

**Why cosine similarity, out of the three metrics pgvector supports
(cosine, L2 distance, inner product)?**
Cosine similarity measures the angle between two vectors, which captures
"how similar in meaning" regardless of how long either piece of text is —
and it's the metric OpenAI's own documentation recommends for their
embeddings. That matches our case well, since questions and chunks are
rarely the same length.

**Why gpt-4o-mini instead of the more capable gpt-4o for generating
answers?**
Answering a question from a small set of retrieved chunks is "grounded"
question answering, not open-ended reasoning — it doesn't need gpt-4o's
extra reasoning power. gpt-4o-mini is much cheaper and faster, which
matters more right now than a capability we don't need yet. Since the
model name is just a setting, upgrading later is a one-line change, no
code changes required.

**Why do we explicitly tell the LLM to say "I don't know" instead of
trusting it to behave well on its own?**
An LLM's default tendency, unless told otherwise, is to always produce a
confident-sounding answer — that's what most of its training rewards.
Weak or irrelevant retrieved context is more likely to produce a
hallucinated (confidently made-up) answer than an honest refusal, unless
we say so directly in the instructions we give it.

**If the `chunks` table had 10 million rows instead of a handful, what
happens to `/query`'s response time, and what's the actual fix?**
Right now, finding the closest chunks means comparing the question against
*every single row* — fine at tiny scale, painfully slow at millions of
rows. The fix isn't a hash map (hash maps only do exact-key lookups, and
there's no "exact match" in similarity search). The real fix is a vector
index like HNSW, which pre-organizes the vectors into a searchable
structure so a query only has to check a small fraction of all the rows,
trading a tiny bit of accuracy for a big speed gain.

---

## General concepts worth being able to explain from memory

**What is RAG (Retrieval-Augmented Generation)?**
The pattern of finding relevant text first, then handing it to an LLM to
write an answer from — instead of asking the LLM to answer purely from
what it already knows, which risks it confidently making things up.

**What's the difference between a service and a repository in this
codebase?**
A repository's only job is talking to the database — save this, get that
— with no business logic in it. A service holds the actual business
logic: the sequence of steps and decisions a feature performs. Keeping
them separate means you can test the logic without a real database, and
swap out how data is stored without touching the logic that uses it.

**What is hallucination, and how do we guard against it here?**
Hallucination is when an LLM confidently states something false or made
up, usually because it lacks real information and defaults to guessing.
We guard against it by grounding every answer in retrieved text, and by
explicitly instructing the model to admit when it doesn't know rather
than guess.
