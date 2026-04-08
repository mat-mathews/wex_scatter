# SOW Signal Analysis

**Date:** 2026-04-06
**Context:** Analysis of two real WEX CSE/SOW documents to understand what signals Scatter could realistically extract and match against a .NET dependency graph. This informs what the `--sow` mode needs to detect and how the sproc discovery work (see `SPROC_DISCOVERY_BRAINSTORM.md`) connects to SOW-driven impact analysis.

---

## Sample SOWs analyzed

1. **FID1010HD** — Commuter-only enrollment confirmation email. Adds instance/admin/employer level settings to control when enrollment confirmation emails are generated for parking and mass transit plans.
2. **FID460HD** — New Deductible Met web service method. Creates a web service for partners to indicate a consumer has met their deductible, triggering automatic enrollment in a post-deductible FSA and balance rollover.

---

## Signal categories

### 1. Direct code artifact matches

These are terms in the SOW text that likely map to actual class names, method names, or type declarations in the codebase.

| SOW text | Likely code artifact | SOW |
|----------|---------------------|-----|
| "Enrollment Confirmation" | Class or service: `EnrollmentConfirmation*` | FID1010HD |
| "Consumer Web Services" | Project: `ConsumerWebServices.csproj` or similar | Both |
| "CreateEmployerFromTemplate" | Method name (exact match) | FID1010HD |
| "CreateEmployer" | Method name (exact match) | FID1010HD |
| "Deductible Met" | Class: `DeductibleMetService`, `DeductibleMetHandler` | FID460HD |
| "Limited Purpose FSA" / "Post Deductible FSA" | Enum or constant: `FSAType.LimitedPurpose` | FID460HD |
| "Available Balance" | Property on account/enrollment model | FID460HD |
| "Health Plan" | Entity class: `HealthPlan`, `ConsumerHealthPlan` | FID460HD |
| "enrollment flag" / Active/Inactive/Terminated | Enrollment status enum | FID460HD |
| "PortalDataService" | Class name (from sample projects) | FID1010HD |

**Detection approach:** Text matching against codebase index (class names, method names, enum values). Current AI parse can do this.

### 2. Application/project identifiers

These are named systems or portals that likely map to specific projects or deployable units.

| SOW text | Likely project | Both SOWs? |
|----------|---------------|------------|
| "Administrator Portal" | Admin portal project(s) | Yes |
| "Consumer Portal" | Consumer-facing portal project(s) | Yes |
| "Employer Web Services" | Employer API project | FID1010HD |
| "Consumer Web Services" | Consumer API project | FID460HD |
| "Message Center" | Module within consumer portal | FID460HD |
| "NetBenefits" | External partner system (out of scope for graph) | FID460HD |
| "TPA Setup" | Admin configuration pages | FID1010HD |

**Detection approach:** Requires codebase index mapping business names to project names. The AI needs to know that "Administrator Portal" maps to whatever the project is actually called in the solution. This is where index quality determines match quality.

### 3. Stored procedure signals (inferred, not named)

Neither SOW names specific stored procedures. But the operations described imply data access patterns that almost certainly map to sprocs in a sproc-heavy codebase.

**FID1010HD (enrollment confirmation):**

| Operation described | Likely sproc pattern |
|--------------------|---------------------|
| Read/write instance level setting | `sp_Get/SetInstanceSetting`, `sp_CopyInstanceSettings` |
| Read/write administrator level setting | `sp_Get/SetAdminNotificationSetting` |
| Read/write employer level setting | `sp_Get/SetEmployerNotificationSetting` |
| TPA Copy functionality | `sp_CopyInstance*`, `sp_CloneInstanceSettings` |
| Check enrollment confirmation config | `sp_GetEnrollmentConfirmationConfig` or similar |

**FID460HD (deductible met):**

| Operation described | Likely sproc pattern |
|--------------------|---------------------|
| Look up consumer by admin + employer + identifier | `sp_GetConsumer*`, `sp_FindConsumer*` |
| Create health plan record | `sp_InsertConsumerHealthPlan`, `sp_CreateHealthPlan*` |
| Update health plan record | `sp_UpdateConsumerHealthPlan` |
| Check active enrollment in limited purpose FSA | `sp_GetConsumerEnrollment*`, `sp_GetActiveEnrollments` |
| Create enrollment in post-deductible FSA | `sp_CreateEnrollment`, `sp_EnrollConsumer` |
| Create financial transaction (debit) | `sp_InsertTransaction`, `sp_CreateLedgerEntry` |
| Create financial transaction (credit) | Same sproc(s) with different parameters |
| Roll over balance | `sp_RolloverBalance` or reuse of transaction sprocs |

**Detection approach:** This is the gap. Current Scatter cannot bridge "SOW describes a balance rollover operation" → "sproc `sp_RolloverFunds` is shared by 7 projects." The sproc inventory (see `SPROC_DISCOVERY_BRAINSTORM.md`) would enable this by:
1. Building a sproc catalog with name-based search
2. Matching SOW operation keywords against sproc names
3. Tracing which projects share those sprocs

### 4. Multi-level settings pattern

Both SOWs describe settings at multiple organizational levels:

- Instance level → Administrator level → Employer level

This implies a settings infrastructure (tables, sprocs, UI components) that many projects touch. The pattern is:
- A shared settings table or service (likely in a core/common project)
- Admin portal reads/writes admin-level settings
- Employer management reads/writes employer-level settings
- Business logic reads the effective setting (cascading from instance → admin → employer)

This is a cross-cutting concern. Changing the settings schema or adding a new setting touches the settings infrastructure, every portal that exposes it, and every service that reads it. The blast radius is wide but predictable if you can identify the settings infrastructure project.

### 5. UI navigation paths

SOWs include specific breadcrumbs to UI locations:

- "TPA Setup > Profile tab > Notifications Settings page > General Rules section"
- "Administrator Portal > Setup tab > Manage Consumer Notifications page"
- "Administrator Portal > Employer tab > Manage Consumer Notifications page"

These could map to controller classes or view files if naming conventions are consistent (e.g., `ManageConsumerNotificationsController`). Low-confidence match but worth attempting.

---

## What Scatter could produce today vs. with sproc inventory

### Today (AI parse + codebase index, no sproc inventory):

- Identify 2-4 target projects with high confidence (web services, enrollment engine)
- Identify 2-3 more with medium confidence (admin portal, plan configuration)
- Trace project-reference consumers through the graph
- **Miss sproc-based coupling entirely**
- Estimated coverage: 50-60% of actual blast radius

### With sproc inventory:

- Same project targets as above
- Plus: "these N sprocs related to enrollment/transactions/settings are shared across M projects"
- Blast radius expands to include projects that share data access patterns
- **Catches the hidden database coupling that represents most of the risk in a sproc-heavy codebase**
- Estimated coverage: 75-85% of actual blast radius

### Remaining gap (even with sproc inventory):

- Runtime/DI-based coupling (service registrations, interface implementations)
- Message queue consumers (if events are used for notifications)
- External system integrations (NetBenefits, partner APIs)
- Configuration-driven behavior (feature flags, settings that change code paths)

---

## Patterns emerging across SOWs

Analyzing multiple WEX CSEs reveals recurring patterns that could inform detection strategies:

1. **Multi-level settings** (instance → admin → employer) — appears in both SOWs. Implies a shared settings infrastructure that is a coupling hotspot.

2. **Web service methods on existing services** — both SOWs add or modify methods on existing service projects. The service project is identifiable, but the downstream consumers of that service are the real blast radius.

3. **Financial transactions** — FID460HD involves ledger operations (debit/credit/rollover). This implies shared transaction processing infrastructure.

4. **Plan types and enrollment status** — shared domain models (FSA types, enrollment flags, plan year concepts) that likely live in a core library referenced by many projects.

5. **Email/notification generation** — FID1010HD modifies email templates and generation logic. Notification services are typically shared infrastructure.

6. **Copy/clone operations** — "TPA Copy functionality" suggests stored procedures that duplicate settings when creating new instances. These sprocs touch the same tables as the CRUD sprocs.

7. **Consumer identification** — both SOWs involve looking up consumers by various identifiers. This implies a shared consumer resolution service or sproc.

These patterns suggest that a small number of infrastructure concerns (settings, enrollment, transactions, notifications, consumer lookup) appear across many CSEs. Mapping those infrastructure concerns to their code artifacts once would accelerate SOW analysis for all future CSEs.

---

## Recommendations

1. **Sproc inventory is the highest-leverage improvement** for SOW analysis in a sproc-heavy codebase. See `SPROC_DISCOVERY_BRAINSTORM.md` for implementation plan.

2. **Settings infrastructure mapping** — identify the projects and sprocs that implement the multi-level settings pattern. This is a recurring coupling hotspot.

3. **Domain model catalog** — surface shared domain types (plan types, enrollment status, transaction types) in the codebase index. SOWs reference these business concepts frequently.

4. **Operation-to-sproc bridging** — the AI parse should attempt to map SOW operations ("create enrollment," "roll over balance") to sproc names via keyword matching against the sproc inventory. This is the key bridge between business language and code artifacts.
