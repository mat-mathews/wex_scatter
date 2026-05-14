# Root vs Affected Target Tiering

## Context

Run 4 on the monolith: 17 targets, 109 consumer analyses, 180 AI enrichment calls (9 risk + 160 coupling + 11 surface), 2+ hours, connection errors at the end. The 160 coupling calls are the cost driver — every direct consumer with relevant files across ALL targets gets a coupling narrative AI call with file contents.

The AI already distinguishes root from affected in its evidence language. "Manages Receipt Images — responsible for storing uploaded receipt photos" (root) vs "identity verification may be required" (affected). We just need the AI to label this distinction explicitly, then use it to control analysis depth and enrichment scope.

## The change

Add a `target_role` field ("root" or "affected") to each target. Root targets are where code changes happen (3-8 projects). Affected targets are downstream/peripheral. The pipeline treats them differently.

### Expected impact on the monolith run

| Phase | Before (all equal) | After (tiered) |
|-------|-------------------|-----------------|
| Consumer analyses | 109 | ~25 (5 root × full + 12 affected × direct-only) |
| Coupling AI calls | 160 | ~20 (root consumers only) |
| Surface AI calls | 11 | ~5 (root only) |
| Risk AI calls | 9 | 9 (unchanged, both tiers) |
| Total AI enrichment | 180 | ~34 |
| Estimated runtime | 2+ hours | ~15-20 min |

## Changes

### 1. Add `target_role` field — `scatter/core/models.py:107`

```python
@dataclass
class AnalysisTarget:
    target_type: str
    name: str
    ...
    match_evidence: Optional[str] = None
    target_role: str = "root"  # "root" | "affected"
```

Default "root" so existing code paths (other modes creating AnalysisTarget) are unaffected.

### 2. Update prompt — `scatter/ai/tasks/parse_work_request.py:126-148`

Add `target_role` to the expected JSON response and add role instructions to the rules:

```
Return a JSON array of objects. Each object should have:
- "type": one of "project" or "sproc"
- "name": the project or sproc name
- "role": one of "root" or "affected"
...

Rules:
...
- Mark targets as "root" when source code in that project will be WRITTEN or MODIFIED.
  Root targets are the epicenter of the change — typically 3-8 projects.
- Mark targets as "affected" when the project may need testing or is downstream of
  a root target, but won't require direct code changes for this work request.
```

### 3. Parse role from response — `scatter/ai/tasks/parse_work_request.py:40-79`

Add one line after extracting match_evidence:

```python
target_role = item.get("role", "root")
```

Pass to `AnalysisTarget(target_role=target_role, ...)`.

### 4. Branch analysis depth by role — `scatter/analyzers/impact_analyzer.py:217-237`

Replace the single target loop with role-aware branching:

```python
for target in targets:
    effective_depth = sow_depth if target.target_role == "root" else 0
    logging.info(
        f"\n--- Analyzing target: {target.name} "
        f"(type: {target.target_type}, role: {target.target_role}) ---"
    )
    target_impact = _analyze_single_target(
        ...,
        max_depth=effective_depth,
        ...
    )
    report.targets.append(target_impact)
```

Note: `sow_depth` is in scope — it's already computed in `run_impact_mode()` and passed as `max_depth` to `run_impact_analysis()`. But we need to pass the original `max_depth` parameter through and override per-target. The cleanest approach: use the existing `max_depth` parameter as the base, and set to 0 for affected targets.

### 5. Scope enrichment by role — `scatter/analyzers/impact_analyzer.py:285-315`

Gate coupling and surface work on root role:

```python
# Coupling: root targets only (this is the big savings — 160 → ~20 calls)
if target_impact.target.target_role == "root":
    for c_idx, consumer in enumerate(target_impact.consumers):
        if consumer.depth == 0 and consumer.relevant_files:
            ...coupling_work.append(...)

# Change surface: root targets only
t = target_impact.target
if t.csproj_path and t.target_type == "project" and t.target_role == "root":
    ...surface_work.append(...)
```

Risk assessment stays for both tiers — it's cheap (one call per target with consumers) and useful for affected targets too.

### 6. Update dry run output — `scatter/modes/impact.py:199`

Add Role column:

```python
print(f"  {'#':<4} {'Name':<50} {'Type':<8} {'Role':<9} {'Conf':<6} {'Resolved'}")
```

### 7. Update console reporter — `scatter/reports/console_reporter.py:258`

Show role in the target header:

```python
print(f"\n--- Target: {ti.target.name} ({ti.target.target_role}) ---")
```

### 8. Update reporters for serialization

- **JSON**: automatic via `asdict()` — `target_role` serialized as a string field
- **Markdown**: add role to target header
- **CSV**: `target_role` included via existing `asdict()` pattern

### 9. Regression test update — `tests/unit/test_sow_regression.py`

Add `target_role` to AnalysisTarget expected keys.

## Team Review

**Priya:** "What if the AI marks something root that should be affected, or vice versa? The dry run is the safety net — users see the role assignments before committing to a full run. If the AI consistently misclassifies, we can tune the prompt. The default of 'root' means any target without an explicit role gets full analysis — safe failure mode."

**Marcus:** "The coupling savings are the real win. 160 calls → ~20. That's what killed run 4. Risk stays for both tiers because it's one call per target. The question is: does the AI actually produce useful role assignments? Only the monolith run will tell us. Ship it, test it, adjust."

**Tomás:** "Keep it as a field on each target, not two separate arrays. One new field, one `item.get('role', 'root')`, one branch in the loop. The response format stays a flat JSON array. Minimal change surface."

**Devon:** "Affected targets at depth 0: one find_consumers() call each, no transitive. That's the O(1) path through the graph — project reference lookup only, maybe namespace check. Should be <1 second each instead of minutes. The 109 consumer analyses become ~25 (5 root × depth 1 fan-out + 12 affected × 1 each)."

**Anya:** "Test the default. If the AI doesn't return a role field, `item.get('role', 'root')` gives full analysis. That's the safe path. Add a test that verifies affected targets skip coupling and surface enrichment."

## Files touched

| File | Change |
|------|--------|
| `scatter/core/models.py:107` | Add `target_role` field to AnalysisTarget |
| `scatter/ai/tasks/parse_work_request.py:40,126` | Add role to prompt + parse from response |
| `scatter/analyzers/impact_analyzer.py:217,285` | Branch depth + enrichment scope by role |
| `scatter/modes/impact.py:199` | Add Role column to dry run |
| `scatter/reports/console_reporter.py:258` | Show role in target header |
| `scatter/reports/markdown_reporter.py` | Show role in target section header |
| `tests/unit/test_sow_regression.py` | Add `target_role` to expected keys |

## Verification

1. `uv run ruff check scatter/ && uv run ruff format --check scatter/`
2. `uv run mypy scatter --ignore-missing-imports`
3. `uv run pytest -v`
4. `bash tools/check.sh`
5. `--sow-dry-run` on monolith: verify role assignments look correct
6. Full `--sow` run on monolith: verify runtime drops from 2h → ~15-20min
