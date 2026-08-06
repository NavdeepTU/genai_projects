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
design ties up a database connection for the *entire* time the pipeline
runs. The connection pool defaults to 15 total connections, and each
upload holds one for the whole 2-30 seconds a document takes to process.
So somewhere around 15 concurrent uploads, new requests stop failing
cleanly and start queueing silently, which shows up as rising latency, not
a clear error — that's the concrete number that would justify finally
adding Kafka, not a vague "too much traffic." It's also worth being honest
that Kafka isn't free to run: it means an always-on consumer process
burning compute even at zero load, and a new failure mode (a stalled
consumer, growing backlog) that's invisible unless someone's specifically
watching queue depth — a genuinely different on-call signal than "a
request is slow."

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
rows. Concretely, 10 million chunks at 1536 dimensions each is around 61
GB of raw embedding data alone, and every query would scan all of it. The
fix isn't a hash map (hash maps only do exact-key lookups, and there's no
"exact match" in similarity search). The real fix is a vector index like
HNSW, which pre-organizes the vectors into a searchable structure so a
query only has to check a small fraction of all the rows, trading a tiny
bit of accuracy for a big speed gain. That's also the point where I'd
actually consider moving to Qdrant instead of pgvector — not before, since
pgvector already runs inside infrastructure we're already operating and
monitoring, and standing up a second stateful service is a real ongoing
cost, not just a technical upgrade.

---

## Feature: Correlation IDs, Audit Logging, and Circuit Breakers

**What do these three features do, in one sentence each?**
Correlation IDs let you trace one request's whole story through the
logs. The audit log is a permanent record of who did what, for
accountability. Circuit breakers stop hammering an external service
(OpenAI) once it's clearly failing, instead of every request separately
waiting for a doomed call to time out.

**Why did we only build these three "enterprise requirements" now, and
defer PII detection, access control, and the Azure-specific ones?**
The project's rules said all 8 were "non-negotiable from the start," but
that directly contradicted the project's own build order, which lists PII
detection and access control as later steps. We resolved it by splitting
on actual buildability: these three don't depend on anything that doesn't
exist yet, while access control is meaningless with no auth model built,
and the Azure-specific ones (API gateway, Key Vault) don't apply to a
system that only runs locally.

**Why a `ContextVar` for the correlation ID instead of FastAPI's
`request.state`?**
`request.state` only works for code that has a direct reference to the
`request` object — true for route handlers, not true for services and
the repository, which are called several layers deep and intentionally
never receive `request` as a parameter. A `ContextVar` is readable from
anywhere in that call chain without threading it through every function
signature.
*Further reading: [Python's official `contextvars` documentation](https://docs.python.org/3/library/contextvars.html).*

**Why does the audit log's repository only expose an insert method?**
Because the whole value of an audit log depends on nobody being able to
quietly edit or delete an entry after the fact — if it could be altered,
it couldn't be trusted as evidence of what really happened. Not exposing
update/delete methods in code is the first layer of that protection.

**Is the audit log actually tamper-proof today?**
Honestly, not fully. The application code can't alter it, but our local
database connection is a superuser, which can bypass real database-level
restrictions. Even a properly restricted role is only a partial fix,
though — the real enterprise answer is usually shipping audit entries to
genuinely separate write-once storage, like blob storage with an
immutability policy, precisely because "a table in the same database,
reachable by anything with enough privilege" isn't a real compliance
boundary. That's a known, deliberately deferred gap, not an oversight.
There's also no retention or archival policy yet — the table just grows
with every request, which is fine at this scale but would need a plan
before it wasn't.

**Why build a circuit breaker by hand instead of using a library?**
Consistent with how the rest of the project was built — extraction,
chunking, and the API calls themselves were all written by hand so the
mechanism is fully understood, and a circuit breaker is simple enough
that building it doesn't cost much.
*Further reading: [Martin Fowler's "CircuitBreaker"](https://martinfowler.com/bliki/CircuitBreaker.html) — the article that popularized the pattern.*

**If we ran two copies of this server, what breaks?**
The circuit breaker's state lives in each process's own memory — nothing
shares it across processes. So each server instance has to independently
rack up its own 3 failures before its circuit opens, while a healthy-looking
instance that hasn't personally seen those failures yet keeps calling the
already-failing service. The fix would be moving that state into
something shared across instances, like Redis.

---

## Feature 3: Hybrid Search

**What does hybrid search do, in one sentence?**
It runs a vector (meaning-based) search and a keyword (exact-term) search
at the same time, then merges the two ranked result lists into one, so
the system catches both "conceptually similar" matches and "contains
this exact word/code" matches.

**Why isn't vector search alone good enough?**
Embedding models represent general meaning, not exact lexical identity —
they're weak at guaranteeing a match on specific things like error codes,
product IDs, or rare proper nouns. A document containing the exact string
"ERR-4521" might not surface for a search on that exact code, because the
embedding model never learned that string as meaningfully distinct from
similar-looking text.
*Further reading: [PostgreSQL's official Full Text Search documentation](https://www.postgresql.org/docs/current/textsearch.html).*

**Why Postgres full-text search instead of a dedicated engine like
Elasticsearch?**
Same reasoning as pgvector over Qdrant: it keeps everything in one
database, no new infrastructure, no second system to keep in sync. A
dedicated engine is more powerful at real scale, but that's overkill for
where this project is today.

**How does Postgres actually decide if a chunk "matches" a keyword
query?**
It's not raw string matching. Both the chunk's text and the query get
normalized the same way first — split into words, lowercased, stop words
like "the" and "a" removed, and each remaining word stemmed to its root
form (so "running," "runs," and "ran" all become "run"). Then it checks
whether the query's processed words appear in the chunk's processed
text, and ranks matches by relevance, not just whether a match exists.

**Why merge the two result lists using Reciprocal Rank Fusion instead of
just combining their raw scores?**
Cosine distance (vector search) and text relevance (`ts_rank`) are
measured on completely different, incomparable scales — there's no
principled way to add "0.23 cosine distance" to "1.8 relevance score."
RRF sidesteps that by scoring each chunk based on *where it ranked* in
each list instead of its raw score, then summing those rank-based scores
— which both methods can express in exactly the same terms.
*Further reading: the original paper — [Cormack, Clarke & Buettcher, "Reciprocal Rank Fusion outperforms Condorcet and Individual Rank Learning Methods," ACM SIGIR 2009](https://dl.acm.org/doi/10.1145/1571941.1572114).*

**If a chunk is found by only one of the two searches, does it get
dropped?**
No — it's still included in the merged results, just with a score from
only that one list, so it won't rank as high as a chunk both searches
agreed on. Nothing gets excluded for appearing in only one list; RRF
works over the union of both.

**Hybrid search runs two queries per request now instead of one — what
does that actually cost?**
Concretely, it doubles database load per query, and since both queries
currently run sequentially against the same connection, each request
holds that connection from the pool for roughly twice as long as before.
Using the same pool math as the ingestion side — about 15 total
connections available — that means the point where concurrent queries
start queueing for a connection happens at roughly half the traffic
compared to before hybrid search existed. It's a real, halved number, not
a free upgrade, even though it doesn't show up until there's real
concurrent load.

**At 10 million rows, what actually gets slow, and why?**
Not "keyword search is inherently slower than vector search" — both
sides currently compute their comparison fresh, on every row, on every
query, with no real index. For keyword search specifically, that means
re-tokenizing and re-stemming every row's text from scratch on every
query. The fix is a GIN index on a persisted `tsvector` column, the exact
same pattern as the HNSW index needed on the vector side.

---

## Feature: Hybrid Search Hardening — Graceful Degradation on Partial Failure

**What does this change do, in one sentence?**
If one of hybrid search's two database queries fails, the system now
answers using whichever one succeeded instead of failing the whole
request — it only gives up if *both* fail.

**Why not just retry the failed search instead?**
Retrying sounds safer but often isn't. If a query failed because the
database is genuinely under load, retrying immediately adds more load to
an already-struggling system instead of relieving it — a "retry storm."
Proceeding with the search that did succeed costs nothing extra and needs
no new logic, since Reciprocal Rank Fusion already treats "found by only
one search" as a completely normal case.

**This came from a code review, not a feature request — how did that
process work?**
A background review agent went through the hybrid search code and
returned findings. I didn't take them at face value — I re-verified the
concrete ones myself against the running database (checked the actual
index with `\d chunks`, confirmed a claimed double-computation with
`EXPLAIN VERBOSE`, and actually executed a query that a different finding
claimed would crash — it ran fine, so that one got dropped). Only
findings that survived that verification became real work.

**What's the subtlety with rolling back the database session, and why did
fixing the first bug introduce a second one?**
Both searches share one connection. If a query fails, Postgres refuses
any further queries on that same connection until it's explicitly rolled
back — so catching the failure isn't enough by itself; the *other* search
would fail too without an explicit `rollback()`. But `rollback()` doesn't
just reset the connection — it also expires every object the session is
still holding onto, including the chunks the *other* search had already
successfully fetched moments earlier. The next time the code reads one of
those chunks' text, SQLAlchemy tries to quietly reload it from the
database, which isn't allowed outside of an `await`, and crashes instead.
The fix: detach each search's results from the session (`session.expunge()`)
immediately after fetching them, so a later rollback has nothing left of
theirs to invalidate.
*Further reading: [SQLAlchemy's official docs on session state management and object expiration](https://docs.sqlalchemy.org/en/20/orm/session_state_management.html).*

**How was this actually verified, not just reasoned about?**
With a small script that force-fails each search independently (vector
only, keyword only, then both) against the real repository and a real
database connection, and checks the actual outcome. That script is what
caught the session-expiry bug — reading the code after the first fix
looked correct; running it didn't.

**If we ran this at real production scale, what changes about how this
failure would be noticed?**
Before this change, a keyword-search-only problem (e.g. the missing index
turning slow under real load) would fail *every single query* — loud, but
overstates the actual damage. After this change, the same problem shows
up as quietly degraded answer quality (RRF running on vector-only
results) with an error log per failed search — a more accurate signal,
but a much quieter one that needs someone actually watching per-search
failure rates to catch. Nothing in this project watches that yet.

---

## Feature 4: Reranking

**What does reranking do, in one sentence?**
It takes hybrid search's candidate chunks — now a wider pool of 20,
instead of the final 5 — and uses a model that looks at the question and
each chunk *together* to pick the 5 that actually answer it best, instead
of trusting vector/keyword search's own ranking as final.

**Why isn't hybrid search's own ranking good enough on its own?**
Vector and keyword search both score the question and a chunk
*separately* — an embedding compares two independently-computed numbers,
never the actual texts side by side. That's fast enough to check against
every row in the database, but approximate. A reranker (specifically, a
cross-encoder) processes the actual question and one actual chunk
together in a single pass, which is far more accurate — but far too slow
to run against everything, only against a short list hybrid search has
already narrowed down.
*Further reading: [Sentence Transformers' official "Retrieve & Re-Rank" documentation](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html), which lays out exactly this two-stage pattern.*

**Why does hybrid search now fetch 20 candidates instead of 5?**
Because reranking needs something to actually choose between. If hybrid
search only ever produced the final 5, reranking would still technically
run — Voyage would still score and could still reorder those same 5 — but
it could never promote a chunk that hybrid search's own ranking happened
to place 8th over one it ranked 3rd, since anything outside the top 5
would already be gone. Fetching a wider pool is what gives reranking room
to actually change *which* chunks reach the LLM, not just their order.

**Why Voyage AI specifically, over a local model or reusing OpenAI?**
Three options existed: a local open-source cross-encoder, Voyage's hosted
Rerank API, or asking OpenAI directly via a prompt to rank the
candidates. OpenAI would have been the easiest to wire in — same client,
same settings pattern already used twice — but the goal was specifically
to use a model actually trained for relevance scoring, not repurpose a
general chat model for a task it wasn't trained for. Voyage over a local
model, specifically to avoid pulling a heavy new ML dependency (PyTorch,
downloaded weights) into a project where every AI capability so far goes
through a hosted API, not local inference. Its free tier (200 million
tokens) also made cost a non-factor, confirmed by checking current
pricing directly rather than assuming.

**What happens if Voyage itself fails?**
Its own independent circuit breaker opens after 3 failures in 60 seconds,
same mechanism as the two OpenAI ones. Unlike an OpenAI failure, this
doesn't fail the request — `retrieval_service.py` catches it and falls
back to hybrid search's own Reciprocal Rank Fusion order instead. This
makes reranking the one external AI dependency in this system where
failure degrades *quality*, not *availability* — verified for real by
forcing the circuit breaker open and confirming the request still
succeeded.

**A real mistake happened while wiring this up — what, and how was it
caught?**
A real Voyage API key briefly ended up in `.env.example` — the *template*
file meant to be committed to git with placeholder values — instead of
`.env`, which is git-ignored. Caught by checking `git status` and
`git log` before anything got pushed: the change was still unstaged and
uncommitted, so nothing ever reached git history. Fixed immediately, and
the exposed key was rotated anyway, since it had already appeared in
conversation transcript text — cheap insurance for something free to
redo. The habit worth keeping: `.env.example` only ever gets
placeholder-shaped values; real secrets only ever go in `.env`.

**If this had to run at real scale, what's the actual cost, and what's
the honest trade-off?**
At an estimated ~13,000 tokens per query (a question plus 20 candidate
chunks), the 200-million-token free tier covers well over 15,000 queries
before any billing starts, and stays cheap after that. The honest
trade-off isn't cost, though — it's that this system now depends on
*three* independent external AI vendors (two OpenAI call sites plus
Voyage) for one query to fully succeed, each with its own credentials to
manage and its own circuit breaker to reason about independently.

---

## Feature 5: LangGraph Query Pipeline

**What does this feature do, in one sentence?**
It turns the query pipeline from a fixed sequence of steps into a graph
that can notice its own retrieval results are weak, rewrite the
question, and search again once before generating an answer.

**The query pipeline was already five steps in a row before this — what
does LangGraph actually add over what we had?**
Being multi-step isn't the same as being able to make decisions.
Before, step 2 always followed step 1 no matter what happened — a
straight line. LangGraph adds *conditional* edges: after reranking, the
pipeline can check what it actually found and branch — loop back and
try again, or move on — instead of blindly continuing regardless of
result quality.

**The original plan was "retry if reranking returns zero chunks" — why
isn't that in the final code?**
Because it doesn't work, and that was only found by actually testing it
live, not by reading the code. Vector search has no relevance floor —
`find_similar_chunks` always returns the *closest* chunks by distance,
however irrelevant, as long as the table isn't empty. Asking a
completely unrelated question against the real database never
triggered the retry, because "zero results" essentially never happens
outside of an empty database.

**So what actually decides when to retry?**
Voyage's own `relevance_score` on the *best* reranked chunk — not "any"
or "all" five chunks, just the top one, since generation only needs one
genuinely relevant chunk to work from. If the best one scores below
`0.4`, and this is the first attempt, the pipeline rewrites the question
and searches again. The threshold itself came from real measurements
against the dev database: a genuinely relevant match scored `0.914`;
two different irrelevant questions both scored `~0.28–0.29` — a wide,
clean gap, with `0.4` sitting comfortably inside it.

**Why does the retry skip entirely — not just decline — when reranking
itself is unavailable, rather than when it's just weak?**
Those are different problems with different fixes. A weak score means
reranking *worked* but found nothing good — rewriting the question is a
real attempt to fix that. Reranking being *unavailable* means the tool
that would even tell you whether to retry is down — rewriting the
question and searching again can't fix an unreachable API, and would
almost certainly just hit the same open circuit breaker a moment later,
for no benefit.

**Why is the final answer always generated from the *original* question,
never the rewritten one?**
The rewritten question is a search tool, not a replacement for what the
user actually asked. If a rewrite broadens "Q4 revenue for Acme" into
something more searchable, the answer still needs to address the
specific thing asked — otherwise the system quietly answers an easier,
different question than the one it was given.

**If this had to handle 10x the traffic, would you raise `MAX_RETRIES`
to catch more relevant chunks?**
No — that's the wrong lever, and it's worth knowing why it's tempting
but wrong. Every retry is a full extra round trip through embedding,
both searches, and reranking again. At 10x traffic, both circuit
breakers already trip more often just from call volume; raising the
retry cap would send *more* load at the exact vendors already
struggling, tripping their breakers even faster — the same retry-storm
problem ADR-012 already reasoned its way out of once. The better lever
is tuning the circuit breakers' own thresholds to scale with traffic,
not retrying more.

**A real testing mistake happened while verifying this — what, and what
does it teach about testing LangGraph code specifically?**
Patching `RetrievalService._rewrite_node` on the class, after
constructing a `RetrievalService`, silently did nothing — the spy never
fired even when the method genuinely ran. The graph is built once in
`__init__` and captures a bound-method *reference* at that moment;
patching the class afterward doesn't reach an already-built graph. The
fix was patching the module-level `rewrite_query` function instead,
which every node looks up fresh on each call. Worth remembering
generally: patch what's actually looked up at call time, not something
already captured earlier.
*Further reading: [LangGraph's official `StateGraph` API reference](https://reference.langchain.com/python/langgraph/graph/state/StateGraph).*

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
