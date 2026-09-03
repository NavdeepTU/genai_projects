# ADR-038: LLM/RAG observability via LangSmith

## Status
Accepted.

## Context
Build-order item 15. Since the Dashboard and Analytics pages shipped
(ADR-032, ADR-033), "cost per query" and "retrieval accuracy trend" have
both sat as honest "not tracked yet" placeholders — this system has never
recorded what a single LLM call actually cost, how many tokens it used,
or what the model was actually shown versus what it actually returned.
General infrastructure monitoring (Azure Monitor, Application Insights)
already exists for the app as a whole; this is different and narrower —
visibility into what happens *inside* a single OpenAI or Voyage call, not
whether the service is up.

## Options considered

**Which tool:**
1. **LangSmith** — built by the same team as LangChain/LangGraph. Traces
   a LangGraph graph's execution automatically, node by node, once
   tracing is turned on process-wide. A hosted service; trace data
   leaves this project's own infrastructure.
2. **Langfuse** — open source, self-hostable (matching how Postgres and
   Neo4j already run via Docker here), or usable as a hosted cloud
   service with a similar trade-off to LangSmith. Framework-agnostic,
   needs more manual instrumentation for the parts that aren't already
   LangChain/LangGraph-shaped.

**Where this gets viewed:**
1. **A separate, dedicated tool** (LangSmith's or Langfuse's own
   dashboard) — the user's own explicit choice, rather than building a
   third UI on top of the Dashboard/Analytics pages this project already
   has.
2. Build cost/token tracking into our own Dashboard/Analytics pages
   directly.

**What a trace actually contains:**
1. **Full prompt and response text**, alongside token counts, cost,
   latency, and success/failure — the user's own explicit choice, most
   useful for debugging why one specific answer came out wrong, at the
   cost of retrieved document text leaving this project's infrastructure.
2. Metadata only (tokens, latency, cost, model, success/failure) — never
   the actual prompt or document content.

## Decision
LangSmith, viewed through its own dashboard (not built into this
project's UI), with full prompt/response content included in every
trace. Every trace tagged with `user_id` and `correlation_id`.

## Reasoning
LangSmith was chosen specifically because this project's query pipeline
is already a LangGraph graph (ADR-014) — turning tracing on process-wide
captures that graph's execution automatically, one span per node
(`_retrieve_node`, `_rerank_node`, `_generate_node`, and so on), with zero
change to the graph's own step logic in `retrieval_service.py` or
`query_graph.py`. Langfuse would need the same result built by hand, or
via its own separate LangGraph callback integration, for a project that
gets this specific integration for free by virtue of a decision already
made a year earlier. Self-hosting Langfuse would also mean standing up
its own Postgres + ClickHouse + Redis stack — real, ongoing operational
weight for a single-developer learning project, not proportionate here.

Full content logging was chosen deliberately, not defaulted into: this
project already has a PII-detection layer (ADR-018) specifically because
document content sensitivity matters here, so sending full prompts to a
third party is a real trade-off, not a footnote — but the whole practical
value of this feature is being able to see *why* an answer came out
wrong, which metadata alone can't show. The PII allowlist's own limits
(14 categories, not exhaustive — see ADR-018) mean this isn't a fully
closed risk; worth knowing, not something this ADR claims to have solved.

The actual integration mechanism matters for understanding why so little
code changed: since this project calls the raw `openai` SDK directly
rather than through LangChain's own model wrapper classes, LangSmith's
`wrap_openai()` — which wraps a client *object*, not each call site — is
what makes automatic prompt/token/cost capture possible with one line
per file, instead of hand-instrumenting every call. Voyage AI has no
equivalent wrapper, so `rerank_chunks` uses `@traceable` directly instead
— same input/output/latency/error capture, but no automatic dollar cost,
since LangSmith's built-in pricing table only knows OpenAI's rates, not
Voyage's.

`user_id` tagging was added by passing it through `RunnableConfig`'s
`metadata` at the one place the query graph is actually invoked
(`RetrievalService.run_query`) — not by adding a new `ContextVar` read
inside each of the five service files. `run_query` already receives
`user_id` as an explicit parameter and threads it through `QueryState`
for every node; reusing that instead of a fresh lookup avoids a subtler,
real trap already documented in this project's own practice: a
`ContextVar` set by request middleware is reset back to empty by the time
a `BackgroundTasks` function runs (see ADR-030's ingestion path), so
reading `get_current_user_id()` freshly inside a service function would
have worked for the synchronous query path but silently broken the
moment the same function was called from a background context.

## Consequences
- New dependency: `langsmith`, added explicitly to `pyproject.toml` even
  though already present transitively via `langgraph` — this project's
  own convention is to declare what's actually imported directly, not
  rely on an undeclared transitive dependency that could disappear.
- New settings: `langsmith_api_key` (required, same convention as every
  other real API key here) and `langsmith_project` (defaults to
  `"knowledge-brain"`) in `app/core/config.py`.
- New `app/core/observability.py`: `enable_tracing()`, called once at the
  very top of `app/main.py`, before any other app module is imported.
  This exists because LangSmith's SDK reads real process environment
  variables (`LANGSMITH_TRACING`, `LANGSMITH_API_KEY`,
  `LANGSMITH_PROJECT`) directly — our own `.env` loading only populates
  a `Settings` object, it never touches `os.environ` — and every service
  module builds its OpenAI client at import time, before any function
  body could set this up otherwise.
- `app/services/embedding.py`, `generation.py`, `query_rewriting.py`,
  `reference_extraction.py`: one line each — `client =
  wrap_openai(AsyncOpenAI(...))` in place of the bare client. Nothing
  else in these files changed.
- `app/services/reranking.py`: `rerank_chunks` gets a
  `@traceable(run_type="tool", name="voyage_rerank")` decorator.
- `app/services/retrieval_service.py`: `run_query`'s single
  `self._graph.ainvoke(...)` call now passes `config={"metadata":
  {"user_id": ..., "correlation_id": ...}, "run_name": "query"}` — the
  one place user/request attribution gets attached, covering the entire
  trace, not just one call inside it.
- MCP inherits this completely unchanged — `ask_knowledge_base` and
  `upload_document` call the exact same service functions, so nothing
  MCP-specific needed touching, consistent with every other feature
  added under this pipeline so far.
- No new tests: this is instrumentation wrapped around already-tested
  functions, not new business logic: the existing 39-test suite passed
  unchanged, and passing with these wrappers in place is itself the
  relevant confirmation — the decorators don't break `unittest.mock`'s
  ability to substitute the underlying functions in tests.
- Verified live, twice: once with a placeholder API key (confirming a
  tracing failure never breaks the actual OpenAI/Voyage call — a real
  document upload and two real queries, one with genuine retrieval and
  reranking against real content, all completed successfully), and once
  with a real LangSmith account and key, confirming actual traces —
  prompt, response, tokens, cost — appear in LangSmith's own dashboard
  for a real query.

## Scale, cost, and on-call reality
Two real, named gaps, not silently skipped: ingestion-time traces
(embedding a document's chunks, extracting its references) are traced
but not tagged with `user_id` the way query traces are — attribution was
scoped to queries specifically, since that's what was actually asked
for, and threading `user_id` into the background-task ingestion path
would need the same explicit-parameter treatment `correlation_id`
already got there (see ADR-030), not built this pass. And Voyage's
reranking cost has no automatic dollar figure — getting one would mean
manually multiplying its token usage by its published per-token rate and
attaching it as trace metadata, not yet done.

Nothing here enforces a cost ceiling or alerts on a spike — this is
visibility, not a guardrail. LangSmith does support automations
(alerting) and feedback scores (which could eventually connect to the
existing eval harness, ADR-016), neither wired up this pass. And this
feature makes a real, permanent dependency on a third-party service's
uptime and pricing beyond its free tier explicit for the first time in
this project — every other external dependency so far (OpenAI, Voyage,
Azure AI Language, Neo4j) was already load-bearing for the app to
function at all; LangSmith is the first one that's purely observability,
meaning its own outages should never be allowed to affect the actual
pipeline. That's exactly why tracing failures are designed to fail
silently rather than raise — verified live with the placeholder-key
test above, not just assumed from the SDK's own documentation.
