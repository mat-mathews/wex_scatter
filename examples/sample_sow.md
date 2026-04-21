# Statement of Work: Portal Configuration Multi-Tenancy Enablement

**Project Code:** PORTAL-2026-Q2-017
**Requested By:** Sarah Chen, VP of Product — Portal & Configuration Services
**Date Submitted:** 2026-03-15
**Priority:** High
**Target Completion:** 2026-05-30 (end of Q2)
**Estimated Budget:** $185,000 (inclusive of infrastructure changes)

---

## 1. Background

WEX currently operates a single-tenant portal configuration model. All portal settings — display preferences, feature flags, data retention policies, and integration endpoints — are stored in a shared configuration store with no tenant isolation. This was acceptable when WEX served a single enterprise customer per deployment, but the business has moved to a shared-infrastructure model where multiple clients operate on the same platform instance.

The current architecture stores portal configuration data through a centralized data service that calls into the database via stored procedures. These procedures do not accept or filter by tenant identifier. Downstream systems that consume portal settings — including the web frontend, batch synchronization jobs, and external API integrations — assume a single-tenant context and do not propagate tenant identity through the call chain.

In Q4 2025, the Compliance team flagged this as a data isolation risk (ref: COMPLIANCE-2025-089). Two incidents in January 2026 resulted in Client A's portal configuration being temporarily visible to Client B's admin users due to a caching defect in the portal layer. The root cause was not the cache itself but the absence of tenant scoping in the underlying data access path.

## 2. Objectives

1. Introduce tenant isolation to the portal configuration data access layer so that all reads and writes are scoped to a specific tenant.
2. Ensure that all downstream consumers of portal configuration — including batch processing, web-facing controllers, and caching layers — propagate and enforce tenant context.
3. Maintain backward compatibility for existing single-tenant deployments during a transition period (estimated 90 days post-release).
4. Achieve zero cross-tenant data leakage as validated by integration tests and a third-party penetration test.

## 3. Scope of Work

### 3.1 Data Access Layer Changes

The core data service responsible for portal configuration persistence must be updated to accept a tenant identifier on all public methods. The stored procedures that this service calls — specifically the insert and retrieval operations for portal settings — must be modified to include tenant ID as a required parameter. The database schema changes (adding tenant columns, creating filtered indexes) are handled by a separate DBA work stream and are not in scope for this SOW, but the application-layer callers must be updated to pass the new parameter.

### 3.2 Consumer Updates

All projects that consume the portal configuration service must be updated to:
- Obtain tenant context from the incoming request (HTTP header, message envelope, or job configuration)
- Pass tenant ID through to the data service on every call
- Handle the case where tenant ID is missing (reject the request with a clear error, do not default to a "global" tenant)

This includes — but may not be limited to — the web-facing portal controllers, the batch synchronization processes that run on a nightly schedule, and any API endpoints that expose portal settings to external systems.

### 3.3 Caching Layer

The portal caching layer currently caches configuration objects by setting key only. After this change, cache keys must include the tenant identifier to prevent cross-tenant cache pollution. Cache invalidation logic must also be tenant-scoped.

### 3.4 Out of Scope

- Database schema migrations (separate DBA work stream, ref: DBA-2026-Q2-003)
- UI changes to the portal admin dashboard (separate frontend SOW, ref: FE-2026-Q2-011)
- Authentication and authorization changes (tenant identity is assumed to be available from the existing auth middleware)
- Performance benchmarking of multi-tenant queries (deferred to post-release optimization sprint)
- Migration tooling for converting existing single-tenant data to multi-tenant format

## 4. Technical Constraints

- All changes must be backward compatible with the existing API surface for 90 days
- No breaking changes to stored procedure signatures — new parameters must be optional with a default of NULL (interpreted as "legacy single-tenant mode")
- The solution must work with both the current .NET Framework 4.7.2 projects and the newer .NET 8 SDK-style projects in the codebase
- Existing CI/CD pipelines must continue to pass without modification (new tests may be added but existing tests must not break)

## 5. Deliverables

| # | Deliverable | Description | Acceptance Criteria |
|---|-------------|-------------|---------------------|
| 1 | Updated data service | Core configuration service with tenant parameter on all public methods | Unit tests verify tenant isolation; no method callable without tenant ID |
| 2 | Updated stored procedure callers | All call sites pass tenant ID to insert and retrieval procedures | Code review confirms no unscoped calls remain |
| 3 | Consumer project updates | All downstream consumers propagate tenant context | Integration tests verify tenant header flows end-to-end |
| 4 | Cache tenant scoping | Cache keys include tenant ID; invalidation is tenant-scoped | Cache hit/miss tests verify no cross-tenant pollution |
| 5 | Backward compatibility shim | Legacy single-tenant callers continue to work during transition | Existing test suite passes without modification |
| 6 | Integration test suite | End-to-end tests covering multi-tenant reads, writes, cache, and batch sync | Tests run in CI; zero cross-tenant leakage scenarios |

## 6. Timeline

| Phase | Duration | Activities |
|-------|----------|------------|
| Design & Planning | 1 week | Architecture review, identify all affected call sites, design tenant propagation strategy |
| Implementation — Core | 2 weeks | Data service changes, stored procedure caller updates, unit tests |
| Implementation — Consumers | 2 weeks | Downstream project updates, cache changes, batch job updates |
| Integration Testing | 1 week | End-to-end testing, regression suite, performance smoke tests |
| Staging Deployment | 1 week | Deploy to staging, run penetration test, validate with Product |
| Production Rollout | 1 week | Phased rollout with feature flag, monitoring, rollback plan |

## 7. Assumptions

1. The DBA team will have the schema changes (tenant columns, indexes) deployed to the development environment by 2026-04-07.
2. The authentication middleware already provides a resolvable tenant identifier on every incoming request.
3. The batch job scheduler can be configured to pass tenant ID via job metadata (confirmed with DevOps 2026-03-10).
4. No more than 50 tenants will be active on a single instance in the initial rollout.
5. The existing stored procedure parameter addition (NULL default) approach has been approved by the DBA team lead (Maria Rodriguez, confirmed 2026-03-12).

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Unknown consumers of configuration service discovered late | Medium | High | Run dependency analysis tooling (Scatter) before implementation to identify full blast radius |
| Stored procedure changes cause regression in unrelated batch jobs | Low | High | Run full regression suite in staging; coordinate with batch job owners |
| Cache invalidation race condition under multi-tenant load | Medium | Medium | Design review with platform team; add cache versioning |
| Timeline slip due to DBA schema dependency | Medium | High | Begin application-layer work with mock tenant columns; integrate when schema is ready |

## 9. Approval

| Role | Name | Date | Signature |
|------|------|------|-----------|
| VP Product | __________________ | __________ | _____________ |
| Engineering Lead | __________________ | __________ | _____________ |
| Architecture | __________________ | __________ | _____________ |
| DBA Lead | __________________ | __________ | _____________ |
