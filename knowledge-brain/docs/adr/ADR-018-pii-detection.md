# ADR-018: PII detection in the ingestion pipeline

## Status
Accepted

## Context
Build-order item 7. Deferred twice before now — once at project start
(no auth model existed yet to make ACL meaningful, so PII/ACL were
pushed to their existing build-order slots), and again when the
evaluation harness was chosen instead, on the reasoning that the
retrieval pipeline's growing complexity was more urgent than a
compliance feature with no live exposure yet. That second reason
stopped applying once last session's `ADR-017` made MCP's
`upload_document` a real, network-reachable way for someone else's
data to enter the system — the exposure this feature protects against
became concrete, not theoretical.

## Options considered
For where the check runs:
1. **Inside each API route** (`app/api/documents.py` and
   `app/mcp/server.py`'s `upload_document` tool), separately.
2. **Inside `IngestionService.ingest_document`**, the one place both
   entry points already funnel through.

For what happens when Azure's PII service itself is unavailable:
1. **Fail open** — proceed with ingestion anyway, the same best-effort
   pattern reranking and Neo4j use.
2. **Fail closed** — don't embed until the document has actually been
   checked.

For which PII categories trigger a flag:
1. **Azure's full default set** (173 categories, everything from
   direct identifiers to dozens of countries' government ID formats).
2. **An explicit, hand-picked allowlist.**

## Decision
Run the check inside `IngestionService`, not either route. Fail
closed on an Azure outage. Use an explicit 14-category allowlist —
`Person`, `PhoneNumber`, `Email`, `Address`, `Age`, `CreditCardNumber`,
`USBankAccountNumber`, `InternationalBankingAccountNumber`,
`USSocialSecurityNumber`, `USIndividualTaxpayerIdentification`,
`USDriversLicenseNumber`, `USUKPassportNumber`,
`INPermanentAccount`, `INUniqueIdentificationNumber` — passed to Azure
via `categories_filter`, not Azure's default set.

## Reasoning
Both API routes were rejected as the place to add this check for the
same reason MCP itself needed zero changes to `IngestionService` last
session: the service layer never depended on which door a request came
through, and duplicating the check in two route files would mean two
places to keep in sync instead of one. Putting it inside
`IngestionService` protects both `/documents/upload` and MCP's
`upload_document` automatically, verified live through both paths.

Fail closed was chosen specifically because this is a compliance
control, not a quality-of-answer feature — the reasoning that justifies
reranking or Neo4j degrading gracefully (a missing "nice to have"
still gives a usable answer) doesn't apply here, since the entire
point of this check is that an unverified document must not be
embedded. Concretely, this decision needed no new code: `CircuitOpenError`
raised by `detect_pii` already falls into the existing
`except Exception` block in `ingest_document`, which was written for
other failures — placing the check inside that same `try` block was
the only change needed to get fail-closed behavior for free.

The full-default-set option was tried first, not assumed away — and
live testing (not code review) caught a real problem with it: Azure's
`PersonType` category flagged the word "Employees" in a completely
unremarkable vacation-policy document at 98% confidence, and "Customer"
in the genuine PII test document alongside the real findings. `PersonType`
identifies a *role* being mentioned, not a specific individual's
information — a category that would make nearly every business
document flag, since almost all of them mention roles. Notably,
`PersonType` isn't even a member of Azure's own filterable
`PiiEntityCategory` enum, so it can't be explicitly excluded by name —
an allowlist sidesteps that entirely, since anything not requested,
including `PersonType`, simply never comes back. The 14 categories
chosen cover direct identifiers, financial data, and government IDs
for the US and India specifically — every other country's ID formats
(national IDs, tax numbers, driver's licenses, for dozens of
countries) were deliberately left out as out of scope for now, not
because they aren't real PII. Credentials/secrets categories (Azure
storage keys, connection strings, `SWIFTCode`) were excluded on
purpose too — a different risk category from personal information,
explicitly out of scope for this feature.

## Consequences
- New files/changes: `app/services/pii_detection.py` (`detect_pii`,
  `_split_into_documents`), a new circuit breaker
  (`azure_pii_detection`) — its own instance, independent of every
  other one in this project, so an Azure Language outage can't be
  mistaken for an OpenAI or Voyage outage. `Document` gains
  `pii_detected` (permanent, survives a status change later) and
  `failure_reason` (distinguishes a genuine bug from an Azure outage,
  both of which previously collapsed into the same generic `FAILED`
  status with no way to tell them apart). New `DocumentStatus.PENDING_REVIEW`.
  New repository methods `flag_for_review` and `mark_failed`, mirroring
  each other's shape — a compound state change gets its own named
  method rather than an optional parameter bolted onto the generic
  `update_status`.
- Long documents are split on paragraph breaks, not a hard character
  cut, to stay under Azure's real, verified 5,120-character
  synchronous-request limit (checked against Microsoft's own docs, not
  assumed) while minimizing the chance of severing a name or address
  across a split boundary — not eliminating that risk, since a name
  could still fall exactly on a paragraph break. Pieces are batched up
  to 5 per request, Azure's own hard cap, and every category found
  across every piece is unioned into one result.
- A schema migration gotcha, found by checking the live database
  directly rather than assuming: SQLAlchemy's native Postgres enum
  stores the Python enum's *member names* (`PENDING`, `READY`), not
  its lowercase `.value` strings — the `ALTER TYPE ... ADD VALUE`
  command had to add `'PENDING_REVIEW'`, not `'pending_review'`, to
  match. Also, SQLAlchemy's `default=` is Python-side only; the
  `pii_detected` column's `ALTER TABLE` needed its own SQL-level
  `DEFAULT false` to apply to already-existing rows, not just future
  ones.
- Verified live end to end, through both entry points: a document with
  a real name, phone number, and SSN correctly ends up
  `PENDING_REVIEW` with `pii_detected = true` and zero chunks saved
  (never embedded); a clean document correctly reaches `READY`; a
  document containing an Indian PAN number, uploaded through the MCP
  tool specifically, correctly gets flagged too — confirming the
  "protects both doors" claim wasn't just theoretical.

## Scale, cost, and on-call reality
This adds one more real external dependency — and one more real
external cost — to every single document upload, on both entry points.
At meaningfully higher upload volume, Azure Language's own rate limits
(shared, same tier structure as every other Cognitive Services
resource) become a real constraint alongside the OpenAI/Voyage limits
that already exist, not a new category of problem, just one more
vendor in the same position.

The 14-category allowlist is a real, named scope limit, not
comprehensive coverage: it only recognizes US and India government ID
formats. A document containing, say, a French social security number
or a UK national insurance number would currently sail through
undetected — not a bug, a deliberate scope decision, but one that
would need revisiting before this system could honestly claim broad
compliance coverage for a truly international document set.

Fail-closed has a real availability cost worth being honest about: an
Azure Language outage now blocks *all* uploads system-wide, on both
entry points, not just PII-affected ones — a stronger guarantee than
reranking or Neo4j's best-effort degradation, deliberately traded for
correctness on a compliance-critical check. A future improvement worth
naming: today, a flagged document has no admin UI to actually get
reviewed and released — `pii_detected` and `PENDING_REVIEW` exist in
the database, but nothing yet lets a human act on them. That's
frontend work, a future build-order item, not built here.
