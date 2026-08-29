# ADR-035: Let the backend Container App scale to zero

## Status
Accepted.

## Context
Reviewing Azure Cost Management for the first time since deployment
(ADR-020 through ADR-025) surfaced a real, unexpected cost: Azure
Container Apps was the single largest line item, at ₹617.08 for the
period reviewed — larger than every other resource combined. Checking
`infra/main.tf` directly, rather than guessing at generic Azure
pricing, found the cause immediately: `min_replicas = 1`. The backend
had been running exactly one replica continuously, 24/7, since it was
first deployed — paying for compute the whole time regardless of
whether any real request ever arrived. This project has near-zero real
traffic; the backend exists to be exercised occasionally during
development sessions, not served continuously to real users.

## Options considered
1. **`min_replicas = 0`** — let Container Apps scale the backend down
   to zero replicas after a period of no traffic, waking a fresh
   instance automatically on the next request.
2. **A manual start/stop script pair**, mirroring the approach
   proposed (but not yet built) for Postgres — explicitly stop the
   Container App before each dev session, start it after.
3. **Leave it at `min_replicas = 1`**, accept the cost as the price of
   always-instant responses.

## Decision
`min_replicas = 0`, `max_replicas` unchanged at `1`.

## Reasoning
Option 2 was rejected as solving a problem Container Apps already
solves better on its own. A manual toggle requires remembering to run
it, both at the start and the end of every session — the exact daily
discipline this project already avoided for Postgres by simply not
building it yet. `min_replicas = 0` needs zero ongoing action:
Container Apps' own default HTTP scale rule wakes a fresh replica
automatically the moment a real request arrives, whether from APIM,
the Container App's direct URL, or MCP. This is a genuine difference
in kind from Postgres, not just a different tool for the same job —
Postgres has no automatic wake-on-request mechanism, so a script
toggled by the developer is the only lever available there; Container
Apps' whole platform is built around exactly this behavior already.

Before deciding this was safe, checked Microsoft's own documentation
directly rather than assuming: `min_replicas = 0` without ingress
enabled can leave a Container App permanently stuck at zero
replicas, with nothing able to trigger it to wake back up. This
project's backend has `ingress { external_enabled = true, ... }`
already configured (needed regardless, since APIM and the direct URL
both depend on it) — so the danger case documented by Microsoft
doesn't apply here, confirmed rather than assumed.

Option 3 was rejected as the status quo the whole discussion started
from — no reasoning needed beyond naming it as the alternative that
was actually being paid for.

The real, accepted trade-off is cold start: the first request after
an idle period pays a real delay (FastAPI startup, plus the MCP
lifespan's `session_manager.run()`) before it responds, confirmed via
Microsoft's documented 300-second (5-minute) default cool-down period
before a Container App's last replica actually scales to zero. Every
request after that stays fast until the app idles out again. Given
this project's actual usage pattern — occasional development sessions,
not continuous real traffic — a few seconds of latency on the first
request of a session is a real cost worth paying for eliminating
continuous billing the other 23-plus hours of most days.

## Consequences
- `infra/main.tf`: `azurerm_container_app.backend`'s `template.min_replicas`
  changed from `1` to `0`, applied live via `terraform plan` /
  `terraform apply` — confirmed a clean in-place update (`0 to add, 1
  to change, 0 to destroy`), no resource recreation.
- No application code changed. This is purely a scaling-policy change
  to already-deployed infrastructure.
- MCP is affected identically to REST — both entry points run in the
  same container, so a client like Claude Desktop calling
  `ask_knowledge_base` after idle time pays the same cold start a
  browser hitting the REST API would.
- Verified the change didn't conflict with ADR-023's `lifecycle {
  ignore_changes = [template[0].container[0].image] }` block before
  applying — that block only protects the CI-owned `image` field, not
  `min_replicas`, so this change went through Terraform normally, with
  no need to work around the CI-ownership rule.
- Billing model confirmed directly from Microsoft's own documentation,
  not assumed: Consumption-plan Container Apps compute has three
  states, not two — *active* (processing a request, full rate),
  *idle* (a reduced but non-zero rate, only reachable when
  `min_replicas` is configured above zero and the app sits at that
  floor doing nothing), and *scaled to zero* (genuinely no charge).
  The previous `min_replicas = 1` configuration meant this app could
  only ever be in the first two states, continuously, all month —
  never truly free. `min_replicas = 0` removes the middle state
  entirely for this app; it's now either actively serving a request or
  costing nothing.

## Scale, cost, and on-call reality
This is a real, permanent fix for an idle project, not a workaround —
unlike Postgres (still mid-free-trial, so stopping it saves nothing
yet) or the Container Registry (which has no idle state to exploit at
all, a flat fee regardless), Container Apps' Consumption plan was
specifically designed for exactly this usage shape, and the fix cost
nothing but a one-line config change. The honest cost of this decision
is entirely UX, not money: at real, sustained traffic, a several-second
cold start on the first request after any lull would be a genuine
user-facing latency problem, not just a curiosity — the moment this
project has real users hitting it throughout the day rather than
occasional dev sessions, `min_replicas` should move back toward `1` (or
higher, with real autoscaling), trading the now-eliminated idle cost
back for consistent responsiveness. That's a real, load-bearing
trade-off to revisit deliberately when traffic patterns actually
change, not something to forget once set.
