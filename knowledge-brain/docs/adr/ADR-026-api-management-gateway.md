# ADR-026: API Management gateway on Consumption tier — one lock, not two

## Status
Accepted. The mechanism itself is verified live via API Management's own
request trace. A full, clean end-to-end status-code test is currently
blocked by a separate, unrelated gap — tracked as its own standalone
item, not part of this decision's scope.

## Context
Build-order item 11 (API gateway via Azure API Management) was the one
piece of the original Azure deployment work still open after item 10
closed. The Container App backend was reachable, deployed via CI/CD,
and correctly enforcing correlation IDs, identity, and document-level
ACL — but its own URL was still directly exposed to the public
internet, with nothing in front of it. A direct, named violation of
Enterprise Requirement 1.

The design called for two independent locks: a network-layer
restriction (only accept traffic from APIM's own outbound IP) and a
request-layer secret (APIM stamps a header only it and the backend
know, checked by new middleware). Consumption tier was chosen
deliberately over Developer/Premium for cost — pay-per-call, no fixed
monthly bill, consistent with every other "cheapest managed option"
already chosen in this project (Postgres Burstable, ACR Basic, Neo4j
AuraDB Free).

## What we built
- `infra/apim.tf` — the APIM instance itself (Consumption tier,
  system-assigned identity), an API definition importing FastAPI's own
  OpenAPI spec rather than hand-declaring every route a second time, a
  randomly generated gateway secret stored in Key Vault and read by
  APIM through a Key Vault-backed named value, and a policy stamping
  that secret onto every request APIM forwards.
- `app/core/middleware.py` — `gateway_secret_middleware`, checking that
  header with a constant-time comparison, positioned between
  `correlation_id_middleware` (outermost) and `user_id_middleware`
  (innermost) — deliberately checking "did this come through our
  gateway" before "who is this," since the former is the more
  fundamental question a request has to answer first.
- `infra/main.tf` originally also included a `dynamic
  "ip_security_restriction"` block on the Container App's ingress,
  looping over `azurerm_api_management.main.public_ip_addresses`.

## Two real, evidence-driven reversals
1. **Consumption tier has no static outbound IP at all.**
   `az apim show ... --query publicIpAddresses` came back empty — not a
   config mistake, a genuine tier limitation confirmed live, not
   assumed. The `dynamic` block therefore generated zero rules; Azure
   reported `"ipSecurityRestrictions": []` even though `terraform
   apply` had exited cleanly. True network isolation needs Developer
   tier's VNet integration instead — a real, ongoing cost (roughly
   $48–50/month, ~₹4,000–4,400/month, itself only a rough estimate from
   third-party sources, not confirmed directly against Azure's own
   calculator), not a config toggle.
2. **Rate limiting isn't available in the form originally designed,
   either.** `rate-limit-by-key`, keyed per caller IP or subscription,
   failed with `"Policy is not allowed in 'Consumption' sku"` the
   moment it was actually saved. The alternative Azure's own policy
   picker offers on this tier, plain `rate-limit`, is scoped
   per-*subscription* — meaningless here, since `subscription_required
   = false` was already set deliberately, to avoid building APIM's
   separate subscription-key system this session. Adding real rate
   limiting back would mean reversing that decision first, not pasting
   in a snippet.

## Decision
- Accept one real lock — the gateway secret header — rather than two,
  given the real, ongoing cost of the alternative. The dead
  `ip_security_restriction` block was removed entirely rather than
  left in, since code that implies protection it doesn't provide is
  worse than no code at all.
- Deferred explicitly, not forgotten: rate limiting (blocked by tier,
  not by the subscription-key decision — see the corrected reasoning
  below), request/response logging (needs Application Insights
  wiring), and APIM's own subscription-key concept.
- `subscription_required = false` kept as-is. The gateway secret is
  the one mechanism actually gating access today.

## Reasoning
Same evidence-first approach this project has used for every other
real incident (ADR-020's Postgres region restriction, ADR-022's arm64
image mismatch): both reversals here were confirmed by actually
running the thing and reading Azure's own response, not by researching
Terraform schemas harder beforehand. A smaller instance of the same
lesson showed up mid-session too — the `ip_security_restriction`
block's `priority` argument, copied from memory of App Service's
`ip_restriction` schema, doesn't exist on Container Apps' version at
all; caught only once `terraform plan` said so directly.

The one-lock outcome mirrors a precedent this project already set:
MCP's server accepted a single shared secret as "good enough,"
explicitly naming that anyone holding it is indistinguishable from a
legitimate caller. The same trade-off applies here now, for the same
reason — proportionate to a project with no real production traffic
yet, not a permanent design.

## Consequences
- A request reaching the Container App's raw URL directly, bypassing
  APIM entirely, is only rejected if it doesn't carry the correct
  `X-Gateway-Secret` value — nothing about the request's actual path or
  network origin is checked anymore. If that secret ever leaks, anyone
  holding it can call the backend directly, skipping whatever rate
  limiting or logging APIM would otherwise have provided — the same
  named risk this project already accepted for MCP's key, now applying
  here too.
- API versioning (the `/v1/` prefix) and the auth-token gate (the
  header) are real and verified working. Rate limiting and structured
  request/response logging are not built, and are tracked as separate,
  explicit follow-ups rather than silently dropped from the original
  Enterprise Requirement.
- A live incident surfaced as a side effect of testing this feature,
  not caused by it: the Azure Postgres database has no application
  tables at all — nothing has ever run `create_tables.py` against it.
  Both `gateway_secret_middleware` and `user_id_middleware` write to
  `audit_log` on every rejection before returning an error response, so
  this crashes *any* rejected request against the live deployment
  today, which blocked a clean end-to-end status-code test of this very
  feature. The mechanism was still verified — through APIM's own
  request trace, which showed the secret correctly resolved, stamped,
  and forwarded, and the backend correctly routing the request into the
  expected middleware chain before crashing on this unrelated cause.
  Tracked as its own standalone item, not folded into API Management's
  scope, and not yet fixed.

## Scale, cost, and on-call reality
On Consumption tier, this backend's entire security posture rests on
one secret value never leaking — there is no network-level backstop if
it does. Upgrading to Developer tier would add real, ongoing monthly
cost but close this gap structurally, through VNet integration, rather
than by convention. At genuine production scale with real external
users, the two-lock design would very likely be worth that cost; for a
project with no real external traffic yet, accepting the savings is
the more defensible call — the same reasoning already applied to the
Postgres/Redis/Neo4j tier choices elsewhere in this project. Whoever
operates this at real scale should treat "upgrade tier for network
isolation" and "add real per-caller rate limiting" as linked
follow-ups, not separate ones — both depend on the same
subscription-key decision this session deliberately left unopened.

Worth naming as a general, recurring lesson, not just this feature's
own footnote: a clean `terraform apply` proves configuration was
*accepted*, never that it's *doing what was intended*. This project has
now hit that exact gap three separate times — ADR-020's Postgres zone
drift, ADR-022's arm64 image silently failing to start, and tonight's
IP restriction silently generating zero rules — each one only caught by
checking real, live behavior afterward, never by the apply itself.

**Correction, caught during this ADR's own interview-prep review:** the
paragraph above originally claimed upgrading tier and adding real rate
limiting both depend on reopening the `subscription_required = false`
decision. That's not accurate. `rate-limit-by-key` — the policy
actually wanted, keyed on caller IP/subscription via a custom
expression — never required subscriptions in the first place; it
failed tonight purely because Consumption tier disallows it outright.
Developer/Premium tier likely restores `rate-limit-by-key` directly,
with no need to touch `subscription_required` at all. If that holds
up, "upgrade tier" alone gets back *both* network isolation and real
per-caller rate limiting as two benefits of the same move, rather than
two separate blockers layered on top of each other. Not yet confirmed
against Azure's own policy-availability docs — flagged here as the
next thing to verify before committing to it, not asserted as settled.
