# Team Brainstorm: Multi-Repo Impact Analysis

*The pizza team gathers around the whiteboard. Priya draws two boxes — "MONOLITH (1 repo, 500+ csproj)" and "MICROSERVICES (N repos)" — with arrows between them.*

---

## Day One

**Priya** *(Architect)*: Let's frame the problem before jumping to solutions. Today scatter operates on a single filesystem tree — one `--search-scope`. That works for the monolith. But the target-state architecture means impact now crosses repo boundaries. There are really three distinct problems here:

1. **Intra-monolith** — already solved, this is what scatter does today
2. **Monolith-to-microservice** — "I changed something in the monolith, which microservices call this?"
3. **Microservice-to-microservice** — "I changed Service A's API, who breaks?"

And a sub-problem: the coupling between these systems isn't via `ProjectReference` anymore — it's via **HTTP contracts, message contracts, and database schemas**.

---

**Marcus** *(Principal)*: Right. And let's be real about the local checkout situation. 500+ projects in the monolith is already big but it's one `git clone`. The microservices are the problem — if you have 50 microservices in 50 repos, nobody's cloning all of them. So we need two modes:

- **"I have everything locally"** — federated scan across multiple local paths
- **"I don't have everything locally"** — work from a pre-built index

---

### Approach 1: Multi-Root Local Analysis

**Tomás** *(Senior)*: The simplest thing that could work: let scatter accept multiple `--search-scope` paths. Instead of one root, give it a list. The graph builder walks all of them and builds a unified `DependencyGraph`.

```
scatter --target-project ./monolith/MyLib/MyLib.csproj \
        --search-scope ./monolith \
        --search-scope ./microservice-orders \
        --search-scope ./microservice-payments
```

The graph engine already doesn't care where the `.csproj` files live — `ProjectNode.path` is absolute. We'd just need to make the file scanner iterate multiple roots.

**Devon** *(Mid-Senior)*: That's a good starting point but it won't find cross-service dependencies. If `microservice-orders` calls `microservice-payments` via HTTP, there's no `ProjectReference` to follow. We'd need new edge types.

---

### Approach 2: Contract-Based Edge Discovery

**Fatima** *(Mid-Senior)*: This is the real problem. Between microservices, the "dependency" isn't a project reference — it's a **contract**. I see three contract types at WEX:

| Contract Type | Producer Side | Consumer Side |
|---|---|---|
| **REST/HTTP API** | Controller actions, Swagger/OpenAPI specs | HttpClient calls, generated clients |
| **Message/Event** | Message publishers, event schemas | Message handlers/consumers |
| **Database** | Sproc definitions, table schemas | EF contexts, raw SQL, sproc calls |

Scatter already handles the database case (sproc scanner). We need the same idea for HTTP and messaging.

**Jake** *(Mid-Level)*: For REST APIs specifically — if teams are generating OpenAPI specs (or we can extract them from controllers), we can build a **contract registry**. The scanner finds:
- **Producers**: `[ApiController]` classes, `[HttpGet]`/`[HttpPost]` routes
- **Consumers**: `HttpClient` calls, Refit interfaces, generated API client classes

If Service A has a controller at `/api/orders/{id}` and Service B has an `HttpClient` hitting `/api/orders/`, that's an edge.

**Anya** *(Senior)*: I like this, but string-matching URLs is fragile. The more reliable approach: if teams use **generated clients** (NSwag, Kiota, Refit), the generated client class name or namespace gives you a deterministic link. Scan for generated client imports the same way we scan for `using` statements today.

---

### Approach 3: The Contract Index (No Full Checkout)

> **Constraint discovered after Day One**: We have no control over the microservice teams and cannot ask them to create or publish manifests. The manifest concept still applies, but **we must generate them ourselves** from source we can access.

**Priya**: Now the harder question — how do we do this *without* checking out every microservice? Marcus, you called this the index approach.

**Marcus**: Here's the revised idea: **scatter generates manifests by scanning microservice repos itself** — either via shallow clone or the Azure DevOps API. The manifest schema describes what a service exposes and consumes:

```json
{
  "service": "orders-api",
  "repo": "wex/microservice-orders",
  "version": "2.4.1",
  "exposes": {
    "http_endpoints": [
      {"route": "GET /api/orders/{id}", "response_type": "OrderDto"},
      {"route": "POST /api/orders", "request_type": "CreateOrderRequest"}
    ],
    "events_published": ["OrderCreated", "OrderCancelled"],
    "sprocs_owned": ["dbo.sp_GetOrder", "dbo.sp_InsertOrder"]
  },
  "consumes": {
    "http_clients": [
      {"service": "payments-api", "routes": ["POST /api/payments"]}
    ],
    "events_subscribed": ["PaymentCompleted"],
    "sprocs_called": ["dbo.sp_GetCustomer"]
  }
}
```

**Kai** *(Junior-Mid)*: So scatter builds the graph from manifests instead of scanning source? That's a fundamentally different mode. You'd have:
- `scatter --scan` (today's behavior, local filesystem)
- `scatter --from-index ./index-dir/` (graph from pre-built contracts we generated)
- And a hybrid: scan your local repos + augment with the index for everything else

**Tomás**: The hybrid is the killer feature. Developer changes something in the monolith, scatter scans the monolith locally for direct impact, then checks the index to find microservices that consume the affected types/sprocs/endpoints — all without cloning those microservice repos.

---

### Approach 4: API Contract Change Detection

**Devon**: Let's get specific about the UI/BFF case. A BFF (Backend-for-Frontend) exposes endpoints the UI calls. If I change a BFF response shape, how does scatter tell me which UI components break?

**Sam** *(Mid-Level)*: The pattern I've seen work:

1. **BFF side**: Extract the response DTOs from controller return types. Scatter already does type extraction — we'd add a scanner that maps `controller route → return type → DTO shape`.

2. **UI side**: If the UI uses TypeScript, the generated API client types are the contract. Scan the TS types for matches against the BFF's DTOs.

3. **Diff-based**: The really useful mode is — "I changed `OrderDto.cs`, which BFF endpoints return this type, and which UI components consume those endpoints?" That's a two-hop traversal on the graph:
   ```
   OrderDto → BFF Controller (returns OrderDto) → UI Component (calls that endpoint)
   ```

**Fatima**: And the breaking-change detection should be **structural**, not just "did this file change." If I *add* a field to `OrderDto`, that's probably non-breaking. If I *remove* or *rename* a field, that's breaking. We could do a simple structural diff of DTO classes between branches.

**Marcus**: Let's not over-scope that. Start with "this DTO changed, here's who uses it" and let the human decide if it's breaking. Schema-level diffing is a V2 feature.

---

### Day One Architecture (Revised)

**Priya** *(drawing on the whiteboard)*:

```
┌──────────────────────────────────────────────────┐
│                  scatter CLI                      │
│   --search-scope (multiple local paths)           │
│   --remote-org (scan DevOps org repos via API)    │
│   --index-dir (cached contract index)             │
├──────────────────────────────────────────────────┤
│              Unified DependencyGraph              │
│                                                   │
│  Edge types:                                      │
│   • project_reference  (existing)                 │
│   • namespace_usage    (existing)                 │
│   • type_usage         (existing)                 │
│   • sproc_shared       (existing)                 │
│   • nuget_dependency   (NEW)                      │
│   • http_contract      (NEW)                      │
│   • event_contract     (NEW)                      │
│   • generated_client   (NEW)                      │
├──────────────────────────────────────────────────┤
│              Scanners                             │
│   FileScanner      (existing)                     │
│   TypeScanner      (existing)                     │
│   SprocScanner     (existing)                     │
│   NuGetScanner     (NEW - PackageReference edges) │
│   ApiScanner       (NEW - controllers, routes)    │
│   ClientScanner    (NEW - HttpClient, Refit)      │
│   EventScanner     (NEW - pub/sub patterns)       │
│   OpenApiLoader    (NEW - swagger/openapi specs)  │
├──────────────────────────────────────────────────┤
│              Remote Scanner (NEW)                 │
│   DevOpsRepoEnumerator  (list repos in org)       │
│   RemoteFileScanner     (fetch specific files)    │
│   ContractExtractor     (controllers, csproj,     │
│                          generated clients)        │
│   IndexCache            (local JSON cache with    │
│                          staleness/TTL)            │
├──────────────────────────────────────────────────┤
│              Index Builder                        │
│   scatter index build  (our pipeline, our artifact)│
│   JSON index per service                          │
│   No team cooperation required                    │
└──────────────────────────────────────────────────┘
```

---

## Day Two: The Debate

*Priya has yesterday's whiteboard photo projected. The team has coffee. Devon has espresso.*

---

**Priya**: Yesterday we landed on a revised approach — we generate the index ourselves, no asks of other teams. Today I want us stress-test that. Poke holes. What breaks? What's harder than it looks? And let's get concrete on what the code actually needs to change. Marcus, start us off.

---

### Debate 1: The Graph Model — One Graph or Two?

**Marcus**: I spent last night staring at `graph_builder.py`. The function signature tells the story of our problem:

```python
def build_dependency_graph(search_scope: Path, ...)
```

One `Path`. Everything flows from that single root. The `.csproj` discovery, the `.cs` file mapping, the reverse index — all of it assumes one tree. Before we talk about remote scanning or API contracts, we need to answer: **what does `ProjectNode` become when the thing we're modeling isn't a `.csproj`?**

**Tomás**: Right. Look at the node:

```python
@dataclass
class ProjectNode:
    path: Path          # a .csproj on disk
    name: str           # the .csproj stem
    namespace: str      # derived from .csproj
    framework: str      # from .csproj
    type_declarations: List[str]
    sproc_references: List[str]
```

Every field is `.csproj`-centric. If we want to represent a microservice we scanned remotely, what's the `path`? It doesn't exist locally. What's the `name`? The repo name? The assembly name? If it has 3 `.csproj` files inside, is it one node or three?

**Devon**: I see two options:

**Option A: Keep ProjectNode, add a ServiceNode layer on top.** A microservice is a *group* of ProjectNodes. The graph has two tiers — project-level (today) and service-level (new). Cross-service edges connect at the service level, intra-service edges connect at the project level.

**Option B: Generalize ProjectNode into something more abstract.** Call it `ComponentNode`. It can represent a `.csproj`, a microservice, a UI app, whatever. Add a `component_type` field. The graph stays single-tier but nodes are polymorphic.

**Priya**: I'm going to push back on both. Option A is premature hierarchy — we'll spend weeks debating what a "service" is. Option B turns our clean data model into a grab-bag.

**Anya**: Neither. One graph. The graph already has `edge_type` for filtering. We don't need separate graphs — we need better edge types and a way to filter by them. The `DependencyGraph` class is a pure data structure with good query methods. Splitting into two graphs means every traversal algorithm has to know about both. That's worse.

**Marcus**: And `DependencyEdge.weight` already captures confidence. `project_reference` edges get weight 1.0, `http_contract` edges get 0.6. The graph can represent both levels with different confidence, and consumers of the graph can filter by confidence threshold.

**Tomás**: I'm with Anya and Marcus. One graph. But we do need to handle the `path` problem for remote nodes. A `ProjectNode` for a service we scanned remotely has no local path.

**Devon**: Make `path` `Optional`. If it's a remote node, path is `None`. Add a `source` field — `"local"` vs `"remote:wex/microservice-orders@main"`. That's the minimum change.

> **Decision**: One unified graph. `ProjectNode.path` becomes `Optional[Path]`, add `source: str` field. No `ServiceNode` for now — a service is just a group of `ProjectNode`s that happen to share a repo.

---

### Debate 2: NuGet Contract Packages — The Quiet Win

**Kai**: Can I ask the dumb question? Yesterday we said NuGet contract packages are the highest-signal approach. But do WEX's microservices actually *do* that? Like, is there a `OrdersService.Contracts` NuGet package on the internal feed?

**Marcus**: That's not a dumb question — it's THE question. If they don't, we're back to pattern-matching controller files.

**Jake**: Even if not all teams do it, some .NET microservice templates include a `*.Contracts` or `*.Client` project by convention. And even without an explicit contracts package, if Service A depends on a NuGet package that is *built from* Service B's repo, that's a signal. We can map NuGet package names back to repos — the internal feed has metadata about which pipeline published each package.

**Fatima**: So the approach is:
1. Query the internal NuGet feed for all packages and their source repos
2. For each `.csproj` in the monolith, check `<PackageReference>` for any internal packages
3. Those package references are cross-service edges

That requires zero source scanning of microservices. Just NuGet feed metadata plus monolith `.csproj` parsing, which we already do.

**Tomás**: That's beautiful because it's *data we already have*. The `.csproj` parser in `project_scanner.py` already reads `<PackageReference>`. We just don't do anything with internal packages today — we only look at `<ProjectReference>`. Adding a `nuget_dependency` edge type is a small diff.

**Anya**: But it only gives you the dependency direction. "The monolith consumes Service B's contracts package." It doesn't tell you *which endpoints or types* it uses from that package. You still need controller scanning if you want to know whether a specific endpoint change breaks anything.

**Marcus**: True. But "this change is in Service B, and the monolith depends on Service B's contracts package" is already 10x more than we have today, which is nothing. Ship that, then add endpoint-level precision later.

> **Decision**: NuGet feed scanning promoted to Phase 2. Highest signal, lowest effort. Requires only `.csproj` parsing (already done) plus NuGet feed metadata.

---

### Debate 3: Remote Scanning Mechanics

**Priya**: Let's talk about the DevOps API approach for controller scanning. Fatima, you suggested we can fetch just `*Controller.cs` files without cloning. Walk us through the reality.

**Fatima**: The Azure DevOps REST API has two relevant endpoints:
- **Items API** — list files in a repo by path pattern, fetch file contents
- **Search API** — full-text code search across repos

For controller scanning, we'd:
1. List all repos in the org via the API
2. For each repo, search for files matching `*Controller.cs`
3. Fetch those files' contents
4. Run our existing regex patterns to extract `[HttpGet("/api/...")]` routes and return types

**Jake**: Rate limits are the concern. If there are 200 microservice repos and we're hitting the API for each one, that's a lot of calls. And the search API has fairly strict rate limits — I've seen 429s at around 100 requests per minute.

**Devon**: Which is why the index-and-cache approach matters. We don't scan every time. We scan once, cache the results, and re-scan on a schedule or on-demand. The cache is just JSON files — one per repo — that we store locally or in a shared location.

**Kai**: How does that interact with the existing graph cache in `graph_cache.py`? We already have `FileFacts` and `ProjectFacts` for incremental rebuilds. Could we extend that to cover remote repos?

**Tomás**: Different concern. The existing cache is for *performance* — avoid re-parsing unchanged files on the local filesystem. The remote index is for *reachability* — knowing what exists in repos we don't have locally. I'd keep them separate. The remote index is input to the graph builder, not part of the graph cache.

> **Decision**: Remote scanning via Azure DevOps API, not shallow clones. Targeted file fetching (`*Controller.cs`, `*.csproj`) with local JSON cache per repo. Separate from the existing graph cache. Our pipeline runs `scatter index build` on a schedule.

---

### Debate 4: Multi-Root — Is It Actually Trivial?

**Sam**: I want to come back to multi-root `--search-scope` because that's Phase 1 and I want to make sure it's actually trivial. Looking at `build_dependency_graph`:

```python
all_csproj = find_files_with_pattern_parallel(search_scope, "*.csproj", ...)
all_cs = find_files_with_pattern_parallel(search_scope, "*.cs", ...)
```

To support multiple roots, we'd run these for each root and concatenate the results. But there's a subtlety — `_map_cs_to_project` uses a directory index to find the nearest `.csproj` parent. If two roots have unrelated directory trees, that's fine. But if someone passes overlapping roots (like `./monolith` and `./monolith/SubProject`), we'd get duplicates.

**Devon**: Deduplicate by resolved path. Run the file discovery per-root, merge into a `set()` by absolute path, then proceed as today. Cheap insurance.

**Tomás**: And the signature change is:

```python
def build_dependency_graph(
    search_scopes: List[Path],  # was: search_scope: Path
    ...
)
```

With a backward-compat wrapper that wraps a single `Path` into `[path]`. The rest of the function is unchanged — it already works on flat lists of `.csproj` and `.cs` files. The only thing that changes is how those lists are built.

**Anya**: We need a test for overlapping roots. And a test for roots on different filesystems (if someone has the monolith on one drive and microservices on another).

> **Decision**: Confirmed trivial. Change `search_scope: Path` to `search_scopes: List[Path]`, deduplicate by resolved path, backward-compat wrapper for single-path usage.

---

### Debate 5: Non-.NET Services and the Long Game

**Marcus**: Let me throw a curveball. We've been talking about C# the entire time. But WEX's microservices — are they all .NET? What if some are Node, Java, Go?

**Priya**: Good question. For Phase 1-5, assume .NET. That's the monolith and that's the majority of microservices. But the architecture shouldn't *prevent* non-.NET support. The `ApiScanner` should be interface-based — "give me endpoints from this directory" — with a C# implementation first and room for others.

**Fatima**: And for non-.NET services, the NuGet approach doesn't help, but OpenAPI specs do. If a Go service publishes a Swagger spec, we can still build contract edges from it. The spec is language-agnostic.

**Jake**: OpenAPI parsing is a well-solved problem — there are Python libraries for it. If a repo has a `swagger.json` or `openapi.yaml`, we can extract every endpoint, request type, and response type without understanding the source language at all.

**Tomás**: That's the right long-term play. Contracts are the API boundary, not the implementation language. Short term: scan .NET controllers. Long term: consume OpenAPI specs. Same edge type in the graph either way.

> **Decision**: Assume .NET for Phases 1-5. Design scanners as interfaces for future language support. OpenAPI spec parsing added to roadmap as a language-agnostic alternative.

---

### Confidence-Layered Edge Strategy

**Tomás**: Regardless of how we discover contract edges, we should layer them by fidelity:

```
Layer 1: NuGet contract packages     (highest fidelity, .csproj only)
Layer 2: Generated client detection   (scan for NSwag/Refit/Kiota output)
Layer 3: Controller route extraction  (scan *Controller.cs files)
Layer 4: HttpClient URL matching      (lowest fidelity, fragile)
```

Each layer adds edges with decreasing confidence. The graph already has a `weight` field on `DependencyEdge` — use it.

---

## Decisions Summary

1. **One graph, not two.** Keep `DependencyGraph` unified. New edge types (`nuget_dependency`, `http_contract`, `event_contract`) with confidence weights to distinguish from high-fidelity source-scanned edges.

2. **`ProjectNode` evolves minimally.** Make `path` Optional, add `source: str` field (`"local"` or `"remote:{repo}@{ref}"`). No `ServiceNode` for now — a service is just a group of `ProjectNode`s that happen to share a repo.

3. **Multi-root is Phase 1.** Change `search_scope: Path` to `search_scopes: List[Path]`. Deduplicate by resolved path. Backward-compat wrapper for single-path usage.

4. **NuGet feed scanning is Phase 2.** Highest-signal, lowest-effort cross-service edge — requires only `.csproj` parsing we already do plus NuGet feed metadata. No source scanning of remote repos needed.

5. **Controller scanning is Phase 3.** Build an `ApiScanner` that extracts routes and return types from `*Controller.cs` files. Works on local source first (monolith internal APIs), extend to remote files later.

6. **Remote scanning goes through Azure DevOps API**, not shallow clones. Targeted file fetching (`*Controller.cs`, `*.csproj`) with local JSON cache per repo. Separate from the graph cache. Our pipeline runs `scatter index build` on a schedule.

7. **OpenAPI specs are the language-agnostic long play.** If a repo has `swagger.json`/`openapi.yaml`, parse it instead of scanning source. Same edge types in the graph.

## Open Questions

### For Product/Direction

1. **Primary user scenario**: When we ship this, who runs it first — a dev working on the monolith who wants to know "did I break a microservice?", or a platform team trying to map the full dependency landscape? The answer changes what we optimize for (speed of a single query vs. completeness of the graph).

2. **Accuracy threshold**: If NuGet scanning finds 70% of cross-service dependencies but misses the rest, is that useful or misleading? Are false negatives (missed dependencies) acceptable if we're clear about coverage, or will people lose trust?

3. **Direction of impact**: Is the monolith-to-microservice direction more urgent than microservice-to-microservice? If the monolith is the thing changing most frequently and microservices are more stable, we should optimize for "change in monolith → impact on microservices" first. Is that the right read?

### For Platform/DevOps

4. **NuGet feed access**: What does the internal NuGet feed look like? One feed or many? Can we query it programmatically (NuGet API, Azure Artifacts REST API)? Does the feed metadata include which repo/pipeline published each package? That's the link we need for `nuget_dependency` edges. *(Blocker for Phase 2)*

5. **Microservice repo conventions**: Do microservice repos follow any naming or structural conventions? (e.g., repo names like `wex-orders-api`, a standard `src/` layout, a shared project template) Anything predictable reduces how much we need to scan.

6. **OpenAPI/Swagger specs**: Do any microservices publish OpenAPI specs? Are they checked into the repo (`swagger.json`), generated at build time, or published to an API gateway (like Azure API Management)? If there's a gateway, can we query it for the spec catalog?

7. **Azure DevOps API access**: Do we have a service account or PAT with read access across all microservice repos in the org? Any repos locked down with different permissions? *(Blocker for Phase 4)*

### For Architecture

8. **Inter-service communication patterns**: How do microservices talk to each other? REST over HTTP? gRPC? Both? What messaging — Azure Service Bus? Event Grid? Kafka? Are there shared databases between the monolith and microservices, or is each microservice on its own database? *(Determines which scanners we build and in what order — blocker for Phase 3 prioritization)*

9. **Shared contracts pattern**: Do any teams publish `*.Contracts` or `*.Client` NuGet packages with DTOs and client interfaces? Or does each consuming team write their own HTTP clients? If it's the latter, we need the controller scanner much sooner. *(Directly affects Phase 2 value — if no contract packages exist, Phase 2 becomes "query the NuGet feed for package→repo mappings" which is a different and harder problem)*

10. **BFF landscape**: How many BFFs exist? Do they live in the monolith repo or in their own repos? Do the UI teams use generated TypeScript clients (e.g., from NSwag/openapi-generator), or hand-written fetch calls? *(Deferred but shapes Phase 8 scope)*

### About the Monolith

11. **Internal HTTP calls**: Are there internal HTTP calls within the monolith? Does Project A in the monolith call Project B's controller via `HttpClient` even though they're in the same repo? If so, that's a contract edge hiding inside what looks like a monolith — and we need the API scanner even before we go multi-repo. *(Could reprioritize Phase 3 ahead of Phase 2)*

12. **Project breakdown**: Of those 500+ `.csproj` files, how many actually represent deployable services (APIs, workers, batch jobs) vs. shared libraries (class libraries, utilities)? This affects how we think about the nodes — not every project is a meaningful blast radius boundary.

### Internal Design Questions

13. **Service identity**: When we create a remote `ProjectNode`, what's the canonical name? Repo name? Assembly name? We need a stable key that won't collide with monolith project names.

14. **Cache invalidation**: How does the remote index know when a microservice's API has changed? Poll on a schedule? Webhook from their CI/CD? Or just rebuild nightly and accept staleness?

## Revised Roadmap

| Phase | What | Key Detail |
|---|---|---|
| **1** | Multi-root `--search-scope` | Confirmed trivial — signature change + dedup |
| **2** | NuGet feed → `nuget_dependency` edges | Highest signal, lowest effort |
| **3** | `ApiScanner` for controller routes (local) | .NET controllers first, interface-based for future languages |
| **4** | Remote repo scanning via DevOps API + cache | Our pipeline, our artifact, no team cooperation |
| **5** | OpenAPI spec parsing | Language-agnostic contract import |
| **6** | Generated client scanner (NSwag/Refit) | Higher-fidelity HTTP contract matching |
| **7** | Event/message scanner | Async integration patterns |
| **8** | UI/BFF + TypeScript | Separate design session needed |

---

**Marcus**: We should prototype Phase 1 and 2 together. Multi-root is maybe a 2-hour change. NuGet scanning is a day. We could have a working demo inside a week that shows the monolith graph augmented with cross-service NuGet edges.

**Tomás**: Agreed. Small increments, ship something, learn.

**Sam**: Can I name the feature? "Multi-scope" for Phase 1, "Contract edges" for the umbrella of Phases 2-7?

**Priya**: Works for me. Let's build it.

---

## Leadership Evaluation: Alignment with Product Vision

*Priya and Marcus evaluate the multi-repo initiative against the product definition (docs/PRODUCT_DEFINITION.md).*

---

### Priya Chandrasekaran, Architect

The product vision statement is clear:

> *"Scatter evolves from a developer CLI utility into a dependency analysis platform — accepting work requests as input and producing scoped impact assessments, and supporting modernization planning with actual dependency data and AI analysis."*

The subtitle of the product definition is **"AI-Powered Monolith Analysis & Decomposition."** That word — *decomposition* — is doing a lot of work. It implies scatter exists to help the monolith break apart. But here's the tension: **you can't plan a decomposition if you can't see what's on the other side of the boundary.**

Today, scatter answers "what depends on this thing *inside the monolith*?" The multi-repo initiative extends that to "what depends on this thing *across the entire platform*?" That's not a new product — it's the natural completion of the existing vision. The product definition even names the scenario explicitly:

> *"We want to extract the portal module into a target-state service — but we don't know everything that depends on it or shares its database."*

Right now scatter can tell you what depends on the portal module *within the monolith*. But once that module IS extracted — once it's a microservice in its own repo — scatter goes blind. The thing we're helping teams *plan* creates an environment we can't *analyze*. That's a contradiction we need to resolve, and this initiative resolves it.

**Assessment: Strong alignment.** Multi-repo support isn't scope creep — it's the vision's natural second act. The monolith is shrinking. The microservices are growing. If scatter only sees one side, it becomes less valuable every quarter.

**Concern about focus.** The product definition has a clear priority hierarchy:

1. Understand the monolith
2. Analyze work requests (CSE/SOW impact)
3. Support extraction planning

Multi-repo is primarily relevant to #3 and partly to #1 and #2. We're currently in Phase 4.5 (credibility & adoption), with CI/CD integration (Phase 5) promoted as the next priority. Multi-repo work should not displace either of those. **The danger is building capability nobody uses because we haven't finished the adoption story for the monolith-only features.**

**Recommendation**: Sequence multi-repo *after* Phase 5 (CI/CD integration). By then, scatter has users, those users will be asking "but what about the microservices?", and the demand will be organic rather than speculative.

---

### Marcus Webb, Principal Engineer

Priya's right about alignment but I want to challenge something. The product definition identifies three trigger scenarios:

| Scenario | Multi-repo relevant? |
|---|---|
| **CSE arrives** — "this sproc is used by 4 apps, which teams?" | **Yes** — those 4 apps might not all be in the monolith anymore |
| **Modernization initiative** — "extract the portal module" | **Yes** — need to see both sides of the extraction boundary |
| **Feature branch in progress** — "what's my blast radius?" | **Partially** — today this is monolith-only, but increasingly changes touch microservices too |

So it's relevant to all three triggers, not just extraction planning. That's stronger alignment than Priya suggested.

But here's what concerns me: **the value proposition table in the product definition measures scatter against "manual" (senior devs tracing code for days)**. That comparison stays valid whether scatter sees one repo or twenty. The multi-repo work doesn't change the core value prop — it extends the *coverage* of it. That means:

- **If scatter isn't adopted yet**: multi-repo is premature. You're extending coverage of a tool nobody's using.
- **If scatter IS adopted and people are hitting the boundary**: multi-repo is the highest-value next feature, because users are literally telling you "I need to see past the monolith."

**Where are we on adoption?** The product definition says we're in Phase 4.5 — "Credibility & adoption: fix broken features, graph integration, Claude skills, pipeline shortcuts." That tells me we're still *earning trust*. Multi-repo support before trust is established is building the second floor before the first floor is load-bearing.

**Assessment: Aligned but premature for the current phase.**

Here's what I'd actually do:

1. **Ship Phase 1 (multi-root `--search-scope`) now.** It's a 2-hour change. It costs nothing and unblocks developers who happen to have multiple repos checked out locally. No new scanners, no remote APIs, no index infrastructure. Just remove the single-path limitation. This is a no-regret move.

2. **Defer Phases 2-8 until scatter has active users hitting the monolith boundary.** When a tech lead says "scatter showed me 4 consumers in the monolith, but I know there are microservices using this too" — *that's* the signal to build NuGet scanning and the rest.

3. **Meanwhile, capture the design work we've done.** The brainstorm doc is the design. When the time comes, we're not starting from zero. The architecture decisions (one graph, confidence-layered edges, DevOps API scanning) are ready to implement.

**One exception**: If the answer to Open Question #11 is "yes, there are internal HTTP calls within the monolith" — then the API controller scanner (Phase 3) is actually a monolith feature, not a multi-repo feature. It would improve scatter's existing coverage of the monolith. That could justify building it sooner.

---

### Joint Recommendation

| Action | Timing | Rationale |
|---|---|---|
| Ship multi-root `--search-scope` | **Now** (Phase 4.5 scope) | No-regret, 2-hour change, backward-compatible |
| Investigate Open Question #11 (internal HTTP calls in monolith) | **Now** | If yes, API scanner is a monolith feature, not multi-repo |
| NuGet scanning, remote scanning, contract edges (Phases 2-8) | **After Phase 5 ships and scatter has active users** | Don't extend coverage before adoption |
| Keep the design doc current | **Ongoing** | So we can move fast when demand arrives |

**The bottom line**: The multi-repo vision is right. The product definition supports it. The timing question is whether we've earned the right to build it yet, or whether we're solving tomorrow's problem before finishing today's. Get the monolith story bulletproof first, then extend.
