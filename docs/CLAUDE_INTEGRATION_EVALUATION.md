# Scatter as a Claude Tool: Integration Evaluation

**Date:** 2026-03-11
**Author:** PM + Principal Engineer evaluation
**Scatter version:** 2.1.0 (443 tests, 6 analysis modes)

---

## 1. Executive Summary

Scatter already produces machine-readable JSON output across all modes. Exposing it as a Claude tool requires minimal new code — the hard part (analysis engine, metrics, caching, health dashboard) is done. The question is **which integration surface** and **how to drive adoption**.

Two integration paths exist:

| Path | What it is | Effort | Who benefits |
|------|-----------|--------|-------------|
| **Claude Code Skills** | Markdown files in `.claude/skills/` that tell Claude how to invoke scatter CLI | 1-2 days | Engineers using Claude Code in the monolith |
| **MCP Server** | A Python process exposing scatter as structured tools over JSON-RPC | 3-5 days | Any MCP-compatible client (Claude Code, Claude Desktop, VS Code, custom agents) |

**Recommendation:** Start with Skills (zero code, immediate value), build the MCP server when cross-client demand materializes.

---

## 2. Why This Matters

### The problem scatter solves today

WEX's ~20-year .NET monolith has hundreds of projects with deep, intertwined dependencies. Engineers spend 2-4 hours manually tracing "if I change X, what breaks?" Scatter reduces that to <30 seconds.

### Why Claude integration multiplies that value

Today, an engineer must:
1. Know scatter exists
2. Remember the CLI flags
3. Run the command
4. Read and interpret the output

With Claude integration, the workflow becomes:
> "What's the blast radius if we add a TenantId column to the portal configuration table?"

Claude invokes scatter, reads the JSON output, and responds with a narrative summary, risk assessment, and action plan. The engineer never touches the CLI.

**This collapses four steps into one natural-language question.** It also eliminates the adoption barrier — engineers don't need to learn scatter's CLI; they just ask Claude.

---

## 3. Integration Path A: Claude Code Skills

### What it is

Skills are markdown files checked into the repo at `.claude/skills/<name>/SKILL.md`. When a user asks Claude Code a question that matches the skill's description, Claude reads the instructions and follows them — typically invoking bash commands and reading the results.

### Skills to create

| Skill | Invocation | Maps to CLI mode |
|-------|-----------|-----------------|
| `/scatter-graph` | "Show me the dependency health" | `--graph --output-format json` |
| `/scatter-consumers` | "Who uses GalaxyWorks.Data?" | `--target-project ... --output-format json` |
| `/scatter-impact` | "What's the blast radius of changing X?" | `--sow "..." --output-format json` |
| `/scatter-sproc` | "Who calls dbo.sp_InsertPortalConfiguration?" | `--stored-procedure ... --output-format json` |
| `/scatter-branch` | "What did my feature branch touch?" | `--branch-name ... --output-format json` |

### How it works (example)

```yaml
# .claude/skills/scatter-graph/SKILL.md
---
name: scatter-graph
description: >
  Analyze .NET dependency graph. Computes coupling metrics, detects
  dependency cycles, identifies domain clusters, and produces a health
  dashboard. Use when asked about project architecture, coupling,
  dependency health, or cycles.
allowed-tools: Bash(python *), Read, Glob
argument-hint: [search-scope-path]
---

Run scatter in graph mode:

1. Execute: python -m scatter --graph --search-scope "$ARGUMENTS"
   --include-db --output-format json --output-file /tmp/scatter_graph.json
2. Read /tmp/scatter_graph.json
3. Summarize: health dashboard, top coupled projects, cycles,
   domain clusters, observations
4. If the user asked about a specific project, focus on its metrics
```

### Level of effort

| Task | Effort |
|------|--------|
| Write 5 SKILL.md files | 2-3 hours |
| Test each skill interactively | 2-3 hours |
| Write a brief usage guide | 1 hour |
| **Total** | **~1 day** |

### Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Claude misinterprets scatter JSON output | Low | JSON is structured; Claude handles it well. Test with real outputs. |
| Long-running scans timeout | Medium | Graph cache makes subsequent runs fast (<2s). First run on large repo may take 30-60s. Set bash timeout. |
| Skills only work in Claude Code | Low | This is the target audience. MCP server is the escape hatch. |
| Skill instructions drift from CLI changes | Low | Skills are in-repo; update them alongside CLI changes. |

---

## 4. Integration Path B: MCP Server

### What it is

A Python process that speaks the Model Context Protocol (JSON-RPC 2.0 over stdio). Claude Code, Claude Desktop, or any MCP client can connect to it and call scatter's analysis functions as structured tools with typed parameters.

### Architecture

```
Claude Code / Desktop
    |
    | JSON-RPC over stdio
    v
scatter/mcp_server.py (FastMCP wrapper)
    |
    | Python import (no subprocess)
    v
scatter.analyzers / scatter.reports (existing modules)
```

### Key design decision: subprocess vs. direct import

| Approach | Pros | Cons |
|----------|------|------|
| **Subprocess** (shell out to `python -m scatter`) | Simple, no coupling, reuses CLI validation | Process startup overhead (~500ms), stdout/stderr management |
| **Direct import** (call scatter functions in-process) | Fast (<100ms), richer error handling, can return Python objects | Tighter coupling, must handle logging (scatter uses `logging` module which writes to stderr) |

**Recommendation:** Start with subprocess (simpler, safer), migrate to direct import if latency matters.

### Tools to expose

| Tool | Parameters | Returns |
|------|-----------|---------|
| `analyze_dependency_graph` | `search_scope`, `include_db`, `rebuild` | Full graph JSON (metrics, cycles, clusters, dashboard) |
| `find_project_consumers` | `target_project`, `search_scope`, `class_name?`, `method_name?` | Consumer list with pipeline mappings |
| `analyze_change_impact` | `description`, `search_scope`, `max_depth?` | Impact report with risk assessment |
| `find_sproc_consumers` | `sproc_name`, `search_scope` | Projects referencing the sproc |
| `get_project_metrics` | `project_name`, `search_scope` | Single project's coupling score, fan-in/out, cluster |
| `generate_mermaid_diagram` | `search_scope`, `top_n?` | Mermaid markup for dependency visualization |

### Level of effort

| Task | Effort |
|------|--------|
| Create `scatter/mcp_server.py` with FastMCP | 1 day |
| Define 6 tool functions with type hints + docstrings | 1 day |
| Add `.mcp.json` for project-scoped registration | 1 hour |
| Test with Claude Code `claude mcp add` | 0.5 day |
| Error handling, timeouts, logging isolation | 0.5 day |
| Documentation | 0.5 day |
| **Total** | **~3-4 days** |

### Dependencies

```
pip install "mcp[cli]"  # Anthropic's Python MCP SDK
```

Single new dependency. The SDK is stable (current spec version 2025-11-25).

### Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| MCP spec is still evolving | Low | Core tool protocol is stable. Transport layer changes won't affect tool definitions. |
| stdout pollution | Medium | Scatter uses `logging` (writes to stderr by default). Verify no `print()` calls leak to stdout in library mode. |
| Large JSON responses | Medium | Use `--include-graph-topology=false` by default. For 500-project graphs, topology JSON can be 5MB+. Without topology, reports are <100KB. |
| Auth/secrets for AI features | Low | Scatter's AI features (summarization, impact narrative) need API keys. MCP server can pass env vars. Non-AI modes work without keys. |
| Process lifecycle | Low | stdio transport means server runs as long as the Claude session. No daemon management needed. |

---

## 5. Comparison: Skills vs. MCP Server

| Dimension | Skills | MCP Server |
|-----------|--------|-----------|
| **Time to ship** | 1 day | 3-4 days |
| **New code** | 0 lines (markdown only) | ~200 lines Python |
| **New dependencies** | None | `mcp[cli]` |
| **Works with Claude Code** | Yes | Yes |
| **Works with Claude Desktop** | No | Yes |
| **Works with custom agents** | No | Yes |
| **Team sharing** | Check `.claude/skills/` into git | Check `.mcp.json` into git |
| **Typed parameters** | No (free text arguments) | Yes (JSON Schema from type hints) |
| **Discoverability** | `/scatter-graph` slash command | Claude sees tool list automatically |
| **Maintenance** | Update markdown when CLI changes | Update Python when API changes |

### Verdict

**Do both, sequentially.** Skills first (1 day, immediate value), MCP server when any of these triggers appear:
- Another team wants scatter in Claude Desktop or VS Code
- You build a custom agent that needs scatter programmatically
- You want typed parameter validation (e.g., preventing invalid search scopes)

---

## 6. Adoption Strategy

### Phase 1: Grassroots (Week 1-2)

**Goal:** Get 3-5 engineers using scatter through Claude Code.

| Action | Owner |
|--------|-------|
| Check `.claude/skills/` into the monolith repo | You |
| Demo in team standup: "ask Claude about our dependency health" | You |
| Slack message with 3 example prompts engineers can copy-paste | You |
| Pair with one engineer on a real CSE scoping using scatter+Claude | You |

**Example prompts to share:**
```
"What's the blast radius of modifying dbo.sp_InsertPortalConfiguration?"
"Show me the dependency health of our codebase"
"Who depends on GalaxyWorks.Data?"
"/scatter-graph ."
```

**Why grassroots first:** Tool adoption at WEX follows a "show, don't tell" pattern. Engineers adopt tools they see working in real scenarios, not tools announced in email.

### Phase 2: Proof of Value (Week 3-4)

**Goal:** Quantify time saved, get management buy-in.

| Action | Detail |
|--------|--------|
| Track 5 CSE scoping sessions with scatter vs. without | Compare wall-clock time |
| Document one "scatter caught a missed dependency" story | Concrete risk avoided |
| Calculate hourly savings: `(manual_hours - scatter_hours) * team_size * hourly_rate` | Finance-friendly metric |
| Present at architecture review | 10-minute demo, focus on the dependency graph and health dashboard |

**The compelling narrative:**
> "Last quarter we spent 3 days scoping CSE-4872 because nobody knew GalaxyWorks.Data had 12 consumers through the stored procedure layer. Scatter found all 12 in 30 seconds and identified 2 circular dependencies that would have blocked the deployment."

### Phase 3: Standard Practice (Month 2-3)

**Goal:** Scatter becomes part of the development workflow.

| Action | Detail |
|--------|--------|
| Add scatter graph analysis to PR template | "Run `/scatter-graph .` and note any new cycles" |
| Include scatter output in CSE scoping documents | Standardize the format |
| Add `--fail-on cycles` to CI pipeline (Initiative 7) | Automated governance |
| Train new team members: "ask Claude about dependencies" | Onboarding integration |
| Build MCP server if cross-tool demand exists | Expand beyond Claude Code |

### Phase 4: Platform (Month 4+)

**Goal:** Scatter is infrastructure, not a personal tool.

| Action | Detail |
|--------|--------|
| Publish MCP server to internal package registry | Any team can connect |
| Baseline tracking: weekly coupling score snapshots | Trend analysis |
| Architecture review dashboard (HTML reports) | Leadership visibility |
| Extract as shared service if multiple repos need it | Beyond the monolith |

---

## 7. How to Advocate for Scatter

### To Engineers

**Don't say:** "We built a dependency analysis tool with coupling metrics and Tarjan's SCC algorithm."

**Do say:** "Before your next PR, ask Claude 'what's the blast radius of this change?' and it'll tell you exactly which pipelines to test."

Lead with the workflow improvement, not the technology.

### To Engineering Managers

**Frame:** Time and risk.

> "Our team spends ~8 hours per CSE on manual dependency tracing. Scatter reduces that to minutes. Last month that would have saved 32 engineer-hours across 4 CSEs. It also caught a circular dependency that would have caused a build failure in production."

**Metrics to track:**
- Hours saved per CSE scoping
- Dependencies caught that manual review missed
- Reduction in post-deployment hotfixes (longer term)

### To Architecture / Leadership

**Frame:** Modernization governance.

> "We can now measure our monolith's coupling score every sprint. The dependency graph shows exactly where the extraction boundaries are and how feasible each service extraction would be. The health dashboard flags architectural regressions before they compound."

**Artifacts to share:**
- Health dashboard output (observations, coupling scores)
- Mermaid dependency diagram (visual, embeddable in Confluence)
- Extraction feasibility scores per domain cluster
- Trend charts showing coupling changes over time (once baselines ship)

### To Other Teams

**Frame:** Zero-setup value.

> "It's already in the repo. Just open Claude Code and ask about dependencies. No installation, no API keys needed for the core analysis."

The Claude Code skills approach is critical here — it eliminates the "I'd have to learn a new CLI" objection entirely.

---

## 8. Technical Considerations

### Performance expectations

| Operation | Cold (first run) | Warm (cached graph) |
|-----------|-----------------|-------------------|
| `--graph` (sample projects) | ~2s | <0.5s |
| `--graph` (500-project repo) | 30-60s | <2s |
| `--target-project` | 5-15s | 5-15s (no cache) |
| `--sow` (with AI) | 10-30s | 10-30s (AI latency) |

The graph cache is the key performance lever. After the first build, subsequent `--graph` calls are nearly instant.

### JSON output size

| Mode | Typical size | With topology |
|------|-------------|---------------|
| Graph (10 projects) | ~5KB | ~15KB |
| Graph (500 projects) | ~100KB | ~5MB |
| Impact report | ~10KB | N/A |
| Consumer report | ~2KB | N/A |

The `--include-graph-topology` flag (default: off) keeps JSON output manageable. Claude can handle 100KB of structured JSON easily; 5MB is unnecessary for most questions.

### What scatter outputs today (JSON)

```json
{
  "metadata": { "scatter_version": "2.1.0", "timestamp": "...", "duration_seconds": 1.2 },
  "summary": { "node_count": 10, "edge_count": 25, "cycle_count": 0, "cluster_count": 3 },
  "top_coupled": [ { "project": "GalaxyWorks.Data", "coupling_score": 8.5, ... } ],
  "cycles": [],
  "metrics": { "GalaxyWorks.Data": { "fan_in": 4, "fan_out": 1, "instability": 0.2, ... } },
  "clusters": [ { "name": "GalaxyWorks", "projects": [...], "extraction_feasibility": "moderate" } ],
  "health_dashboard": {
    "avg_coupling_score": 3.2,
    "observations": [
      { "severity": "warning", "rule": "stable_core", "message": "GalaxyWorks.Data: stable core..." }
    ]
  }
}
```

This is already Claude-friendly. No additional formatting layer needed.

---

## 9. What's NOT Needed

| Idea | Why skip it |
|------|-----------|
| A web UI for scatter | Claude IS the UI. The whole point is natural-language interaction. |
| A scatter chatbot / custom GPT | Claude Code skills give you this for free, in the IDE. |
| Rewriting scatter in TypeScript for MCP | Python MCP SDK is first-class. No language change needed. |
| Real-time streaming of analysis progress | Scatter runs complete in <2s (cached). Streaming adds complexity for no UX gain. |
| Custom Claude model fine-tuning | Scatter's JSON is structured enough that any Claude model interprets it correctly. Skills provide the instructions. |

---

## 10. Recommended Next Steps (updated 2026-03-13)

Resequenced to align with adoption-driven priorities. Claude skills and
credibility fixes are the highest-leverage items across the entire scatter
roadmap — not just the Claude integration track.

1. **This week:** Fix `--summarize-consumers` wiring (~1 hour) — P0 credibility bug
2. **This week:** Integrate dependency graph into `--sow` / `--target-project` modes (~4 hours) — 5x perf win for the core workflow Claude will invoke
3. **This week:** Create 5 Claude Code skills in `.claude/skills/` (1 day) — collapses adoption barrier entirely
4. **This week:** Add `scatter pipelines` shortcut / deployment checklist mode (~2 hours) — #1 release-night use case
5. **Next week:** Demo to 2-3 team members (30 min each)
6. **Next week:** Use scatter+Claude on a real CSE scoping
7. **Month 2:** Ship Initiative 7 CI/CD exit codes (`--fail-on`) — makes scatter an architecture governance gate
8. **Month 2:** PR blast radius comments (GitHub/ADO) — second always-on touchpoint alongside skills
9. **Month 3:** Evaluate MCP server based on adoption patterns
10. **Month 3:** Baseline tracking + trend analysis (needs real usage history)

The fastest path to value is credibility fixes + skills + grassroots adoption.
CI/CD gates make it sticky. Everything else follows from engineers seeing it work.
