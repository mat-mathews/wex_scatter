# Leiden in Scatter: Using Graph Communities to Discover Legacy Monolith Seams

**Author:** Mathew Brown / Scatter concept analysis  
**Context:** Large .NET legacy monolith modernization, Strangler-pattern migration, SOW qualification, PR risk, release impact, and service-boundary discovery  
**Format:** Analysis report  
**Working thesis:** Leiden can help Scatter identify natural dependency communities inside a legacy monolith. Those communities can become candidate domain seams, migration slices, blast-radius neighborhoods, and risk-scoring units. Leiden does not magically extract microservices. It gives Scatter a map of the terrain so humans can make better architecture decisions without starting every conversation from vibes and a grep command.

---

## 1. Executive Summary

Scatter is already positioned as a deterministic dependency and risk analysis tool for large .NET codebases. It answers questions like:

1. **Before merge** — what does this change touch, and how risky is it?
2. **Before promotion** — what pipelines and downstream consumers are involved?
3. **Before SOW estimation** — how big is this really, and what parts of the system are likely involved?
4. **Before migration** — what should move together, what should stay behind an adapter, and where are the real seams?

Leiden community detection could add a powerful new layer to Scatter:

> **Community-aware architecture analysis.**

Leiden can identify natural clusters in a dependency graph: groups of files, classes, projects, namespaces, repositories, database objects, pipelines, and feature flags that are more connected internally than externally.

For a legacy monolith, that is extremely useful.

The monolith may be organized physically by old folders, legacy projects, or framework conventions, but those structures often do not reflect how the system actually behaves. The dependency graph is closer to the truth.

Leiden helps find:

- Natural functional neighborhoods
- Dense collaboration zones
- Likely domain boundaries
- Candidate microservice seams
- Migration groupings
- Blast-radius communities
- Boundary / bridge components
- Refactoring candidates
- Regression-test neighborhoods
- Pipeline-impact areas
- Architecture drift over time

The important caveat:

> Leiden does **not** discover perfect microservice domains. It discovers candidate structural communities. Scatter then has to score and explain whether those communities are good extraction candidates.

That scoring must include more than graph shape. A real microservice boundary also requires:

- Business capability alignment
- Clear ownership
- Clean data boundaries
- Limited shared database writes
- Stable API entry points
- Manageable cycles
- Known consumers
- Testability
- Deployment independence
- Release / pipeline clarity

So the right framing is not:

> “Scatter uses Leiden to generate microservices.”

The better framing is:

> “Scatter uses Leiden to discover natural neighborhoods in the monolith, then scores them as candidate domain seams and migration slices.”

That is a strong, honest, and useful modernization story.

---

## 2. Background: Why This Matters in a Legacy Monolith

Legacy monoliths usually have three different architectures:

1. **The architecture people believe exists**
2. **The architecture the folder structure suggests**
3. **The architecture the dependency graph reveals**

The third one is usually the one that matters when a PR breaks production.

In a large .NET monolith, the visible organization might be something like:

```text
/Controllers
/Services
/Managers
/Repositories
/Helpers
/Common
/Utilities
/Shared
/Legacy
/ReallyShared
/SharedButActuallyDangerous
```

That structure may tell you where a file lives, but not what it really belongs to.

A class called `ConsumerSupportService` might participate in:

- Consumer alerts
- Receipt-needed notifications
- Denied receipt logic
- Upload eligibility
- Feature flag checks
- Partner configuration
- Claims repository access
- Portal-specific behavior
- Shared API behavior

The folder name does not reveal that. The dependency graph does.

Scatter’s core opportunity is to expose the real shape of the system:

- What depends on what?
- Which changes cross boundaries?
- Which components are bridge nodes?
- Which areas are tightly connected?
- Which areas are cyclic?
- Which database objects are shared?
- Which pipelines are affected?
- Which communities are stable enough to move?
- Which ones are still monolith weather systems?

Leiden can help provide that “real shape” at a higher level than individual files or projects.

---

## 3. Graph Clustering vs Graph Decomposition

Before going deeper, it is important to separate two related but different families of graph analysis:

1. **Community detection / clustering**
2. **Structural decomposition**

They both group nodes, but they answer different questions.

### 3.1 Community Detection

Community detection asks:

> Which nodes appear to belong together based on graph connectivity?

Examples:

- Leiden
- Louvain
- Infomap
- Markov Cluster Algorithm / MCL
- Walktrap
- Label Propagation
- Spectral clustering
- Stochastic Block Models

These algorithms find “soft” communities. They infer neighborhoods based on density, flow, or probability.

In Scatter terms, this helps find:

- Functional neighborhoods
- Domain candidates
- Migration groupings
- Blast-radius regions
- Collaboration zones

### 3.2 Structural Decomposition

Structural decomposition asks:

> What hard graph structures exist?

Examples:

- Tarjan strongly connected components
- Kosaraju strongly connected components
- Gabow strongly connected components
- Bridge detection
- Articulation points
- Biconnected components
- Topological sorting
- Dominator trees

These algorithms find concrete structural facts.

In Scatter terms, this helps find:

- Circular dependencies
- Hard dependency knots
- cut points
- bridge edges
- critical shared components
- topological ordering of acyclic regions
- “you cannot separate this without breaking a cycle” areas

### 3.3 Why Tarjan Did Not Initially Appear in the Clustering List

Tarjan’s algorithm is not usually classified as a graph clustering algorithm. It is a graph decomposition algorithm.

Tarjan SCC finds **strongly connected components** in a directed graph.

A strongly connected component means:

> Every node in the component can reach every other node.

In software dependency terms:

> These modules are mutually dependent. They form a dependency cycle or knot.

That is not fuzzy clustering. It is a hard structural fact.

Example:

```text
ClaimsService -> PlanService
PlanService -> AccountService
AccountService -> ClaimsService
```

Tarjan SCC produces:

```text
{ ClaimsService, PlanService, AccountService }
```

Meaning:

> These are mechanically tangled. You cannot topologically separate them as-is.

That is different from Leiden, which might say:

> These nodes appear to belong to the same community because they are densely connected.

Both signals are useful, but they mean different things.

---

## 4. Tarjan vs Leiden: The Key Difference

This distinction is central to the Scatter story.

### 4.1 Tarjan Says: “These Things Are Mechanically Tangled”

Tarjan finds hard knots.

Useful outputs:

```text
Strongly Connected Component:
  - ClaimsService
  - PlanService
  - AccountService

Meaning:
  These components participate in a circular dependency.
  They cannot be cleanly separated without breaking or rerouting dependencies.
```

Scatter can use Tarjan to detect:

- Circular project references
- Class-level dependency cycles
- Namespace cycles
- Repository/service cycles
- Database procedure cycles
- Domain logic loops
- Areas that block migration

Tarjan is excellent for:

- Refactoring risk
- Architecture debt
- Migration blockers
- Cycle-breaking recommendations
- Topological dependency cleanup

### 4.2 Leiden Says: “These Things Appear to Belong Together”

Leiden finds natural neighborhoods.

Useful outputs:

```text
Community:
  - CommuterEnrollmentService
  - ParkingPlanElectionService
  - TransitPlanElectionService
  - EnrollmentConfirmationEmailService
  - CommuterPlanRepository

Meaning:
  These components are more connected to each other than to the rest of the graph.
  This may represent a functional neighborhood or domain candidate.
```

Scatter can use Leiden to detect:

- Cohesive functional areas
- Potential domain seams
- Migration slices
- Blast-radius communities
- Dense collaboration zones
- Boundary-crossing PRs
- Refactoring candidates
- Pipeline impact groupings

Leiden is excellent for:

- Domain discovery
- Community-aware risk
- SOW sizing
- Service boundary analysis
- Migration planning
- Architecture drift detection

### 4.3 The Practical Difference

Tarjan answers:

> What is tied in a knot?

Leiden answers:

> What lives in the same neighborhood?

Or, in legacy-monolith terms:

> Tarjan finds the sailor’s knots. Leiden finds the neighborhoods where the sailors keep tying them.

Both belong in Scatter.

---

## 5. Why Leiden Specifically?

Louvain and Leiden are both modularity-style community detection algorithms. Leiden is generally preferred because it improves on Louvain by producing better-connected communities and avoiding some pathological disconnected-community issues.

For Scatter, that matters because a bad community can mislead architecture analysis.

If the algorithm says two disconnected groups are one community, Scatter could recommend a bad migration grouping. That is exactly the kind of confident nonsense the tool must avoid.

Leiden is attractive because it is:

- Fast enough for large graphs
- Suitable for weighted graphs
- Suitable for large dependency networks
- Better behaved than Louvain
- Good at finding hierarchical community structure
- Commonly used in large-scale network analysis

For Scatter, Leiden should probably become one component of the analysis engine, not the entire engine.

Recommended combination:

```text
Tarjan SCCs
+ Leiden communities
+ boundary-node detection
+ centrality metrics
+ database coupling
+ historical co-change
+ feature flag usage
+ pipeline mapping
+ ownership metadata
+ AI-generated narrative summaries
```

The graph does the math.  
The AI explains the result.  
Humans make the architecture call.

That division of labor keeps Scatter credible.

---

## 6. What Graph Would Scatter Give to Leiden?

Leiden needs a graph. Scatter can build multiple graphs depending on the question.

### 6.1 Project-Level Graph

Nodes:

```text
.NET projects
```

Edges:

```text
ProjectReference
package references
solution membership
pipeline mapping
```

Useful for:

- High-level architecture boundaries
- Pipeline impact
- promotion risk
- service extraction planning
- project-level blast radius

Pros:

- Fast
- Easy to explain
- Good for leadership and release conversations

Cons:

- Too coarse for real code behavior
- May miss class-level coupling
- Project boundaries may already be misleading

### 6.2 Namespace-Level Graph

Nodes:

```text
Namespaces
```

Edges:

```text
using statements
type references
method call references
```

Useful for:

- Domain-ish architecture grouping
- layered architecture detection
- cross-namespace coupling
- boundary leakage

Pros:

- Better semantic signal than projects
- Easier to read than class-level graphs

Cons:

- Namespace naming may be stale
- “Common” namespaces distort results

### 6.3 Class-Level Graph

Nodes:

```text
Classes
interfaces
controllers
services
repositories
models
helpers
```

Edges:

```text
constructor injection
method calls
property usage
inheritance
interface implementation
type references
repository calls
```

Useful for:

- Detailed PR risk
- migration slice planning
- bridge node detection
- SCC detection
- refactoring analysis

Pros:

- High resolution
- Great for actual engineering use

Cons:

- Larger graph
- More noise
- Requires more parsing or static analysis

### 6.4 Method-Level Graph

Nodes:

```text
Methods
endpoints
stored procedure calls
database commands
```

Edges:

```text
calls
control flow
data access
```

Useful for:

- endpoint-level blast radius
- test targeting
- very detailed risk scoring

Pros:

- Precise
- Helpful for hard questions

Cons:

- Expensive
- Complex
- Harder to explain
- May require Roslyn or deeper analysis

### 6.5 Data-Coupling Graph

Nodes:

```text
Tables
stored procedures
repositories
database functions
services
```

Edges:

```text
reads table
writes table
calls stored procedure
updates shared entity
```

Useful for:

- microservice extraction readiness
- data ownership analysis
- shared DB coupling risk
- migration blockers

Pros:

- Critical for real microservice planning
- Prevents false-positive service boundaries

Cons:

- Requires SQL parsing / repository inspection
- Dynamic SQL can be painful
- Legacy DB usage often hides in unexpected places

### 6.6 Historical Co-Change Graph

Nodes:

```text
Files
classes
projects
tickets
SOWs
```

Edges:

```text
changed together in same PR
changed together in same ticket
changed together in same release
```

Useful for:

- functional grouping
- hidden coupling
- ownership analysis
- SOW sizing
- regression risk

Pros:

- Captures behavior static analysis misses
- Great signal for “these things move together”

Cons:

- Requires Git / PR / ticket history
- Can encode team habits, not just architecture
- Needs time-windowing

### 6.7 Multi-Layer Graph

Most powerful version:

Nodes include:

```text
Projects
files
classes
methods
repositories
stored procedures
database tables
feature flags
pipelines
SOWs/tickets
teams
```

Edges include:

```text
depends_on
calls
reads
writes
references
changed_with
owned_by
deployed_by
gated_by_feature_flag
promoted_by_pipeline
```

This allows Scatter to answer:

> This PR changes a service class in the Consumer Alerts community, touches a shared repository, reads a table also used by Claims, uses a partner feature flag, and maps to two pipelines.

That is a useful sentence.

---

## 7. Edge Weighting: The Most Important Design Choice

Leiden’s output depends heavily on edge weights.

If all edges are treated equally, the algorithm may overvalue trivial references and undervalue operationally important dependencies.

Scatter should weight edges differently based on risk and meaning.

### 7.1 Possible Edge Types and Weights

| Edge Type | Example | Suggested Weight | Reason |
|---|---|---:|---|
| Project reference | Project A references Project B | High | Strong structural dependency |
| Constructor injection | Service depends on repository | High | Runtime dependency |
| Method call | A calls B | Medium / High | Direct behavior dependency |
| Interface implementation | Class implements interface | Medium | Type-level relationship |
| Namespace usage | using Some.Namespace | Low / Medium | May be noisy |
| Shared table write | Both write same table | Very High | Microservice extraction blocker |
| Shared table read | Both read same table | Medium / High | Data coupling |
| Stored procedure call | Service calls sproc | High | Hidden domain/data dependency |
| Feature flag shared | Multiple communities use same flag | Medium | Release behavior coupling |
| Historical co-change | Files often change together | Medium / High | Practical coupling |
| Pipeline mapping | Same pipeline deploys both | Medium | Release coupling |
| Ownership overlap | Same team owns both | Low / Medium | Governance signal |

### 7.2 Risk-Weighted Graphs

Scatter may want different graphs for different questions.

#### For domain discovery

Prioritize:

```text
type references
method calls
repository calls
shared domain models
historical co-change
business naming similarity
```

#### For extraction readiness

Prioritize:

```text
shared DB writes
stored procedure calls
cycles
external dependencies
boundary nodes
runtime dependencies
```

#### For PR risk

Prioritize:

```text
changed files
changed communities
bridge nodes
call graph
downstream consumers
pipeline mapping
feature flags
```

#### For SOW estimation

Prioritize:

```text
keyword-to-community mapping
historical SOW/ticket touch patterns
domain communities
UI/service/DB layers
feature flag and pipeline impact
```

This suggests Scatter may run Leiden on multiple weighted projections of the graph, not just one universal graph.

---

## 8. Natural Functional Neighborhoods

A natural functional neighborhood is a group of components that appear to work together to deliver a behavior or capability.

Examples in a benefits / health platform context might include:

```text
Consumer Alerts / Receipts
Commuter Enrollment
Plan Design
Plan Funding
Vendor Accounts
NACHA / Payment Files
Deductible Met / Post-Deductible Enrollment
Employer Configuration
Admin Portal Settings
Consumer Web Services
```

These neighborhoods may not align perfectly with projects or folders.

That is the point.

### 8.1 Example Output

```text
Neighborhood: Consumer Alerts / Receipts

Confidence: High
Nodes: 42
Projects: 6
Key files:
  - ConsumerSupportService.cs
  - NotificationService.cs
  - ReceiptStatusRepository.cs
  - DenialCodeRepository.cs
  - DomainFeatureFlagHelper.cs

Internal edges: 118
External edges: 21
Boundary pressure: Medium
Likely domain label: Consumer Notifications / Receipt Alerts
```

### 8.2 Why This Matters

A developer working on receipt-needed alerts needs to know:

- What else lives nearby?
- What code is likely affected?
- Which services participate?
- Which repositories are involved?
- Which feature flags gate behavior?
- Which tests should run?
- Which pipelines might matter?

A natural neighborhood gives that context quickly.

Without it, the developer has to build the map manually. Every time. Usually during a deadline. While Slack gently catches fire.

### 8.3 Scatter Feature

Command:

```bash
scatter neighborhoods
```

Potential output:

```text
Detected Communities:

1. Consumer Alerts / Receipts
   Nodes: 42
   Cohesion: 0.82
   Boundary Pressure: 0.27
   Migration Readiness: Medium

2. Commuter Enrollment
   Nodes: 37
   Cohesion: 0.79
   Boundary Pressure: 0.31
   Migration Readiness: Medium-High

3. Banking / NACHA / Vendor Accounts
   Nodes: 64
   Cohesion: 0.88
   Boundary Pressure: 0.58
   Migration Readiness: Medium-Low

4. Plan Design / Configuration
   Nodes: 71
   Cohesion: 0.73
   Boundary Pressure: 0.67
   Migration Readiness: Low
```

---

## 9. Dense Collaboration Zones

A dense collaboration zone is a region where many components interact heavily.

This can mean several things:

1. A real business capability
2. A fragile service cluster
3. A hidden platform
4. A domain that needs ownership
5. A god-service region
6. A place where every SOW eventually wanders in and starts a small, educational fire

### 9.1 Metrics

For each Leiden community, Scatter could calculate:

```text
internal edge density
external edge count
average node degree
weighted dependency density
number of projects involved
number of database objects touched
number of feature flags
number of pipelines
recent PR activity
historical defect count
SOW/ticket frequency
```

### 9.2 Example Output

```text
Zone: Plan Configuration

Density: High
External Coupling: High
DB Coupling: High
Recent Change Activity: High
Feature Flags: 9
Pipelines: 4

Interpretation:
This is not just a cluster. This is a busy cluster.
Changes here are likely to affect multiple workflows.
Treat as a coordination zone, not a simple implementation area.
```

### 9.3 Use Cases

Dense collaboration zones help with:

- SOW scoping
- PR risk
- reviewer selection
- regression planning
- migration planning
- ownership assignment
- architecture reviews

For example, if a small request touches a dense zone, Scatter can warn:

```text
The request appears small by changed file count, but it lands inside a high-density collaboration zone with heavy external coupling.
```

That is exactly the kind of thing that prevents bad estimates.

---

## 10. Likely Domain Boundaries

This is one of the strongest uses for Leiden.

A domain boundary candidate is a community whose structure suggests it may represent a coherent business capability.

### 10.1 Good Candidate Signals

A good domain-boundary candidate tends to have:

```text
High internal connectivity
Low external connectivity
Clear business vocabulary
Limited cross-community cycles
Limited shared database writes
Small number of stable entry points
Clear ownership pattern
Clear consumer set
Manageable pipeline impact
```

Example:

```text
Community 12:
  - CommuterEnrollmentService
  - ParkingPlanService
  - TransitPlanService
  - EnrollmentConfirmationEmailService
  - CommuterElectionRepository

Likely domain:
  Commuter Enrollment

Boundary strength:
  82/100
```

### 10.2 Bad Candidate Signals

A bad candidate tends to have:

```text
High external coupling
Shared tables everywhere
Multiple cycles
Portal logic mixed with domain logic
No clear business noun
Many unrelated workflows
Heavy dependency on common services
```

Example:

```text
Community 4:
  - AccountService
  - PlanService
  - ConsumerService
  - ClaimsService
  - EmployerService

Likely label:
  "Everything, apparently"

Boundary strength:
  31/100
```

This is not a service boundary. It is a weather system.

### 10.3 Scatter Feature: Domain Candidate Report

Command:

```bash
scatter domain-candidates
```

Example:

```text
Candidate Domain: Commuter Enrollment

Boundary Strength: 82/100
Internal Cohesion: High
External Coupling: Low
Cycle Risk: Low
Database Isolation: Medium
Migration Readiness: Good

Suggested Treatment:
Good candidate for API extraction or Strangler endpoint ownership.
```

Another:

```text
Candidate Domain: Consumer Account / Claims / Plan Crossover

Boundary Strength: 31/100
Internal Cohesion: High
External Coupling: Very High
Cycle Risk: High
Database Isolation: Poor

Suggested Treatment:
Do not extract as-is.
First reduce cycles and isolate database access behind adapters.
```

### 10.4 Why This Is Better Than Opinion

Without graph data, domain-boundary conversations often sound like:

```text
"I feel like this should be its own service."
```

With Scatter:

```text
"The graph suggests this is a cohesive domain candidate with 82% boundary strength, 11 external dependencies, no SCCs, and only two shared table writes."
```

Still not perfect. Much better.

---

## 11. Candidate Microservice Extraction

Now to the direct question:

> Could Leiden in Scatter help pull out microservice domains from the legacy monolith?

Yes — with an important correction.

Leiden does not pull out microservices.

Leiden helps Scatter discover candidate seams where a microservice or domain boundary might exist.

The extraction decision still requires human validation.

### 11.1 Correct Framing

Bad framing:

```text
Scatter finds microservices automatically.
```

Better framing:

```text
Scatter discovers natural dependency communities and scores them as candidate domain seams for Strangler-pattern migration.
```

Best framing:

```text
Scatter uses deterministic graph analysis to identify where the monolith already behaves like a neighborhood, where it is still tangled, and what would need to be isolated before a service boundary becomes real.
```

### 11.2 Extraction Readiness

Scatter can assign an extraction readiness score.

Possible dimensions:

```text
community cohesion
external coupling
cycle risk
shared DB writes
shared DB reads
entry point clarity
feature flag complexity
pipeline clarity
ownership clarity
historical co-change
test coverage
runtime dependency complexity
```

### 11.3 Example Report

```text
Candidate Domain: Commuter Enrollment

Extraction Readiness: 78/100

Move Together:
  - CommuterEnrollmentService
  - CommuterElectionRepository
  - EnrollmentConfirmationEmailService
  - ParkingPlanService
  - TransitPlanService

Keep Behind Adapter For Now:
  - EmployerConfigService
  - ConsumerProfileService
  - SharedNotificationService

Risks:
  - Email generation path is shared with non-commuter enrollment flows.
  - Employer-level settings cross into configuration domain.
  - Consumer portal trigger path needs validation.

Suggested Strangler Slice:
  Start with commuter enrollment confirmation behavior behind a BP endpoint.
  Keep shared email generation in monolith initially.
  Add adapter boundary before attempting full extraction.
```

This is the useful output.

It does not say:

> Here is your microservice.

It says:

> Here is a candidate seam, here is what moves together, here is what blocks extraction, and here is the safest first slice.

### 11.4 Microservice Boundary Is Not Just Code

A major risk in using community detection for microservices is forgetting that a microservice boundary is not only about code dependencies.

A real service boundary also needs:

- Data ownership
- Transaction boundaries
- API ownership
- Operational ownership
- Deployment independence
- Monitoring
- rollback strategy
- versioning
- security model
- support model

Leiden can identify a code community with high cohesion.

But if that community writes to five shared tables used by seven other domains, it may be a good functional domain candidate and a bad immediate microservice candidate.

Example:

```text
Community: Plan Funding / Vendor Accounts

Code Cohesion: High
DB Isolation: Low

Problem:
  Community writes to shared employer, bank account, plan, payment, and NACHA tables.

Recommendation:
  Good functional domain candidate.
  Bad immediate microservice candidate.
  Start with API façade and data-access isolation.
```

That distinction keeps Scatter honest.

---

## 12. Migration Groupings

A migration grouping answers:

> What should move together?

That is often more useful than:

> What service should we extract?

In Strangler-pattern work, the first move is often not a fully independent microservice. It is a controlled slice:

- one endpoint
- one capability
- one adapter boundary
- one domain-facing API
- one behavior moved behind a façade

Leiden can help identify the core group behind that slice.

### 12.1 Example

A SOW touches:

```text
DeductibleMetController
DeductibleService
PlanEnrollmentService
PostDeductibleHraService
LimitedPurposePlanRepository
```

Leiden finds:

```text
Community 17:
  Deductible / Plan Enrollment / Rollover
```

Scatter can recommend:

```text
Core Migration Group:
  - DeductibleMetController
  - DeductibleService
  - PlanEnrollmentService
  - RolloverService

Supporting Dependencies:
  - PlanRepository
  - ConsumerRepository
  - FeatureFlagHelper

External Dependencies:
  - ClaimsService
  - EmployerPlanConfigService
  - NotificationService
```

### 12.2 Scatter Feature: Migration Slice Planner

Command:

```bash
scatter migrate-slice --entry DeductibleMetController
```

Output:

```text
Recommended Migration Group:
  Community 17 - Deductible / Enrollment Trigger

Move Together:
  14 files
  3 repositories
  2 feature flag checks
  1 API controller
  4 database objects

Do Not Move Yet:
  ClaimsService - high external coupling
  ConsumerProfileService - shared across 5 communities

Suggested First Strangler Slice:
  Create BP endpoint for deductible-met attestation.
  Keep monolith repository access behind adapter.
  Do not attempt full PlanEnrollmentService extraction yet.
```

### 12.3 Why This Is Valuable

Modernization often fails when teams extract a method and accidentally bring half the monolith with it.

Scatter can prevent that by saying:

> This method belongs to a larger community. Move or wrap the community, not just the method.

Or:

> This dependency connects to six communities. Do not extract it directly. Put an adapter around it.

That is practical architecture guidance.

---

## 13. Blast-Radius Communities

This may be the most immediately useful Leiden-powered Scatter feature.

Today, PR risk often focuses on:

```text
Changed files
Changed projects
Changed lines
```

Those are useful, but incomplete.

A small PR can be high risk if it crosses community boundaries or touches a bridge node.

A large PR can be lower risk if it stays inside one isolated community.

### 13.1 Community-Aware PR Risk

Example:

```text
Changed files: 12
Impacted communities: 4

Primary community:
  Consumer Alerts / Receipts
  7 changed files
  81% of change footprint

Secondary communities:
  Feature Flags / Configuration
  2 changed files

  Consumer Portal Shared Services
  2 changed files

  Claims Repository
  1 changed file
```

Scatter can then explain:

```text
Risk increased because this PR crosses community boundaries.
The main change appears to be Consumer Alerts, but it also touches Claims Repository.
That is where the blast radius expands.
```

### 13.2 Boundary-Crossing Risk

Potential risk rules:

```text
Single community change:
  Lower risk

Two related communities:
  Moderate risk

Three or more communities:
  Higher risk

Touches boundary nodes:
  Higher risk

Touches SCC inside a community:
  Higher risk

Touches shared DB writes:
  Very high risk

Touches feature flags used by multiple communities:
  Higher release risk
```

### 13.3 Example PR Comment

```text
Scatter Risk Comment

This PR primarily affects the Consumer Alerts community, but crosses into Claims Repository and Feature Flag Configuration.

The risky part is not the number of changed files.
The risky part is that the change crosses two community boundaries and touches a shared repository used by three downstream workflows.

Suggested validation:
  - Consumer alert retrieval
  - Receipt-needed alert behavior
  - Denied receipt workflow
  - Upload-allowed denial codes
  - Partner feature flag off/on cases
```

That is useful.

A raw number like `Risk: 7.2` is fine, but the narrative is what helps a reviewer take action.

---

## 14. Boundary Nodes and Bridge Components

Leiden can help identify nodes that connect communities.

These are often the most dangerous files in the system.

Examples:

```text
DomainFeatureFlagHelper.cs
ConsumerSupportService.cs
PlanRepository.cs
SharedNotificationService.cs
EmployerConfigService.cs
DatabaseConnectionFactory.cs
AuthContext.cs
RepositoryLocator.cs
```

A bridge node may not look scary by name. It may look like a helper.

But if it connects seven communities, it is not “just a helper.”

It is a small door in a large building, and everyone uses that door.

### 14.1 Boundary Node Report

Command:

```bash
scatter boundary-nodes
```

Example:

```text
Top Boundary Nodes:

1. DomainFeatureFlagHelper.cs
   Connects: 7 communities
   Risk: High
   Recommendation:
     Treat changes as platform-level. Validate flag behavior across all consuming communities.

2. ConsumerSupportService.cs
   Connects: 4 communities
   Risk: High
   Recommendation:
     Require broader regression coverage.

3. PlanRepository.cs
   Connects: 5 communities
   Risk: High
   Recommendation:
     Database-impact review needed.
```

### 14.2 Uses

Boundary nodes can inform:

- PR review
- code owners
- regression coverage
- architecture cleanup
- adapter placement
- migration planning
- SOW sizing

For example:

> A SOW that touches one bridge node may be bigger than a SOW that touches ten isolated files.

That is exactly the kind of judgment Scatter should help automate.

---

## 15. SOW Qualification and T-Shirt Sizing

This is a strong business use case.

When a new SOW comes in, WEX-style teams often use SWAGs or T-shirt sizing. Scatter can make that less hand-wavy.

Leiden helps map SOW language to communities.

### 15.1 Example

SOW request:

```text
Update enrollment confirmation email logic for commuter plans.
```

Scatter maps this to likely communities:

```text
Commuter Enrollment
Notification / Email Generation
Employer Configuration
Admin Portal Settings
Possibly Consumer Portal
```

Then it evaluates:

```text
Number of communities involved
Boundary crossings
Shared services
Feature flags
UI impact
DB impact
Pipeline impact
Historical SOW patterns
```

### 15.2 Sizing Heuristics

Possible model:

```text
XS:
  One community
  Low density
  Few external edges
  No database coupling
  No UI change
  No feature flag needed

S:
  One community
  Moderate density
  Known endpoint
  Minimal UI impact
  Low regression spread

M:
  Two communities
  Some shared config or repository usage
  Feature flag needed
  Moderate test coverage

L:
  Three or more communities
  UI + service + database changes
  Cross-portal behavior
  Shared services involved

XL:
  Multiple communities
  High boundary-node usage
  SCCs present
  Shared database writes
  Pipeline impact unclear
  Requirements ambiguity
```

Or the more honest version:

```text
Run Away Briefly:
  Dense community
  shared sprocs
  portal overlap
  unclear trigger paths
  legacy constructors
  feature flags
  and someone said "small change"
```

### 15.3 Scatter Feature: SOW Scope

Command:

```bash
scatter sow-scope --keywords "commuter enrollment confirmation email"
```

Example output:

```text
Likely Impacted Communities:
  - Commuter Enrollment
  - Notification / Email Generation
  - Employer Configuration
  - Admin Portal Settings

Suggested Size:
  Large

Why:
  - Crosses 4 communities
  - Includes portal UI and backend generation logic
  - Shared email generation path appears to serve multiple enrollment methods
  - Feature flag recommended
  - Regression coverage needed across Admin, Employer, and Consumer-originated flows
```

### 15.4 Why This Would Have Helped in Real SOW Work

In the commuter email case, a key ambiguity was whether the change applied only to Admin and Employer portal triggers or to all methods that generate enrollment confirmation emails.

Scatter could have helped by showing:

```text
Email generation logic is not isolated to one portal.
The same generation path is connected to multiple enrollment triggers.
```

That would not resolve the business question by itself, but it would surface the ambiguity early.

That is exactly what a good SOW scoping tool should do.

---

## 16. Regression Test Targeting

Leiden communities can help pick smarter regression tests.

Instead of saying:

```text
Run everything.
```

Scatter can say:

```text
Run tests around the changed community, its boundary nodes, and its neighboring communities.
```

### 16.1 Example

Changed community:

```text
Consumer Alerts / Receipts
```

Recommended regression areas:

```text
GetConsumerAlerts
Receipt-needed alert behavior
Denied receipt workflow
Upload-allowed denial codes
Partner feature flag enabled/disabled
ConsumerSupportService DI resolution
```

### 16.2 Selection Model

Scatter can recommend tests based on:

```text
changed nodes
containing community
neighboring communities
boundary nodes
historical failure areas
feature flags
downstream callers
pipeline mapping
```

### 16.3 Output Example

```text
Recommended Regression Coverage:

Primary:
  - GetConsumerAlerts
  - Receipt needed alert
  - Denied receipt workflow

Feature Flag:
  - Flag enabled
  - Flag disabled
  - Partner not configured

Boundary:
  - Shared ConsumerSupportService construction
  - Claims repository interaction

Reason:
  Change touches Consumer Alerts community and crosses into Claims Repository.
```

This is practical because teams rarely have infinite testing time.

Scatter can help focus effort where the graph says risk lives.

---

## 17. Pipeline and Promotion Awareness

Scatter already has a strong story around promotion risk.

Leiden adds a logical layer between changed files and pipelines.

Instead of:

```text
These files changed.
```

Scatter can say:

```text
These communities changed.
These communities map to these projects.
These projects map to these pipelines.
Include these pipelines in the DevOps promotion ticket.
```

### 17.1 Example Output

```text
Impacted Communities:
  - Consumer Alerts
  - Consumer Portal Shared Services
  - Feature Flag Configuration

Likely Pipelines:
  - ConsumerWebService-CI
  - ConsumerPortal-CI
  - StranglerApi-CI

Promotion Note:
  This change is not isolated to Consumer Alerts.
  It touches shared service code used by the Consumer Portal path.
  Include both pipelines in the UAT promotion request.
```

### 17.2 Why This Matters

Promotion tickets often need a list of affected pipelines.

In a large monolith, figuring that out manually can become slow, fragile, and dependent on tribal knowledge.

Community-aware promotion analysis gives DevOps better signal:

- What changed?
- What communities are involved?
- Which projects belong to those communities?
- Which pipelines deploy them?
- Which downstream consumers should be checked?

That turns the release conversation from archaeology into analysis.

Still archaeology, but with better tools and fewer cursed artifacts.

---

## 18. Architecture Drift Detection

One powerful use of Leiden is comparing community structure over time.

Run community detection on:

```text
main branch today
main branch last release
quarterly snapshots
before / after migration
before / after a large SOW
```

Then compare:

```text
Did communities become cleaner?
Did external edges increase?
Did bridge nodes multiply?
Did cycles get worse?
Did a community split into healthier parts?
Did two communities merge into a larger mess?
```

### 18.1 Healthy Drift

Good signs:

```text
fewer cross-community edges
fewer cycles
stronger boundaries
lower boundary-node pressure
cleaner data access
more stable ownership
```

### 18.2 Unhealthy Drift

Bad signs:

```text
communities merging
external edges increasing
shared repository usage growing
database coupling increasing
feature flags spreading across domains
boundary nodes accumulating more consumers
```

### 18.3 Example Report

```text
Architecture Drift: Consumer Alerts

Compared to last release:
  External edges increased from 14 to 27.
  New dependency added to Claims Repository.
  Boundary strength dropped from 74 to 61.

Interpretation:
  The community is becoming less isolated.
  Recent changes may be increasing coupling.
```

### 18.4 Why Leadership Cares

Architecture drift is often discussed as opinion:

```text
The codebase feels worse.
```

Scatter can make it measurable:

```text
Boundary pressure increased 38% over two releases.
Cycle count increased from 3 to 9.
Shared DB writes increased across three communities.
```

That is a much stronger engineering management signal.

---

## 19. Ownership and Team Alignment

If Scatter includes Git/PR metadata, communities can be mapped to ownership patterns.

For each community:

```text
Who changes it most?
Who reviews it?
Which team owns most files?
Which team gets paged?
Which team thinks they own it but clearly does not?
```

### 19.1 Strong Ownership Example

```text
Community: Banking / NACHA

Primary Contributors:
  Team A: 71%
  Team B: 18%
  Team C: 11%

External Dependencies:
  - Plan Configuration
  - Employer Accounts
  - Payment Formatting

Ownership Signal:
  Strong

Recommendation:
  Treat Team A as primary reviewer for PRs touching this community.
```

### 19.2 Weak Ownership Example

```text
Community: Shared Consumer Services

Primary Contributors:
  Team A: 31%
  Team B: 28%
  Team C: 24%
  Team D: 17%

Ownership Signal:
  Weak

Recommendation:
  This is a shared-risk community.
  Add explicit reviewer rules or split responsibility.
```

### 19.3 Uses

This helps with:

- code owners
- reviewer routing
- offshore/onshore collaboration
- onboarding
- support handoffs
- architecture accountability

A community with high risk and weak ownership is a good candidate for explicit governance.

---

## 20. Refactoring Candidates

Leiden communities can identify several kinds of refactoring opportunities.

### 20.1 Strong Cluster, Weak Boundary

Signal:

```text
High internal cohesion
High external coupling
```

Meaning:

> This thing wants to be a domain, but too many other things poke it.

Possible refactors:

```text
Introduce façade
Create adapter
Move DB access behind boundary
Define API surface
Reduce shared model leakage
```

### 20.2 Weak Cluster, High Traffic

Signal:

```text
Low internal cohesion
Many edges everywhere
```

Meaning:

> This is probably a junk drawer.

Possible refactors:

```text
Split utility class
Separate responsibilities
Remove god-service behavior
Create smaller abstractions
```

### 20.3 Strong Cluster With SCCs

Signal:

```text
High cohesion
Internal cycles
```

Meaning:

> This may be a good domain candidate, but currently tied in knots.

Possible refactors:

```text
Break cycles
Introduce interface boundary
Separate orchestration from persistence
Move shared dependency inward or outward
```

### 20.4 Bridge Node Overload

Signal:

```text
One node connects many communities
```

Meaning:

> This file is doing too much or is too centrally depended on.

Possible refactors:

```text
Split by domain
Introduce domain-specific adapters
Move generic helper behind stable interface
Reduce direct consumers
```

---

## 21. Feature Flag Impact Mapping

Feature flags are supposed to reduce release risk, but they can also hide cross-domain coupling.

Scatter can treat feature flags as graph nodes.

### 21.1 Feature Flag Community Map

Example:

```text
Feature Flag: 477542_UpdateReceiptNeededAlerts

Communities Touched:
  - Consumer Alerts / Receipts
  - Consumer Support Service
  - Partner Configuration

Flag Scope:
  Medium

Warning:
  Flag check appears in shared service code.
  Validate both enabled and disabled paths.
```

### 21.2 Why This Matters

A feature flag that touches one community is usually manageable.

A feature flag that spans five communities may be a release-risk seam.

Feature flag usage can answer:

```text
Is this flag local to a behavior?
Is it controlling behavior across domains?
Is it placed at the right boundary?
Does it belong in configuration, orchestration, or domain logic?
```

That is useful for both PR review and release planning.

---

## 22. Compare Planned Architecture vs Actual Architecture

This is another strong modernization feature.

If the target architecture says:

```text
Claims
Benefits
Accounts
Payments
Notifications
Enrollment
Plan Configuration
```

But Leiden detects:

```text
Claims + Plan Config + Consumer Account
Payments + Employer Account + NACHA
Notifications + Enrollment + Portal Config
```

Scatter can show the mismatch.

### 22.1 Output Example

```text
Target State Mismatch:

Detected graph communities do not align cleanly with intended domain boundaries.

Largest mismatch:
  Claims, Plan Config, and Consumer Account are highly interdependent in current state.

Recommendation:
  Do not attempt direct service extraction using target-state boundaries yet.
  First isolate shared data access and reduce cross-domain service calls.
```

### 22.2 Why This Is Useful

It reframes architecture gaps as terrain.

You are not saying:

> The target architecture is wrong.

You are saying:

> The current system does not yet have seams that match the target architecture. Here is the work required to create them.

That is a much better conversation.

---

## 23. Community-Aware AI Summarization

Scatter’s philosophy should remain:

> AI is enrichment, not the engine.

Leiden provides deterministic communities. Scatter extracts evidence:

```text
top files
top namespaces
top terms
strongest edges
entry points
database objects
feature flags
pipelines
historical tickets
```

Then AI summarizes:

```text
Community 23 appears to handle consumer-facing alert logic for receipt status, denied claims, and upload eligibility.
```

### 23.1 Suggested Flow

```text
1. Build graph
2. Run Leiden
3. Calculate metrics
4. Extract top evidence
5. Generate candidate label
6. Generate human-readable explanation
7. Include confidence and caveats
```

### 23.2 Example

Raw evidence:

```text
Top terms:
  receipt, alert, consumer, denial, upload, notification

Top files:
  ConsumerSupportService
  ReceiptAlertService
  DenialCodeRepository
  NotificationService
```

AI label:

```text
Consumer Receipt Alerting
```

AI summary:

```text
This community appears to handle consumer-facing alert logic for receipt status, denied claims, and upload eligibility.
```

The important rule:

> The AI names and explains the community. It does not invent the community.

That keeps the system defensible.

---

## 24. Scoring Model Ideas

Leiden gives the communities. Scatter needs to score them.

### 24.1 Community Cohesion

Possible formula:

```text
cohesion = internal_edges / total_edges_touching_community
```

Weighted version:

```text
cohesion = weighted_internal_edges / weighted_total_edges_touching_community
```

High cohesion means the community is internally connected.

### 24.2 Boundary Pressure

```text
boundary_pressure = external_edges / internal_edges
```

Weighted version:

```text
boundary_pressure = weighted_external_edges / weighted_internal_edges
```

High boundary pressure means the community leaks into other areas.

### 24.3 Boundary Strength

```text
boundary_strength =
  cohesion
  - normalized_boundary_pressure
  - cycle_penalty
  - shared_db_penalty
  + naming_consistency
  + ownership_consistency
```

### 24.4 Blast Radius Score

```text
blast_radius =
  impacted_communities
  + boundary_nodes_touched
  + external_edges_from_changed_nodes
  + SCC_presence
  + shared_db_access
  + feature_flag_spread
  + pipeline_count
```

### 24.5 Migration Readiness

```text
migration_readiness =
  cohesion
  - external_coupling
  - cycle_risk
  - shared_database_access
  - boundary_node_reliance
  + entry_point_clarity
  + ownership_clarity
  + pipeline_clarity
```

### 24.6 Domain Confidence

```text
domain_confidence =
  cohesion
  + naming_consistency
  + ownership_consistency
  + historical_cochange_consistency
  - external_coupling
  - mixed_database_ownership
```

### 24.7 Refactor Urgency

```text
refactor_urgency =
  change_velocity
  + defect_history
  + cycle_risk
  + boundary_pressure
  + PR_frequency
  + shared_db_write_count
```

### 24.8 SOW Complexity

```text
sow_complexity =
  impacted_communities
  + impacted_layers
  + boundary_crossings
  + shared_db_writes
  + feature_flag_need
  + pipeline_count
  + ambiguity_score
  + historical_change_volatility
```

---

## 25. Suggested Scatter Commands

### 25.1 Community Discovery

```bash
scatter communities
```

Detect and list Leiden communities.

### 25.2 Single Community Detail

```bash
scatter community --id 17
```

Show one community in detail.

### 25.3 Community-Aware PR Risk

```bash
scatter pr-risk --community-aware
```

Adds community crossing and boundary node scoring to PR risk.

### 25.4 Blast Radius

```bash
scatter blast-radius --file ConsumerSupportService.cs
```

Shows impacted communities.

### 25.5 Migration Slice

```bash
scatter migrate-slice --entry DeductibleMetController
```

Suggests migration grouping.

### 25.6 SOW Scope

```bash
scatter sow-scope --keywords "commuter enrollment confirmation email"
```

Maps SOW language to likely communities.

### 25.7 Architecture Drift

```bash
scatter architecture-drift --since release/2026.04
```

Compares community structure over time.

### 25.8 Boundary Nodes

```bash
scatter boundary-nodes
```

Finds bridge components.

### 25.9 Domain Candidates

```bash
scatter domain-candidates
```

Ranks likely domain boundaries.

### 25.10 Feature Flag Impact

```bash
scatter flag-impact --flag 477542_UpdateReceiptNeededAlerts
```

Maps a feature flag to communities and release risk.

### 25.11 Pipeline Impact

```bash
scatter promotion-impact --branch feature/fid1826-alerts
```

Maps communities to projects and pipelines.

---

## 26. Example Scatter Report: PR Risk

```text
Scatter Community-Aware PR Risk

PR:
  FID1826HD - Update Receipts Needed Alert

Changed Files:
  12

Primary Community:
  Consumer Alerts / Receipts

Secondary Communities:
  - Feature Flag Configuration
  - Claims Repository
  - Consumer Portal Shared Services

Risk:
  High-Medium

Why:
  The PR is mostly contained in Consumer Alerts, but crosses two community boundaries.
  It touches shared service construction and a repository used by claims-related workflows.
  Feature flag behavior must be validated for enabled and disabled partner states.

Boundary Nodes Touched:
  - ConsumerSupportService.cs
  - DomainFeatureFlagHelper.cs

Recommended Validation:
  - GetConsumerAlerts
  - Denied receipt included when upload allowed
  - Denied receipt excluded when upload not allowed
  - Overdue receipt included
  - Feature flag enabled
  - Feature flag disabled
  - Partner not configured
  - ConsumerSupportService DI resolution
```

This is actionable. It tells the reviewer what changed, why it matters, and where to focus.

---

## 27. Example Scatter Report: SOW Scope

```text
Scatter SOW Scope Analysis

SOW:
  Commuter-only enrollment confirmation email

Likely Impacted Communities:
  - Commuter Enrollment
  - Notification / Email Generation
  - Employer Configuration
  - Admin Portal Settings
  - Consumer Enrollment Trigger Path

Suggested T-Shirt Size:
  Large

Why:
  The change appears to affect more than a single portal setting.
  Email generation logic is shared across multiple enrollment triggers.
  Scope should clarify whether all methods that trigger enrollment confirmation emails are included.

Architecture Notes:
  The graph suggests commuter enrollment behavior is cohesive enough to reason about as a neighborhood.
  However, email generation crosses into a shared notification community.

Recommended Questions:
  - Does this apply to Admin portal enrollment only?
  - Employer portal enrollment?
  - Consumer portal enrollment?
  - CDEX or direct ingestion?
  - Any API-triggered enrollment changes?
  - Should the feature flag gate all trigger paths?

Recommended Implementation Strategy:
  Add settings at required levels.
  Centralize the commuter-only check in the shared generation path.
  Avoid duplicating logic per portal.
  Add regression coverage for each enrollment trigger.
```

This would be useful before a team commits to a SWAG.

---

## 28. Example Scatter Report: Migration Slice

```text
Scatter Migration Slice Analysis

Entry Point:
  DeductibleMetController.SubmitDeductibleMetAttestation

Detected Community:
  Deductible / Plan Enrollment / Rollover

Extraction Readiness:
  68/100

Move Together:
  - DeductibleMetController
  - DeductibleMetService
  - PlanEnrollmentService
  - PostDeductibleHraService
  - LimitedPurposePlanRepository
  - RolloverService

Keep Behind Adapter:
  - ConsumerProfileService
  - EmployerPlanConfigService
  - ClaimsService
  - NotificationService

Risks:
  - PlanEnrollmentService has external dependencies to multiple communities.
  - Rollover logic touches shared plan and balance data.
  - Shared database writes reduce immediate microservice readiness.

Suggested Strangler Slice:
  Create BP-facing deductible-met endpoint.
  Wrap monolith plan enrollment logic behind adapter.
  Keep shared DB writes in monolith for first phase.
  Add feature flag for routed behavior.
  Add tests around FSA and HRA paths.
```

This is the modernization version of “cut here, not there.”

---

## 29. Example Scatter Report: Domain Candidate

```text
Scatter Domain Candidate Report

Candidate:
  Commuter Enrollment

Boundary Strength:
  82/100

Extraction Readiness:
  74/100

Evidence:
  High internal cohesion
  Clear business vocabulary
  Limited number of external entry points
  Related services and repositories cluster together
  Moderate dependency on employer configuration
  Moderate dependency on shared email generation

Potential API Boundary:
  - SubmitCommuterEnrollment
  - UpdateCommuterElection
  - GenerateCommuterEnrollmentConfirmation

Risks:
  - Email generation path shared with non-commuter flows
  - Employer-level settings cross into configuration domain
  - Consumer portal trigger path needs validation

Recommendation:
  Good candidate for a Strangler slice.
  Do not extract full email generation as part of the first move.
  Put a domain-specific adapter around notification behavior.
```

This is the kind of report that could support a design review.

---

## 30. Comparison With Other Algorithms

Leiden should not be used alone. It should be selected based on what Scatter is trying to answer.

### 30.1 Leiden vs Louvain

| Topic | Louvain | Leiden |
|---|---|---|
| Purpose | Community detection | Community detection |
| Speed | Fast | Fast |
| Quality | Good | Usually better |
| Connected communities | Can produce poorly connected communities | Designed to improve this |
| Scatter use | Useful baseline | Better default |

Recommendation:

> Use Leiden as the default modularity-based community detector.

### 30.2 Leiden vs Tarjan

| Topic | Tarjan | Leiden |
|---|---|---|
| Category | Structural decomposition | Community detection |
| Finds | Strongly connected components | Natural communities |
| Meaning | Mechanical dependency knots | Functional neighborhoods |
| Output | Hard fact | Candidate grouping |
| Use in Scatter | Cycle detection, migration blockers | Domain discovery, blast radius, migration slices |
| Risk role | “Cannot separate as-is” | “Likely belongs together” |

Recommendation:

> Use both. Tarjan finds knots. Leiden finds neighborhoods.

### 30.3 Leiden vs Infomap

| Topic | Leiden | Infomap |
|---|---|---|
| Basis | Modularity / quality function optimization | Flow / information theory |
| Good for | Dense communities | Random-walk / navigation communities |
| Scatter use | Dependency neighborhoods | Runtime-like flow or call-path behavior |
| Strength | General community detection | Flow-based behavior grouping |

Recommendation:

> Compare Leiden and Infomap. If they agree, confidence increases. If they disagree, the difference may reveal useful architecture nuance.

### 30.4 Leiden vs MCL

| Topic | Leiden | MCL |
|---|---|---|
| Basis | Modularity optimization | Markov flow expansion/inflation |
| Good for | Large graph communities | Flow-like clusters, biological networks |
| Scatter use | General domain candidates | Alternative clustering for dependency flow |
| Tuning | Resolution parameter | Inflation parameter |

Recommendation:

> MCL can be a useful secondary algorithm, especially where dependency flow matters.

### 30.5 Leiden vs Spectral Clustering

| Topic | Leiden | Spectral |
|---|---|---|
| Requires k? | Usually no | Often yes |
| Scalability | Good | Can be costly |
| Explainability | Moderate | Mathematical but less intuitive |
| Scatter use | General community detection | Partitioning / comparison |

Recommendation:

> Spectral clustering is less likely to be the first production choice for Scatter, but can be useful for experiments.

### 30.6 Leiden vs METIS

| Topic | Leiden | METIS |
|---|---|---|
| Goal | Find natural communities | Balanced graph partitioning |
| Best for | Domain discovery | Work partitioning / load balancing |
| Output | Natural clusters | Balanced partitions |
| Scatter use | Architecture discovery | Splitting work across teams/pipelines |

Recommendation:

> Use Leiden for discovering natural seams. Use METIS if the goal is balanced partitioning, not domain truth.

### 30.7 Leiden vs Label Propagation

| Topic | Leiden | Label Propagation |
|---|---|---|
| Speed | Fast | Very fast |
| Stability | Better | Can be unstable |
| Quality | Higher | Rougher |
| Scatter use | Mainline analysis | Quick approximation |

Recommendation:

> Label propagation may be useful for quick exploratory analysis, but Leiden is better for durable reports.

### 30.8 Leiden vs Stochastic Block Models

| Topic | Leiden | SBM |
|---|---|---|
| Style | Heuristic optimization | Probabilistic generative model |
| Output | Communities | Inferred blocks |
| Explainability | Practical | Statistical |
| Scatter use | Engineering tool | Research / validation layer |

Recommendation:

> SBM could be useful later for validation, but likely overkill for the first Scatter product story.

### 30.9 Leiden vs Embedding-Based Clustering

| Topic | Leiden | Embedding + k-means/HDBSCAN |
|---|---|---|
| Input | Graph directly | Node vectors |
| Good for | Graph structure | Structure + attributes |
| Risk | Less black-box | More black-box |
| Scatter use | Deterministic graph communities | Semantic/code metadata clustering |

Recommendation:

> Embeddings can enrich analysis, but Scatter should keep deterministic graph structure as the engine.

---

## 31. Suggested Implementation Architecture

### 31.1 Data Pipeline

```text
1. Repository scan
2. Project graph extraction
3. Namespace/type extraction
4. Dependency edge extraction
5. Database access extraction
6. Feature flag extraction
7. Pipeline mapping
8. Historical co-change import
9. Graph normalization
10. Edge weighting
11. Leiden community detection
12. Tarjan SCC detection
13. Boundary node analysis
14. Score calculation
15. AI label / narrative generation
16. Report generation
```

### 31.2 Graph Store

Scatter could represent the graph in memory initially, using:

```text
networkx
igraph
graph-tool
custom adjacency lists
```

For Leiden specifically, Python packages commonly used include:

```text
igraph
leidenalg
```

For very large graphs, Scatter may eventually need more performance-oriented graph structures.

### 31.3 Output Artifacts

Possible output formats:

```text
Markdown report
JSON report
SARIF-like risk output
GitHub PR comment
HTML dashboard
CSV community table
Graph visualization export
Mermaid diagrams
DOT/Graphviz
```

### 31.4 JSON Schema Sketch

```json
{
  "communities": [
    {
      "id": 17,
      "label": "Consumer Alerts / Receipts",
      "confidence": 0.84,
      "nodes": [],
      "top_nodes": [],
      "internal_edges": 118,
      "external_edges": 21,
      "cohesion": 0.82,
      "boundary_pressure": 0.27,
      "cycle_count": 2,
      "db_coupling_score": 0.41,
      "migration_readiness": 0.68,
      "boundary_nodes": [],
      "pipelines": [],
      "feature_flags": [],
      "recommended_tests": []
    }
  ]
}
```

---

## 32. Implementation Roadmap

### Phase 1: Community Detection Prototype

Goal:

> Prove Leiden can produce useful communities from existing Scatter graph data.

Tasks:

```text
Build project/file/class graph
Assign edge weights
Run Leiden
Output community list
Generate basic metrics
Produce Markdown report
```

Deliverable:

```bash
scatter communities --format markdown
```

Success criteria:

```text
Communities are recognizable to engineers.
Top nodes make sense.
Obvious functional neighborhoods emerge.
Output is useful enough to discuss in architecture review.
```

### Phase 2: PR Risk Integration

Goal:

> Use communities to improve PR risk comments.

Tasks:

```text
Map changed files to communities
Count impacted communities
Detect boundary crossings
Detect bridge nodes
Add community risk to PR score
Generate PR comment
```

Deliverable:

```bash
scatter pr-risk --community-aware
```

Success criteria:

```text
Reviewers can see why a PR is risky.
Scatter identifies cross-community changes.
Regression recommendations are more focused.
```

### Phase 3: Boundary Node and SCC Integration

Goal:

> Combine Leiden with Tarjan.

Tasks:

```text
Run Tarjan SCCs
Overlay SCCs inside communities
Identify bridge nodes between communities
Rank boundary nodes
Add cycle and bridge penalties to scores
```

Deliverables:

```bash
scatter boundary-nodes
scatter cycles
scatter community --id 17
```

Success criteria:

```text
Scatter distinguishes "cohesive and clean" from "cohesive but cyclic."
Migration blockers become visible.
```

### Phase 4: SOW Scope Mapping

Goal:

> Help qualify SOWs and estimate T-shirt size.

Tasks:

```text
Map keywords to files/classes/communities
Use historical co-change where available
Score impacted communities
Estimate size
Generate questions and risks
```

Deliverable:

```bash
scatter sow-scope --keywords "..."
```

Success criteria:

```text
SOW ambiguity surfaces earlier.
Sizing is backed by graph evidence.
Team gets better initial SWAGs.
```

### Phase 5: Migration Slice Planner

Goal:

> Recommend candidate Strangler slices.

Tasks:

```text
Identify community around entry point
Find move-together group
Find adapter candidates
Find shared DB blockers
Find external dependencies
Generate migration recommendation
```

Deliverable:

```bash
scatter migrate-slice --entry SomeController
```

Success criteria:

```text
Output helps architecture discussion.
Identifies what to move, what to wrap, and what blocks extraction.
```

### Phase 6: Architecture Drift

Goal:

> Track community health over time.

Tasks:

```text
Snapshot graph per release
Run community detection per snapshot
Compare communities
Track boundary pressure
Track cycles
Track migration readiness
```

Deliverable:

```bash
scatter architecture-drift --since release/x
```

Success criteria:

```text
Architecture erosion becomes measurable.
Migration progress becomes visible.
```

---

## 33. Product Positioning

This is a strong way to differentiate Scatter from general-purpose AI coding assistants.

### 33.1 Scatter vs Codex / Claude / Auggie

Codex, Claude, and Auggie are general-purpose AI coding assistants. They are useful for:

```text
writing code
explaining code
fixing bugs
generating tests
summarizing files
working inside local context
```

Scatter answers a different class of question:

```text
What is the structural shape of this codebase?
What breaks if this changes?
What communities are impacted?
What pipelines are involved?
Where are the migration seams?
What is the risk before merge or promotion?
```

### 33.2 Clean Differentiator

> Scatter answers a structural question, not just a coding question.

AI assistants can read files and offer interpretations. Scatter builds the dependency graph and reasons over the structure.

When Scatter says:

```text
This PR crosses three communities and touches a bridge node used by seven downstream workflows.
```

That answer comes from graph analysis, not from an LLM guessing from whatever context fits in a window.

### 33.3 Complementary, Not Competitive

Scatter does not preclude using Augment, Claude, Codex, or other assistants.

In fact, the best story is:

```text
Use AI assistants to help write and understand code.
Use Scatter to understand the structural risk of changing and releasing that code.
```

Scatter can even use AI for narrative summarization.

But the deterministic graph remains the engine.

### 33.4 Positioning Statement

> Scatter is a structural risk and architecture reconnaissance tool for large .NET codebases. It maps dependencies, communities, cycles, bridge nodes, pipelines, and migration seams so teams can make better decisions before merge, before promotion, before SOW commitment, and before service extraction.

That is a strong story.

---

## 34. Risks and Caveats

### 34.1 Leiden Is Not Domain Truth

Leiden knows graph structure. It does not know the business.

It can suggest:

```text
These nodes appear to form a community.
```

It cannot prove:

```text
This is the correct business domain.
```

Scatter should always frame output as:

```text
Likely domain candidate
Candidate migration slice
Suggested boundary
```

Not:

```text
Definitive microservice
```

### 34.2 Folder and Naming Bias

If edge weights or labels rely too heavily on naming, Scatter may reinforce bad legacy names.

Example:

```text
Common
Shared
Helper
Manager
Service
```

These names may not describe actual domains.

Solution:

```text
Use naming as a weak signal, not the primary signal.
```

### 34.3 Shared Database Coupling Can Invalidate Clean Code Clusters

A code community may look clean, but if it writes shared tables with other communities, it is not extraction-ready.

Solution:

```text
Always include DB coupling in migration readiness.
```

### 34.4 Dynamic Runtime Behavior May Be Missed

Static analysis may miss:

```text
reflection
dynamic SQL
runtime dependency injection
configuration-based routing
plugin loading
message bus behavior
external API callbacks
```

Solution:

```text
Include runtime/config analysis where possible.
Flag unknowns explicitly.
```

### 34.5 Historical Co-Change Can Mislead

Files may change together because of process habits, not true architecture.

Example:

```text
One developer owns both areas.
One release bundled unrelated work.
One ticket included broad cleanup.
```

Solution:

```text
Use co-change as an enrichment signal, not a sole source of truth.
```

### 34.6 Resolution Parameter Sensitivity

Leiden has parameters that affect community size.

Too coarse:

```text
Huge communities that are not actionable.
```

Too fine:

```text
Tiny communities that miss real domains.
```

Solution:

```text
Support multiple resolutions and compare stability.
```

### 34.7 False Precision

A score like `82/100` can look more precise than it really is.

Solution:

```text
Pair scores with explanation, evidence, and confidence bands.
```

Example:

```text
Boundary Strength: 82/100
Confidence: Medium-High
Reason:
  Strong cohesion and low external edges, but database ownership is only partially isolated.
```

---

## 35. Recommended First Build

If this were being added to Scatter, I would not start with “microservice extraction.”

That phrase is too big and invites skepticism.

Start with something more concrete:

> **Community-aware PR risk and blast-radius analysis.**

### 35.1 Why Start There?

It has immediate value.

It answers a daily engineering question:

```text
What does this PR touch, and what should I test?
```

It also proves that the detected communities are meaningful.

If the communities are useful in PR risk, then they can be trusted more in SOW and migration analysis.

### 35.2 First Feature Set

Build:

```text
scatter communities
scatter pr-risk --community-aware
scatter boundary-nodes
scatter community --id
```

Then add:

```text
scatter sow-scope
scatter migrate-slice
scatter architecture-drift
```

### 35.3 MVP Output

A GitHub PR comment like:

```text
Scatter Risk Comment

This PR primarily affects Consumer Alerts / Receipts.

Impacted Communities:
  - Consumer Alerts / Receipts
  - Feature Flag Configuration
  - Claims Repository

Boundary Nodes:
  - ConsumerSupportService.cs
  - DomainFeatureFlagHelper.cs

Risk:
  High-Medium

Why:
  The change crosses two community boundaries and touches a shared repository used by claims-related workflows.

Suggested Validation:
  - GetConsumerAlerts
  - denied receipt upload eligibility
  - overdue receipt behavior
  - feature flag enabled/disabled
```

That is shippable. Useful. Easy to demo.

---

## 36. How to Explain This Internally

### 36.1 Short Version

> Scatter can use Leiden to find natural neighborhoods in the monolith. Those neighborhoods help us see blast radius, SOW scope, migration slices, and candidate service boundaries. It does not magically define microservices, but it gives us a much better map of where the seams might be.

### 36.2 Slightly More Technical Version

> We build a dependency graph from project references, type usage, service calls, repositories, database access, feature flags, and historical co-change. Leiden detects communities in that graph. Scatter then scores those communities for cohesion, boundary pressure, cycle risk, database coupling, and pipeline impact. That lets us identify natural functional neighborhoods, risky bridge nodes, and possible Strangler slices.

### 36.3 Executive-Friendly Version

> This gives us evidence-based architecture reconnaissance. Instead of guessing how big a change is or where a service boundary should be, Scatter shows which parts of the system actually move together, where the dependency knots are, and what risk comes with changing or extracting them.

### 36.4 Dry-Humored Version

> It will not hand us perfect microservices in a gift basket. But it can show us where the monolith already has neighborhoods, where the fences might go, and where the whole thing is still held together by shared repositories and optimism.

---

## 37. Recommended Language for Scatter README

Possible README section:

```markdown
## Community-Aware Risk Analysis

Scatter can detect natural communities inside a large .NET codebase using graph clustering. These communities represent functional neighborhoods: parts of the system that are more connected internally than externally.

Scatter uses those communities to improve:

- PR blast-radius analysis
- SOW sizing and qualification
- migration slice planning
- candidate domain boundary discovery
- pipeline impact analysis
- regression test targeting

Community detection does not replace architecture judgment. It gives teams a map of the actual dependency terrain so they can make better decisions before merge, before promotion, and before modernization work.
```

Possible feature callout:

```markdown
### Candidate Service Boundaries

Scatter can identify communities that may be good candidates for Strangler-pattern migration or service extraction. Each candidate is scored for cohesion, external coupling, cycle risk, shared database access, and pipeline impact.

Scatter does not claim "this is your microservice." It says "this is a candidate seam, here is the evidence, and here is what must be untangled before extraction is safe."
```

---

## 38. Final Recommendation

Leiden is worth exploring for Scatter.

Not as a novelty. Not as “AI architecture magic.” Not as a graph-theory science project that ends in a dashboard nobody opens.

It should be used as a practical layer in the risk engine.

The best combined model is:

```text
Tarjan SCCs
+ Leiden communities
+ bridge-node detection
+ DB coupling
+ historical co-change
+ pipeline mapping
+ feature flag mapping
+ deterministic scoring
+ AI narrative summaries
```

That gives Scatter a strong capability set:

```text
Find the knots.
Find the neighborhoods.
Find the bridges.
Find the blast radius.
Find the migration slices.
Find the service-boundary candidates.
Explain the risk.
```

The most valuable first use is probably:

```text
Community-aware PR risk
```

The most strategically interesting use is:

```text
Candidate domain and migration-slice discovery
```

The most business-friendly use is:

```text
SOW qualification and T-shirt sizing
```

The most architecture-mature use is:

```text
Drift detection and target-state comparison
```

The cleanest overall positioning:

> Scatter uses deterministic graph analysis to reveal the real structure of a legacy .NET monolith. Leiden helps identify natural communities. Tarjan identifies hard dependency knots. Together, they help teams understand risk, qualify work, plan migrations, and find candidate domain seams without pretending the algorithm is smarter than the business.

That is a serious tool.

And more importantly, it is the kind of tool a team working inside a 20-year-old monolith would actually use.

---

## Appendix A: Summary Table of Potential Leiden-Powered Scatter Features

| Feature | What It Answers | Primary Users |
|---|---|---|
| `scatter communities` | What natural neighborhoods exist? | Engineers, architects |
| `scatter pr-risk --community-aware` | What communities does this PR affect? | Developers, reviewers |
| `scatter blast-radius` | What is impacted by this file/change? | Developers, QA |
| `scatter boundary-nodes` | What files bridge multiple communities? | Architects, tech leads |
| `scatter domain-candidates` | Where are likely service/domain seams? | Architects, managers |
| `scatter migrate-slice` | What should move together? | Modernization teams |
| `scatter sow-scope` | How big is this SOW likely to be? | Managers, tech leads |
| `scatter flag-impact` | Which communities does this flag affect? | Release teams |
| `scatter promotion-impact` | Which pipelines are involved? | DevOps, release managers |
| `scatter architecture-drift` | Is the architecture getting cleaner or worse? | Leadership, architects |
| `scatter test-impact` | What should we test? | QA, developers |
| `scatter ownership` | Who appears to own this community? | Engineering managers |

---

## Appendix B: Example Metrics by Community

| Metric | Meaning | Use |
|---|---|---|
| Cohesion | How internally connected the community is | Domain confidence |
| Boundary Pressure | How much it connects outward | Extraction risk |
| Cycle Count | Number of SCCs inside the community | Refactoring risk |
| Bridge Nodes | Nodes connecting communities | Blast-radius risk |
| DB Coupling | Shared table/sproc usage | Microservice readiness |
| Feature Flag Spread | Number of communities touched by flags | Release risk |
| Pipeline Count | Number of deployment pipelines involved | Promotion risk |
| Change Velocity | How often it changes | SOW and PR risk |
| Ownership Concentration | Whether one team mostly owns it | Governance |
| Historical Defect Rate | How often changes cause issues | Regression priority |
| Entry Point Clarity | Whether callers enter through stable APIs | Strangler readiness |

---

## Appendix C: Algorithm Selection Summary

| Algorithm | Use in Scatter | Best For |
|---|---|---|
| Leiden | Community detection | Natural neighborhoods, domain candidates |
| Tarjan SCC | Structural decomposition | Cycles, hard dependency knots |
| Infomap | Flow-based communities | Runtime/call-flow-like grouping |
| MCL | Flow clustering | Alternative dependency-flow clusters |
| METIS | Balanced partitioning | Splitting work, not domain truth |
| Label Propagation | Fast rough communities | Quick exploration |
| Spectral Clustering | Mathematical partitioning | Experiments / validation |
| SBM | Probabilistic blocks | Research-grade validation |
| Embedding + HDBSCAN | Attribute-aware clustering | Combining code graph and metadata |

---

## Appendix D: Practical Rules of Thumb

### A community is a good domain candidate when:

```text
It is cohesive.
It has few external dependencies.
It has a clear business name.
It has limited shared database writes.
It has clear entry points.
It does not contain major cycles.
It has understandable ownership.
```

### A community is a bad immediate microservice candidate when:

```text
It writes shared tables used by multiple domains.
It contains several SCCs.
It depends on broad shared services.
It has unclear entry points.
It crosses multiple portal workflows.
It has high feature-flag spread.
It maps to too many pipelines.
```

### A PR is riskier when:

```text
It crosses community boundaries.
It touches bridge nodes.
It touches SCCs.
It touches shared DB writes.
It touches feature flags used by several communities.
It impacts multiple pipelines.
```

### A SOW is probably larger than it looks when:

```text
It touches more than one community.
It crosses UI + service + DB layers.
It changes shared generation logic.
It affects multiple trigger paths.
It requires feature flags.
It changes behavior across portals.
It lands in a dense collaboration zone.
```

### A migration slice is promising when:

```text
It has a cohesive community.
It has a small number of entry points.
It can keep shared dependencies behind adapters.
It has manageable DB coupling.
It can be gated with a feature flag.
It has focused regression coverage.
```

---

## Appendix E: The One-Sentence Thesis

> Leiden helps Scatter find the monolith’s natural neighborhoods; Tarjan finds the knots; together they let Scatter explain blast radius, SOW scope, migration slices, and candidate service boundaries with evidence instead of folklore.
