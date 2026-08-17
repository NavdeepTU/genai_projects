# ADR-028: Frontend stack — Next.js, Tailwind, and Shadcn on Base UI

## Status
Accepted, verified live in the browser.

## Context
Build-order item 13 (the frontend dashboard) was the largest untouched
piece of this project, named as such across many prior sessions.
`CLAUDE.md` sets a specific, non-negotiable stack (Next.js, Tailwind,
Shadcn/UI, TypeScript, dark mode via CSS variables from day one) and an
explicit design bar ("world-class," not a templated default look).

## Decision
Scaffolded `frontend/` as a new top-level directory (sibling to `app/`,
`infra/`, `docs/`), via `create-next-app` (App Router, TypeScript,
Tailwind, no `src/` directory) and `shadcn init`. Two real choices came
up mid-setup that weren't fully anticipated in the original plan:

1. **Component primitive library: Base UI, not Radix.** Shadcn's CLI now
   asks which headless primitive library to build on — Base UI, React
   Aria, or Radix — and marks Base UI "(Recommended)." Took the tool's
   own current recommendation rather than defaulting to Radix from
   memory, the same "trust real, current evidence over training data"
   instinct this project has applied to Azure quirks all along, now
   applied to frontend tooling for the first time.
2. **Custom design tokens, not a bundled preset.** Shadcn's `init`
   offers named preset bundles (color palette + font pairing already
   decided for you). Rejected all of them in favor of "Custom," per the
   `frontend-design` skill's explicit warning against accepting a
   pre-built aesthetic identity before making any deliberate choice —
   picked a base color, an Indigo-adjacent accent, and the "Mira" type
   style deliberately, through Shadcn's own visual builder rather than
   guessing at a name.

## A real incident: Base UI doesn't have `asChild`
`AGENTS.md`, a file this Next.js version generates automatically,
explicitly warns that framework/library APIs may differ from training
data and to check `node_modules`'s own docs before writing code. That
warning turned out to be concretely true, not boilerplate caution:
writing `<DropdownMenuTrigger asChild><Button>...</Button></DropdownMenuTrigger>`
(the standard Radix composition pattern) produced a real hydration
error — `<button> cannot be a descendant of <button>` — because Base
UI has no `asChild` prop at all. Confirmed directly from its installed
TypeScript types (`MenuTriggerProps` has no `asChild`; the actual
composition mechanism is a `render` prop accepting a `ReactElement` or
render function). `asChild` was silently ignored as an unrecognized
prop, so Base UI's own trigger rendered its native `<button>` *and*
kept the child `Button` (also a `<button>`) nested inside it. Fixed in
three places (`theme-toggle.tsx`'s `DropdownMenuTrigger`,
`navbar.tsx`'s `SheetTrigger` and `SheetClose`) by switching to
`render={<Button>...</Button>}`.

## Reasoning
The Base UI/Radix mismatch was caught by actually running the app and
reading a real hydration error in the browser — not by reading the
component source, which looked plausible either way. This is the same
evidence-first debugging pattern this project has used for every other
real incident, now proven to generalize to frontend tooling, not just
Azure infrastructure. Checking `node_modules`'s bundled docs directly
(rather than relying on training data) also caught, separately, that
`fetch()` requests are *not* cached by default in this Next.js
version — the opposite of older Next.js versions' well-known default —
which avoided writing an unnecessary, misleading `cache: "no-store"`
option into `lib/api.ts`.

## Consequences
- Every future Shadcn component this project adds needs the same
  `render`-not-`asChild` treatment if it wraps another interactive
  element — a pattern now understood, not something to rediscover.
- The frontend's actual visual identity (Base color: Neutral, Theme:
  Indigo, Style: Mira) is a real, deliberate choice made through
  Shadcn's own builder, not a name picked blind — recorded here so a
  future session doesn't have to reconstruct the reasoning from the
  generated `components.json` alone.
- `AGENTS.md`'s warning about checking local docs before trusting
  training data is now a proven-necessary habit for this specific
  fast-moving corner of the stack, not just a generic disclaimer.

## Scale, cost, and on-call reality
None of this changes at scale — it's a one-time API-shape lesson, not
an architectural trade-off. The real ongoing cost is discipline: this
project is now on Next.js 16 and Base UI, both genuinely newer than
most public tutorials and most of what's in general AI training data.
Every future frontend chunk should default to checking
`node_modules/next/dist/docs/` or the installed package's own type
definitions before writing composition-heavy code, rather than
assuming a pattern from memory — the cost of skipping that check is a
real, if quick-to-fix, bug each time, as this session demonstrated
twice in one sitting.
