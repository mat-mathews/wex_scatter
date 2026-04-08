# Initiative 6 Phase 3: Blast Radius Tree View — Implementation Plan

## Context

The impact analysis console output currently displays consumers as a flat list with inline depth numbers:
```
  [HIGH] ConsumerA (direct)
  [MEDIUM] ConsumerB (depth: 1)
```

This hides the propagation chain — you can't see *which* direct consumer exposed a transitive one. The goal is to render a tree that makes the blast radius visually obvious:
```
GalaxyWorks.Data  (target)
├── GalaxyWorks.WebPortal       [HIGH]  direct
│   └── GalaxyWorks.BatchProcessor  [MEDIUM]  via WebPortal
├── MyGalaxyConsumerApp         [MEDIUM] direct
└── MyGalaxyConsumerApp2        [LOW]    direct
```

Ref: tasks.txt lines 585–600.

---

## Step 1: Add `propagation_parent` field to `EnrichedConsumer`

**File:** `scatter/core/models.py` (line ~72)

Add one field to the `EnrichedConsumer` dataclass:
```python
propagation_parent: Optional[str] = None   # consumer_name of the parent in BFS tree (None = direct)
```

This is the only model change. It flows through `asdict()` automatically, so JSON output gets it for free.

---

## Step 2: Track parent in BFS traversal

**File:** `scatter/analyzers/impact_analyzer.py` — `trace_transitive_impact()` (lines 199–283)

Currently the BFS iterates level-by-level (`current_level` → `next_level_raw`) but doesn't record which consumer discovered each transitive hit.

Changes:
- Add a `parent_map: Dict[Path, str] = {}` alongside the existing `visited` set.
- When discovering transitive consumers of consumer X (line 266–278), record `parent_map[discovered_path] = consumer_name` for each new discovery.
- When constructing `EnrichedConsumer` (line 250), set `propagation_parent=parent_map.get(consumer_path)`. Direct consumers (depth 0) won't be in `parent_map`, so they get `None`.

This avoids mutating the consumer dicts returned by `find_consumers()` — clean separation of BFS state from input data.

---

## Step 3: Tree rendering in console reporter

**File:** `scatter/reports/console_reporter.py` — `print_impact_report()` (lines 76–122)

Replace the flat consumer loop with a tree renderer:

1. Add a helper function `_build_consumer_tree(consumers)` that returns a dict mapping `parent_name → [children]`. Direct consumers (where `propagation_parent is None`) are children of a virtual root. **Orphan handling**: if a consumer's `propagation_parent` references a name not in the consumer list (e.g., removed by cycle detection), attach it to the root level.

2. Add a helper function `_render_tree(target_name, consumers)` that:
   - Groups direct consumers as root-level children
   - **Sorts children within each parent group by confidence descending** (HIGH → MEDIUM → LOW) so highest-impact paths appear first
   - Recursively renders children with box-drawing prefixes (├──, └──, │)
   - Each line: `{prefix} {consumer_name}  [{confidence_label}]  {depth_info}`
   - `depth_info` is `"direct"` for depth 0, or `"via {propagation_parent}"` for depth > 0
   - Detail lines (risk, pipeline, coupling) render **before** children, using the same connector prefix

3. Modify `print_impact_report()` to call `_render_tree()` for each `TargetImpact` instead of the current flat loop.

Example output structure:
```
--- Target: GalaxyWorks.Data ---
Direct Consumers: 3 | Transitive: 1
GalaxyWorks.Data
├── WebPortal            [HIGH]   direct
│   Risk: Medium — "Uses PortalDataService directly"
│   Pipeline: pipeline-a
│   └── BatchProcessor   [MEDIUM] via WebPortal
├── ConsumerApp          [MEDIUM] direct
└── ConsumerApp2         [LOW]    direct
```

---

## Step 4: Add `propagation_tree` to JSON output

**File:** `scatter/reports/json_reporter.py` — `write_impact_json_report()` (lines 59–78)

After the existing `report_dict.update(asdict(report))`, build and inject a `propagation_tree` key into each target dict:

1. Add a helper function `_build_propagation_tree(consumers_list)` that converts the flat consumers array into a nested structure:
   ```json
   {
     "consumer_name": "WebPortal",
     "depth": 0,
     "confidence_label": "HIGH",
     "children": [
       {
         "consumer_name": "BatchProcessor",
         "depth": 1,
         "confidence_label": "MEDIUM",
         "children": []
       }
     ]
   }
   ```

2. For each target in `report_dict["targets"]`, add `"propagation_tree": [tree_nodes]` alongside the existing flat `"consumers"` array (backward compatible).

---

## Step 5: Add `PropagationParent` column to CSV

**File:** `scatter/reports/csv_reporter.py` — `write_impact_csv_report()` (lines 54–88)

- Add `'PropagationParent'` to `fieldnames` list (after `'Depth'`)
- Add `'PropagationParent': c.propagation_parent or ''` to each row dict

Minimal change — one field added to the schema.

---

## Step 6: Tests

**File:** `test_impact_analysis.py` — new test class `TestBlastRadiusTreeView`

### 6a. Model tests
- `test_enriched_consumer_has_propagation_parent`: verify field exists, defaults to None
- `test_enriched_consumer_with_parent`: verify field is set correctly

### 6b. BFS parent tracking tests
- `test_transitive_tracing_sets_propagation_parent`: mock BFS at depth 1, verify transitive consumer has `propagation_parent` set to the direct consumer's name
- `test_direct_consumers_have_no_parent`: verify depth-0 consumers have `propagation_parent is None`
- `test_cycle_detection_preserves_parent`: verify cycle detection doesn't corrupt parent tracking
- `test_orphan_parent_falls_back_to_root`: if propagation_parent references a removed consumer, tree builder attaches to root

### 6c. Console tree rendering tests
- `test_tree_output_single_target_direct_only`: 3 direct consumers → verify ├── and └── chars in output
- `test_tree_output_mixed_depths`: 1 direct + 1 transitive → verify │ and └── nesting, "via" label
- `test_tree_output_empty_consumers`: no consumers → no tree rendered
- `test_tree_output_deep_nesting`: depth 0→1→2 chain → verify 3-level tree with correct indentation
- `test_tree_output_sorts_by_confidence`: verify HIGH consumers render before LOW within same parent

### 6d. JSON propagation_tree tests
- `test_json_has_propagation_tree`: verify `propagation_tree` key exists in each target
- `test_json_propagation_tree_nesting`: verify nested children structure matches BFS chain
- `test_json_flat_consumers_preserved`: verify backward-compat `consumers[]` array still present

### 6e. CSV tests
- `test_csv_has_propagation_parent_column`: verify column exists in output
- `test_csv_propagation_parent_values`: verify correct parent names in rows

---

## Files Modified (Summary)

| File | Change |
|------|--------|
| `scatter/core/models.py` | Add `propagation_parent` field to `EnrichedConsumer` |
| `scatter/analyzers/impact_analyzer.py` | Tag BFS discoveries with parent name |
| `scatter/reports/console_reporter.py` | Tree rendering with box-drawing characters |
| `scatter/reports/json_reporter.py` | Add `propagation_tree` nested structure |
| `scatter/reports/csv_reporter.py` | Add `PropagationParent` column |
| `test_impact_analysis.py` | ~16 new tests for tree view |

No new files needed.

---

## Verification

1. **Run full test suite**: `python -m pytest` — all existing tests must still pass (the new field defaults to `None`, so `asdict()` output gains one key but nothing breaks).
2. **Check new tests**: `python -m pytest test_impact_analysis.py -k "TreeView" -v`
3. **Visual spot-check**: Run `python -m scatter --sow "..." --search-scope . --google-api-key ...` (or mock) and verify tree output in console.
