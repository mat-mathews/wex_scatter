# Focused Index Brainstorm — Conversation Record

**Date:** 2026-03-19
**Participants:** Mat + team personas (Priya, Marcus, Tomas, Fatima, Sam)

---

## Context

At WEX, the monolith contains multiple portals (admin, employer, consumer) and apps
like CDEX (a data exchange API). They are interconnected but each has its own solution
with projects. When a SOW comes in, the team may know it's work in the admin and
employer portals — but maybe it touches CDEX too.

**Question:** How do we focus the codebase index for the LLM initially, so it's tight
enough to be useful but broad enough to discover non-obvious blast radius?

---

## Initial Options Considered

### Option A: Solution-scoped index
`--solutions Billing.sln,Portal.sln` limits the index to only projects declared in
those `.sln` files. Piggybacks on Initiative 9's solution parsing.

### Option B: Project-pattern filter
`--index-filter "GalaxyWorks.*"` glob limits which projects appear in the index.
Simple, no `.sln` parsing needed.

### Option C: Two-pass refinement
Pass 1: LLM reads SOW + full index, returns candidate projects. User picks which
matter. Pass 2: tight index from just those, re-analyze with deeper detail.

### Option D: Explicit project list
`--scope-projects P1,P2,P3` — user specifies exactly which projects. Most precise,
least discovery.

---

## Team Brainstorm

**Priya** *(leaning back, thinking)*: Let's frame the problem before we jump to
solutions. The real question isn't "how do we filter the index" — it's "how do we
balance precision with discovery?" The team *thinks* it's admin and employer. But the
whole point of scatter is to find what you *didn't* know you'd hit. If we let users
aggressively scope the index, we defeat the purpose. If we don't scope it, the LLM
drowns in noise from 200 projects.

**Marcus**: Right. And in the WEX monolith, "admin portal" isn't one project — it's
probably 30. Employer portal, another 30. CDEX, maybe 15. So the question is: can we
give the LLM enough context to *discover* CDEX without shipping the entire 200-project
index?

**Tomas**: Two-tier index. That's the answer. Tier 1 is a *solution-level* summary —
just solution names, their project counts, and a brief description of what they own.
Tiny. Maybe 20 lines for the whole monolith. Tier 2 is the full project-level index,
but only for the solutions the LLM (or user) selects from Tier 1.

**Priya**: I like that. It mirrors how the team actually thinks about it. Nobody says
"we're touching `WEX.Admin.Portal.Security.OAuth`" — they say "we're touching the
admin portal." The solution is the natural unit of scoping.

**Fatima**: But who builds the Tier 1 descriptions? If it's just solution names like
`AdminPortal.sln`, maybe the LLM can infer enough. But what about `CDEX.sln` — would
the LLM know that's a data exchange API from the name alone? Some solution names are
cryptic. `GWS.Core.sln`. What's that?

**Marcus**: Good point. Two options: either we auto-generate descriptions from the
projects inside each solution — "contains: DataExchangeController, CDEXClient,
ExchangeJobRunner" — just the top N most distinctive types. Or we let the user
maintain a lightweight manifest. I'd vote auto-generate, with an optional override file.

**Tomas**: Auto-generate. Nobody maintains manifests. Here's what I'd put in Tier 1
per solution:

```
SOL:AdminPortal projects:34 types:PortalController,AdminUserService,ConfigManager,... sprocs:sp_GetAdminConfig,sp_UpdateUserRole,...
SOL:EmployerPortal projects:28 types:EmployerDashboard,BenefitPlanService,...
SOL:CDEX projects:12 types:DataExchangeController,CDEXClient,ExchangeJobRunner,...
```

Just the solution name, project count, and top 5-10 most distinctive type names. The
LLM reads the SOW, reads this tiny summary, and says "this SOW touches AdminPortal,
EmployerPortal, and — interesting — CDEX because the SOW mentions 'enrollment data
feeds' and CDEX has `DataExchangeController`."

**Priya**: That's the key insight. The type names in the solution summary act as
*semantic anchors*. The LLM doesn't need to see every project — it needs enough signal
to recognize domain overlap.

**Fatima**: What about the edges *between* solutions though? That's where the surprises
live. If AdminPortal has 6 projects that reference CDEX projects, that's a strong
signal. The Tier 1 summary should include cross-solution coupling. Something like:

```
SOL:AdminPortal projects:34 refs->EmployerPortal(3) refs->CDEX(6) refs->GWS.Core(34)
```

So even before the LLM reads a single type name, it can see: "AdminPortal is heavily
coupled to CDEX — if the SOW touches admin, CDEX is probably in blast radius."

**Marcus**: That's the money feature right there. Cross-solution edge counts are cheap
to compute from the graph — we already have `ProjectReference` edges. Just aggregate
them by solution membership. And it answers the exact question Mat posed: "the team
knows it's admin and employer, but does it touch CDEX?"

**Tomas**: So the flow becomes:

1. **Build solution summaries** from the graph (auto-generated, no user input needed)
2. **LLM Pass 1** — SOW + solution summaries -> LLM picks relevant solutions
   (+ confidence per solution)
3. **Build focused index** — full project-level index, but only for selected solutions
4. **LLM Pass 2** — SOW + focused index -> extract specific `AnalysisTarget`s as today

Two LLM calls instead of one. But Pass 1 is tiny — maybe 500 tokens of context. And
Pass 2 gets a clean, focused index instead of the kitchen sink.

**Priya**: And the user can override Pass 1. `--solutions AdminPortal.sln,EmployerPortal.sln`
skips the first LLM call and goes straight to building the focused index. Best of both
worlds — AI discovery when you want it, explicit control when you know.

**Fatima**: What if Pass 1 misses a solution? What's the failure mode?

**Marcus**: The cross-solution edges are the safety net. If the SOW says "change how
admin users authenticate" and AdminPortal refs->CDEX(6), the LLM should flag CDEX even
if the SOW never mentions data exchange. But if it doesn't — worst case is the same as
today when someone forgets to check CDEX manually.

**Tomas**: We could also add a `--discover` flag that always includes solutions with
high incoming edge counts from selected solutions. Basically: "I picked admin and
employer, but auto-include anything they're heavily coupled to." No LLM needed for
that — pure graph traversal.

**Sam**: Can I throw in a UX thought? The two-pass thing should be transparent to the
user. They run `scatter --sow "..." --search-scope .` and the output says:

```
Solutions identified (Pass 1):
  + AdminPortal (high confidence - direct match)
  + EmployerPortal (high confidence - direct match)
  ! CDEX (medium confidence - coupled to AdminPortal via 6 project refs)

Analyzing 74 projects across 3 solutions...
```

So they see *why* CDEX was included. That builds trust.

**Priya**: Good. And that brings us back to the index implementation. The change to
`codebase_index.py` is small — `build_codebase_index` already takes a `graph` and
iterates `graph.get_all_nodes()`. We'd just add an optional
`solution_filter: Optional[Set[str]]` parameter that filters nodes before building the
text. The real work is:

1. **Solution parsing** (Initiative 9, Phase 1) — need `SolutionInfo` objects
2. **Solution summary builder** — new, small module
3. **LLM Pass 1 prompt** — new task in `scatter/ai/tasks/`
4. **Wiring in `__main__.py`** — orchestrate the two passes

**Marcus**: Scope-wise, I'd ship it in two increments. First: solution filter on the
index (`--solutions` explicit flag, skip LLM Pass 1). That's useful immediately and
tests the plumbing. Second: auto-discovery via LLM Pass 1 with solution summaries.
That's the magic, but it needs the first piece working.

**Tomas**: Agreed. And the solution summary format should be dead simple — easy to
eyeball, easy to test, easy to swap out if the LLM struggles with it.

---

## Consensus

| Concept | Description |
|---------|-------------|
| **Two-tier index** | Tier 1 = solution summaries (names, top types, cross-solution edge counts). Tier 2 = full project index scoped to selected solutions |
| **Two-pass LLM** | Pass 1: SOW + Tier 1 -> select solutions. Pass 2: SOW + Tier 2 -> extract targets (as today) |
| **Cross-solution edges** | The key discovery signal — aggregate ProjectReference counts between solutions to surface non-obvious coupling |
| **User override** | `--solutions X.sln,Y.sln` skips Pass 1, goes straight to focused index |
| **Auto-include coupled** | Solutions with high edge counts from selected solutions get auto-included (graph-based, no LLM needed) |
| **Ship incrementally** | Phase 1: explicit `--solutions` filter. Phase 2: LLM-driven solution discovery |
