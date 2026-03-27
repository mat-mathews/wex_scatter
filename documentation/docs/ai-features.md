# AI Features

Scatter has three AI-powered features. All of them are optional. None of them run unless you ask for them. Each one is activated by a specific flag and requires a configured AI provider.

| Feature | Flag | Available In | What it does |
|---------|------|-------------|--------------|
| Consumer Summarization | `--summarize-consumers` | Git, Target, Sproc | Summarizes what each consumer file actually does with your code |
| Hybrid Type Extraction | `--enable-hybrid-git` | Git mode only | Identifies only the types whose body/signature actually changed in a diff |
| Impact Analysis | `--sow` / `--sow-file` | Impact mode | Parses a work request, traces blast radius, rates risk and complexity |

---

## AI Providers

Scatter uses a pluggable AI provider system. All AI calls go through an `AIProvider` protocol with a task router that selects providers per task type. This means you can swap providers via configuration without changing any analysis commands.

### WEX AI Platform (Primary — Coming Soon)

The **WEX AI Platform** is the company's centralized AI gateway. It handles rate limiting, security controls, model routing, and usage tracking for all internal AI consumers. This will be the default provider for Scatter once the API contract is finalized.

The provider is stubbed in the codebase and ready for integration. Configuration is already wired:

```bash
# Environment variable
export WEX_AI_API_KEY="your-wex-ai-key"

# CLI flag
scatter --sow "..." --search-scope . --wex-api-key "your-key"
```

```yaml
# .scatter.yaml
ai:
  default_provider: wex
  credentials:
    wex:
      api_key: "your-wex-ai-key"
```

Setting `default_provider: wex` will route all AI tasks through the WEX AI Platform. Configuration is ready — flip the switch when your team gets access.

### Google Gemini (Current Default)

The **Google Gemini** provider is the current working AI backend. All AI features are fully functional with Gemini. Set up your API key and go:

```bash
# Environment variable (recommended)
export GOOGLE_API_KEY="your-google-api-key"

# CLI flag
scatter --sow "..." --search-scope . --google-api-key "your-key"

# Config file (~/.scatter/config.yaml)
# ai:
#   credentials:
#     gemini:
#       api_key: "your-key"
```

### Future Providers

Additional providers are on the backlog. These will likely be routed through the WEX AI Platform rather than integrated directly, as the platform provides centralized rate limiting and security controls:

- **Claude (Anthropic)** — pending approval and/or WEX AI Platform integration
- Other models as the WEX AI Platform adds support

### Provider Configuration

Use `SCATTER_DEFAULT_PROVIDER` or `ai.default_provider` in config to switch providers. Use `ai.task_overrides` to route specific AI tasks to specific providers:

```yaml
ai:
  default_provider: gemini          # or "wex" when ready
  task_overrides:
    risk_assessment: wex            # route risk assessment to WEX AI Platform
    summarization: gemini           # keep summarization on Gemini
  credentials:
    gemini:
      api_key: ""
    wex:
      api_key: ""
```

---

## Consumer Summarization

**Flag:** `--summarize-consumers`

You run Scatter and it tells you 37 projects consume your library. Great. But what do those 37 projects *do* with it? You could open each one and read the code. Or you could let the AI do that for you.

When you pass `--summarize-consumers`, Scatter identifies the specific `.cs` files in each consumer that caused the match -- the ones with the `using` statement, the type reference, the sproc call. It sends each file to the configured AI provider and gets back a 2-3 sentence summary of what that file does.

This is most useful when you have dozens of consumers and need to triage which ones actually matter for your change, without opening every single file.

### Example

```bash
scatter --target-project ./GalaxyWorks.Data/GalaxyWorks.Data.csproj \
    --search-scope . \
    --class-name PortalDataService \
    --summarize-consumers \
    --google-api-key $GOOGLE_API_KEY
```

### Sample Console Output

```
Target: GalaxyWorks.Data (./GalaxyWorks.Data/GalaxyWorks.Data.csproj) (2 consumer(s))
    Type/Level: class PortalDataService
         -> Consumed by: MyGalaxyConsumerApp (./MyGalaxyConsumerApp/MyGalaxyConsumerApp.csproj)
           Summaries:
             File: Services/PortalSync.cs
              This file implements the PortalSync service, which orchestrates
              portal configuration synchronization by calling PortalDataService
              to read and write portal settings to the database.
```

### Sample JSON Output

The summaries land in the `ConsumerFileSummaries` field, keyed by relative file path:

```json
{
  "TargetProjectName": "GalaxyWorks.Data",
  "ConsumerProjectName": "MyGalaxyConsumerApp",
  "ConsumerFileSummaries": {
    "Services/PortalSync.cs": "This file implements the PortalSync service, which orchestrates portal configuration synchronization by calling PortalDataService to read and write portal settings to the database."
  }
}
```

---

## Hybrid Git Type Extraction

**Flag:** `--enable-hybrid-git`
**Available in:** Git mode only

### The Problem

By default, git mode uses regex to extract type declarations from changed files. Regex is fast and needs no API key. But it has a precision problem.

Say you change one line inside `PortalDataService` in a file that also declares `PortalDataModel`, `PortalConfig`, `IPortalRepository`, and `PortalConstants`. Regex sees the file changed and flags all five types. Your blast radius report now includes consumers of four types you didn't touch.

### The Solution

When you pass `--enable-hybrid-git`, Scatter sends the file content and the git diff to the AI provider. The LLM reads the diff, determines which type bodies and signatures actually changed, and returns only the affected type names.

Comment-only changes? Empty list -- no unnecessary downstream analysis. One-line fix inside a single class in a five-class file? You get exactly one type back.

If the AI call fails for any reason (network, rate limit, malformed response), Scatter falls back to regex silently. You always get a result.

### Comparison

| | Regex (default) | Hybrid (`--enable-hybrid-git`) |
|---|---|---|
| **Speed** | Instant | ~1-2s per file (API call) |
| **Precision** | All types in changed files | Only types whose body/signature changed |
| **Comment-only changes** | Flags all types in file | Returns empty list (correct) |
| **API key required** | No | Yes |
| **Failure mode** | N/A | Falls back to regex |

### Example

```bash
# Default regex extraction
scatter --branch-name feature/portal-fix --repo-path . --search-scope .

# Hybrid extraction -- compare the results
scatter --branch-name feature/portal-fix --repo-path . --search-scope . \
    --enable-hybrid-git --google-api-key $GOOGLE_API_KEY -v
```

With `-v`, you can see what the AI decided:

```
INFO: Hybrid analysis for GalaxyWorks.Data/PortalDataService.cs: 1 affected type(s)
      identified by LLM: {'PortalDataService'}
```

---

## Impact Analysis

**Flags:** `--sow` (inline text) or `--sow-file` (path to file)

Impact analysis mode takes a work request in plain English, uses AI to identify affected projects and stored procedures, then runs the full consumer analysis automatically. It layers on five AI tasks: parsing, risk assessment, coupling narrative, complexity estimation, and an impact narrative.

If any individual task fails, the report continues without that enrichment -- graceful degradation throughout.

### Codebase Index

When a dependency graph is available, Scatter automatically builds a compact **codebase index** and sends it to the LLM alongside the SOW. The index lists every project name, its types, and stored procedures in a token-efficient one-line-per-project format. This grounds the LLM in what actually exists in the codebase, so it maps domain language (e.g., "portal configuration workflow") to real artifacts (e.g., `GalaxyWorks.Data`, `PortalDataService`) instead of hallucinating names.

After the LLM responds, any target names not found in the index have their confidence automatically halved.

Use `--dump-index --search-scope .` to inspect the index the LLM sees. Use `--sow-min-confidence` to filter low-confidence targets from the analysis.

The full details on using impact analysis mode, interpreting the output, and tuning the depth/scope are in the [Impact Analysis usage page](usage/impact-analysis.md).

---

## Graph Metrics (Not AI)

**No flag needed** -- this is automatic.

Graph metrics are often confused with AI features, but they are pure structural analysis -- no API key, no AI calls. When Scatter runs any analysis mode, it automatically loads or builds the dependency graph and enriches every consumer result with:

- **coupling_score** -- weighted sum of all edge weights touching this project
- **fan_in** / **fan_out** -- how many projects depend on it vs. how many it depends on
- **instability** -- fan_out / (fan_in + fan_out), ranging 0.0 to 1.0
- **in_cycle** -- whether this project participates in a circular dependency

These metrics appear in all output formats (console, JSON, CSV, markdown).

Use `--no-graph` to disable graph loading entirely if you want faster runs and don't care about structural metrics.

### Sample Console Output

```
         -> Consumed by: MyGalaxyConsumerApp (./MyGalaxyConsumerApp/MyGalaxyConsumerApp.csproj)
           Graph: coupling=4.60, fan-in=2, fan-out=1, instability=0.333, in-cycle=no
```

When a consumer project exists outside the graph's search scope:

```
           Graph: (not in graph)
```

> **How this works:** AI calls go through an `AIProvider` protocol with a task router that selects providers per task type. All calls are structured JSON in, structured JSON out. Graph metrics are computed from the dependency graph with no AI involvement. See [Architecture Overview](reference/architecture.md) for the provider system and graph engine.
