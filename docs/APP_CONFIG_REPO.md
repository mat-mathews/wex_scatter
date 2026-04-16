# Implementation Plan: `--app-config-path` Full Pipeline Resolution

## Executive Summary

The current implementation reads only one thing from the config repo: the subdirectory names inside `cdh-batchprocesses-az-cd/production/`. The rest of the pipeline map still requires a manually-maintained `--pipeline-csv`. This plan describes a complete crawler that eliminates the CSV dependency, derives pipeline mappings automatically from the 370-pipeline config repo, handles all structural variants (single-app, batch fan-out, nav fan-out), and slots into the existing scatter architecture without breaking any current behaviour.

---

## 1. What Exists Today

```
--app-config-path C:\_\health-benefits-app-config
        │
        └─► map_batch_jobs_from_config_repo()   [v1_bridge.py]
                │
                ├─ reads: cdh-batchprocesses-az-cd/production/ subdirectory names
                └─ produces: {"cdh-batchprocesses-az-cd": ["AccountingProcessor", ...]}

--pipeline-csv pipeline_to_app_mapping.csv
        │
        └─► load_pipeline_csv()                 [modes/setup.py]
                │
                ├─ reads: "Application Name","Pipeline Name" CSV
                └─ produces: {"SolutionStem": "cdh-employerportal-az-cd", ...}
```

The gap: **the CSV is manually maintained and covers only what someone remembered to put in it**. The config repo contains authoritative, machine-readable mappings for every one of the 370 pipelines.

---

## 2. What's Actually in the Config Repo

### 2.1 Directory Structure Taxonomy

After crawling the real repo, there are four structural patterns:

**Pattern A — Standard single-app pipeline (~160 pipelines)**

```
cdh-employerportal-az-cd/
  production/
    wexhealth.host.json          ← AppName = "WexHealth.Apps.Web.EmployerPortal"
    web.config                   ← <aspNetCore arguments=".\WexHealth.Apps.Web.Employer.Portal.dll">
    App_Data/
      iis_settings.json
  qa/
    wexhealth.host.json
  staging/
  uat/
  ...
```

**Pattern B — Batch fan-out pipeline (1 pipeline, 57 jobs)**

```
cdh-batchprocesses-az-cd/
  production/
    AccountingProcessor/
      wexhealth.host.json        ← AppName = "WEXHealth.CDH.BatchProcesses.HSA.AccountingProcessor"
      Lighthouse1.Apps.Console.AccountingProcessor.exe.config   ← assembly name in filename
      appSettings.json
    AuthorizationProcessor/
      wexhealth.host.json
      Lighthouse1.Apps.Console.AuthorizationProcessor.exe.config
    ...57 subdirectories total...
```

**Pattern C — Nav fan-out (25 pipelines, 1 app per pipeline)**

```
cdh-exportscheduler-nav1-az-cd/
  production/
    wexhealth.host.json          ← AppName = "Lighthouse1.Exports.Scheduler"  ← SAME for all 25
...
cdh-exportscheduler-nav25-az-cd/
  production/
    wexhealth.host.json          ← AppName = "Lighthouse1.Exports.Scheduler"  ← SAME
```

Similarly for `cdh-cdex-fileloader-navN-az-cd` (17 variants) and `pts-cdb-jobqueuejqN-az-cd` (14 variants).

**Pattern D — No `wexhealth.host.json` (~150 pipelines)**

```
pts-cdb-carrierfile-az-cd/
  production/
    App_Data/
      iis_settings.json          ← siteName, appPool — not useful for matching
    web.config                   ← may contain DLL arg or may not exist
```

These pipelines are older (`pts-*`, `direct-*`, `wexhealth.card-*`) and lack the host.json convention. App names must be derived from the pipeline name itself or from `web.config` DLL argument parsing.

---

### 2.2 Data Sources and What Each Provides

| File | Field | Example value | Reliability |
|---|---|---|---|
| `wexhealth.host.json` | `HostResources.AppName` | `"WexHealth.Apps.Web.EmployerPortal"` | **High** — used as the key to request runtime config; authoritative |
| `web.config` | `<aspNetCore arguments=".\X.dll">` | `WexHealth.Apps.Web.Employer.Portal.dll` | High — assembly filename |
| `*.exe.config` filename | filename stem | `Lighthouse1.Apps.Console.AccountingProcessor` | High — IS the assembly name |
| Pipeline dir name | directory stem | `cdh-employerportal-az-cd` | Medium — heuristic only |
| `App_Data/iis_settings.json` | `siteName`, `appPool` | `"newemplportal"`, `"NewEmplPortal"` | Low — IIS identity, not assembly name |

The `AppName` in `wexhealth.host.json` is the most valuable field. It is the string the app uses to identify itself to the WEX configuration service — which means it directly corresponds to the `<AssemblyName>` (or defaulted project name) in the source `.csproj`.

**Critical caveat:** `wexhealth.host.json` files use JavaScript `//` comments which are illegal JSON. They must be stripped before parsing.

---

### 2.3 The AppName → Project Name Mapping Problem

The relationship between the deployed `AppName` and the source project stem is close but not always exact:

| Pipeline | AppName (from host.json) | Actual assembly in web.config | Likely .csproj stem |
|---|---|---|---|
| `cdh-employerportal-az-cd` | `WexHealth.Apps.Web.EmployerPortal` | `WexHealth.Apps.Web.Employer.Portal.dll` | `WexHealth.Apps.Web.Employer.Portal` |
| `cdh-services-az-cd` | `Lighthouse1.ParticipantService` | *(no web.config DLL)* | `Lighthouse1.ParticipantService` |
| `cdh-dataapi-az-cd` | `WexHealth.CDH.Apps.Web.Data.Api` | — | `WexHealth.CDH.Apps.Web.Data.Api` |
| `cdh-batchprocesses-az-cd` / `AccountingProcessor` | `WEXHealth.CDH.BatchProcesses.HSA.AccountingProcessor` | `Lighthouse1.Apps.Console.AccountingProcessor` (exe.config) | `Lighthouse1.Apps.Console.AccountingProcessor` |

Observed patterns:
- AppName is usually the **namespace prefix** of the entry-point assembly
- AppName and assembly name are often the same but sometimes differ in casing or word boundaries (`.Employer.Portal` vs `.EmployerPortal`)
- The exe.config filename IS the assembly name — no transformation needed
- The web.config DLL argument strips `.dll` to get the assembly name

Matching strategy must handle all three with a **priority cascade**.

---

## 3. New Module: `scatter/scanners/config_repo_scanner.py`

### 3.1 Data Model

```python
@dataclass
class DeployedApp:
    pipeline_name: str          # e.g., "cdh-employerportal-az-cd"
    host_app_name: str | None   # from wexhealth.host.json HostResources.AppName
    assembly_name: str | None   # from web.config DLL arg or exe.config filename
    job_name: str | None        # only for batch jobs: subdirectory name, e.g. "AccountingProcessor"
    environment: str            # "production" (crawler only reads production)
    discovery_source: str       # "host_json", "web_config_dll", "exe_config", "pipeline_heuristic"

@dataclass
class NavGroup:
    canonical_name: str         # e.g., "cdh-exportscheduler-nav"
    pipelines: list[str]        # all navN variants
    app_name: str               # shared AppName across all instances

@dataclass
class ConfigRepoCrawlResult:
    apps: list[DeployedApp]
    batch_pipeline_to_jobs: dict[str, list[str]]   # pipeline → [job_names]
    app_name_to_pipelines: dict[str, list[str]]    # AppName → [pipeline_names]
    assembly_to_pipelines: dict[str, list[str]]    # assembly_name → [pipeline_names]
    pipeline_to_apps: dict[str, list[DeployedApp]] # pipeline → apps
    nav_groups: list[NavGroup]                     # detected fan-out groups
    unresolved_pipelines: list[str]                # had no usable app name signals
    stats: CrawlStats

@dataclass
class CrawlStats:
    total_pipeline_dirs: int
    resolved_via_host_json: int
    resolved_via_web_config: int
    resolved_via_exe_config: int
    resolved_via_heuristic: int
    unresolved: int
    batch_jobs: int
    nav_groups: int
```

### 3.2 The `//`-Comment JSON Problem

`wexhealth.host.json` files contain JavaScript-style `//` comments that are not valid JSON:

```json
{
  "HostResources": {
    "AppName": "WexHealth.Apps.Web.EmployerPortal",
    "RollingFileSize": "100000000", //100MB
    "Serilog": {
      "Using": [
        //ASP.NET WebForms (SerilogWeb.Classic)
        //"SerilogWeb.Classic"
      ],
```

Do NOT use a general JSON parser directly. Use a targeted regex extractor:

```python
# Fast path: extract AppName without full JSON parse
_APP_NAME_RE = re.compile(r'"AppName"\s*:\s*"([^"]+)"')

def _extract_app_name(content: str) -> str | None:
    m = _APP_NAME_RE.search(content)
    return m.group(1) if m else None
```

This sidesteps the comment problem entirely and is more robust to formatting variations. It correctly handles the `{AppName}` placeholder (which appears in `Scope` fields, not in the AppName field itself).

---

### 3.3 Crawl Algorithm

```
scan_config_repo(repo_path: Path, environment: str = "production") -> ConfigRepoCrawlResult

For each child of repo_path that is a directory:
    pipeline_dir = child
    pipeline_name = child.name

    # Skip non-pipeline directories
    if pipeline_name starts with "." → skip
    if pipeline_name in SKIP_DIRS → skip  # GeneratedIisSettingsFiles, MachineConfigurationsSummarizer, etc.

    env_dir = pipeline_dir / environment

    # Detect pipeline type
    if env_dir does not exist → record as unresolved, continue

    subdirs = [d for d in env_dir.iterdir() if d.is_dir()
               and d.name not in ("App_Data", "PostDeployTests")]

    if subdirs contain wexhealth.host.json files (each subdir has its own):
        # Pattern B: Batch fan-out
        handle_batch_pipeline(pipeline_name, env_dir, subdirs)
    else:
        # Pattern A or C or D: single-app or fan-out
        handle_single_app_pipeline(pipeline_name, env_dir)
```

**`handle_batch_pipeline(pipeline_name, env_dir, job_dirs)`**

```
job_names = []
for job_dir in sorted(job_dirs):
    job_name = job_dir.name
    job_names.append(job_name)

    # Primary: wexhealth.host.json in job dir
    host_json = job_dir / "wexhealth.host.json"
    host_app_name = _extract_app_name(host_json.read_text()) if host_json.exists() else None

    # Secondary: *.exe.config filename → assembly name
    # "Lighthouse1.Apps.Console.AccountingProcessor.exe.config"
    #   .stem → "Lighthouse1.Apps.Console.AccountingProcessor.exe"
    #   .stem → "Lighthouse1.Apps.Console.AccountingProcessor"  ✓
    exe_configs = list(job_dir.glob("*.exe.config"))
    assembly_name = Path(exe_configs[0].stem).stem if exe_configs else None

    record DeployedApp(pipeline_name, host_app_name, assembly_name, job_name=job_name, ...)

record batch_pipeline_to_jobs[pipeline_name] = job_names
```

**`handle_single_app_pipeline(pipeline_name, env_dir)`**

```
# Primary: wexhealth.host.json at env_dir level
host_json = env_dir / "wexhealth.host.json"
host_app_name = None
source = None
if host_json.exists():
    host_app_name = _extract_app_name(host_json.read_text())
    source = "host_json"

# Secondary: web.config DLL argument
assembly_name = None
web_config = env_dir / "web.config"
if not web_config.exists():
    web_config = env_dir / "Web.Config"  # case-insensitive fallback
if web_config.exists():
    content = web_config.read_text(errors="ignore")
    m = re.search(r'arguments="[^"]*?([A-Za-z][A-Za-z0-9.]+)\.dll"', content)
    if m:
        assembly_name = m.group(1)
        source = source or "web_config_dll"

# Tertiary: *.exe.config in env_dir (non-batch pipelines with exe configs)
if not host_app_name and not assembly_name:
    exe_configs = list(env_dir.glob("*.exe.config"))
    if exe_configs:
        assembly_name = Path(exe_configs[0].stem).stem
        source = "exe_config"

# Quaternary: pipeline name heuristic
if not host_app_name and not assembly_name:
    assembly_name = _heuristic_from_pipeline_name(pipeline_name)
    source = "pipeline_heuristic"

record DeployedApp(pipeline_name, host_app_name, assembly_name, job_name=None, ...)
```

---

### 3.4 Pipeline Name Heuristic (Fallback)

For ~150 pipelines without `wexhealth.host.json`, extract a human-readable name from the pipeline directory name as a last resort:

```python
_PIPELINE_SUFFIX_RE = re.compile(r'-(az-cd|az-cicd|cicd|cd|mws)$')
_NAV_SUFFIX_RE      = re.compile(r'-nav\d+-')

def _heuristic_from_pipeline_name(pipeline_name: str) -> str | None:
    name = _PIPELINE_SUFFIX_RE.sub('', pipeline_name)   # strip trailing -az-cd etc.
    name = _NAV_SUFFIX_RE.sub('-', name)                 # collapse navN variants
    parts = name.split('-')
    if len(parts) < 2:
        return None
    return name   # caller uses this for display, not for programmatic matching
```

The heuristic is labeled explicitly (`discovery_source = "pipeline_heuristic"`) so callers can weight it lower in matching.

---

### 3.5 Nav Fan-Out Detection

After the crawl, detect nav fan-out groups by clustering pipeline names that match the pattern `{prefix}-nav\d+-az-cd`:

```python
_NAV_PATTERN = re.compile(r'^(.+?)-nav\d+(-az-cd|$)')

def _detect_nav_groups(apps: list[DeployedApp]) -> list[NavGroup]:
    groups: dict[str, list[DeployedApp]] = defaultdict(list)
    for app in apps:
        m = _NAV_PATTERN.match(app.pipeline_name)
        if m:
            groups[m.group(1)].append(app)
    result = []
    for canonical, group_apps in groups.items():
        if len(group_apps) > 1:
            names = {a.host_app_name for a in group_apps}
            app_name = names.pop() if len(names) == 1 else None
            result.append(NavGroup(
                canonical_name=canonical,
                pipelines=[a.pipeline_name for a in group_apps],
                app_name=app_name or group_apps[0].host_app_name or "",
            ))
    return result
```

The same pattern detects: `cdh-exportscheduler-navN-az-cd` (25), `cdh-cdex-fileloader-navN-az-cd` (17), `pts-cdb-jobqueuejqN-az-cd` (14).

---

## 4. New Module: `scatter/scanners/config_repo_matcher.py`

This module handles the matching between a source project name (`.csproj` stem) and the crawl result.

### 4.1 Normalized Name Representation

All names — project stems, AppNames, assembly names — are normalized before comparison:

```python
_NORM_RE = re.compile(r'[-_\s]')

def normalize(name: str) -> str:
    """Lowercase, collapse separators to dots, remove common org prefixes."""
    name = name.lower()
    name = _NORM_RE.sub('.', name)       # dashes and underscores → dots
    for prefix in ('wexhealth.', 'wex.', 'lighthouse1.', 'lh1.'):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name

# Examples:
# "WexHealth.Apps.Web.EmployerPortal"                → "apps.web.employerportal"
# "WexHealth.Apps.Web.Employer.Portal"               → "apps.web.employer.portal"
# "WEXHealth.CDH.BatchProcesses.HSA.AccountingProcessor" → "cdh.batchprocesses.hsa.accountingprocessor"
# "Lighthouse1.Apps.Console.AccountingProcessor"     → "apps.console.accountingprocessor"
```

### 4.2 Match Priority Cascade

Given a project stem (from a `.csproj` file), match it to pipelines in this priority order:

**Level 1 — Exact match (normalized)**
```python
norm_project = normalize(project_stem)
if norm_project in crawl_result.normalized_assembly_index:
    return crawl_result.normalized_assembly_index[norm_project]
```

**Level 2 — Token Jaccard similarity**

Assembly names are often suffixed versions of app names or vice versa. The project stem
`Lighthouse1.Apps.Console.AccountingProcessor` should match
`AppName = WEXHealth.CDH.BatchProcesses.HSA.AccountingProcessor` because the final token
`accountingprocessor` is shared.

```python
project_tokens = set(norm_project.split('.'))
for norm_app_name, apps in crawl_result.normalized_host_json_index.items():
    app_tokens = set(norm_app_name.split('.'))
    intersection = project_tokens & app_tokens
    union = project_tokens | app_tokens
    if len(union) > 0 and len(intersection) / len(union) >= 0.5:
        candidates.append((apps, len(intersection) / len(union)))
```

**Level 3 — Final token match**

For cases like `Lighthouse1.Exports.Scheduler` (AppName) vs `Lighthouse1.Apps.Export.Scheduler`
(project): match on the last 2 tokens.

```python
project_tail = norm_project.split('.')[-2:]
for norm_name, apps in crawl_result.normalized_host_json_index.items():
    app_tail = norm_name.split('.')[-2:]
    if project_tail == app_tail:
        candidates.append(apps)
```

**Level 4 — No match → return empty**

Unmatched projects don't get pipeline assignments. Better to return nothing than a wrong pipeline.

### 4.3 Concrete Matching Examples

| Project stem | AppName (host.json) | Assembly (web/exe config) | Match level | Result |
|---|---|---|---|---|
| `WexHealth.Apps.Web.Employer.Portal` | `WexHealth.Apps.Web.EmployerPortal` | `WexHealth.Apps.Web.Employer.Portal` | L1 (assembly exact) | `cdh-employerportal-az-cd` |
| `Lighthouse1.ParticipantService` | `Lighthouse1.ParticipantService` | — | L1 (host.json exact) | `cdh-services-az-cd` |
| `Lighthouse1.Apps.Console.AccountingProcessor` | `WEXHealth.CDH.BatchProcesses.HSA.AccountingProcessor` | `Lighthouse1.Apps.Console.AccountingProcessor` | L1 (assembly exact) | `cdh-batchprocesses-az-cd` / `AccountingProcessor` |
| `Lighthouse1.Apps.Export.SchedulerService` | `Lighthouse1.Exports.Scheduler` | — | L3 (tail: `scheduler`) | `cdh-exportscheduler-navN-az-cd ×25` |
| `WexHealth.CDH.FileImport.FileLoaderService` | `WexHealth.CDH.FileImport.FileLoaderService` | — | L1 (host.json exact) | `cdh-cdex-fileloader-navN-az-cd ×17` |

---

## 5. Integration into Existing Scatter Code

### 5.1 What changes in `modes/setup.py`

**Current `load_batch_jobs`:**
```python
def load_batch_jobs(args) -> Dict[str, List[str]]:
    from scatter.compat.v1_bridge import map_batch_jobs_from_config_repo
    batch_job_map = {}
    if args.app_config_path:
        batch_job_map = map_batch_jobs_from_config_repo(app_config_repo_path)
    return batch_job_map
```

**New `load_from_config_repo`** (replaces `load_batch_jobs`):
```python
def load_from_config_repo(
    args,
) -> tuple[Dict[str, List[str]], Dict[str, str], ConfigRepoCrawlResult | None]:
    """
    Crawl the config repo and return:
    - batch_job_map:          {pipeline_name: [job_names]}       (same shape as before)
    - derived_pipeline_map:   {assembly_name: pipeline_name}     (augments --pipeline-csv)
    - crawl_result:           full structured result for richer matching
    """
    if not args.app_config_path:
        return {}, {}, None

    from scatter.scanners.config_repo_scanner import scan_config_repo

    app_config_path = Path(args.app_config_path).resolve(strict=True)
    logging.info(f"\n--- Crawling config repo: {app_config_path} ---")

    result = scan_config_repo(app_config_path, environment="production")

    logging.info(
        f"Crawl complete: {result.stats.total_pipeline_dirs} pipelines, "
        f"{len(result.apps)} deployed apps, "
        f"{result.stats.batch_jobs} batch jobs, "
        f"{len(result.nav_groups)} nav fan-out groups, "
        f"{result.stats.unresolved} unresolved"
    )

    batch_job_map = result.batch_pipeline_to_jobs

    derived_pipeline_map: Dict[str, str] = {}
    for app in result.apps:
        name = app.assembly_name or app.host_app_name
        if name and app.pipeline_name:
            derived_pipeline_map[name] = app.pipeline_name

    return batch_job_map, derived_pipeline_map, result
```

**In `__main__.py`**, merge the derived map with the CSV (CSV takes precedence):

```python
batch_jobs, config_repo_pipeline_map, crawl_result = load_from_config_repo(args)
pipeline_map = load_pipeline_csv(paths.pipeline_csv)
pipeline_map = {**config_repo_pipeline_map, **pipeline_map}  # CSV overrides repo
```

This merge strategy is important: the CSV takes precedence over the crawled data, so operators can still override specific mappings manually.

### 5.2 What changes in `core/models.py` — `ModeContext`

Add an optional `crawl_result` field so that downstream code can access the full structured data:

```python
@dataclass
class ModeContext:
    ...
    config_repo_crawl: Optional[ConfigRepoCrawlResult] = None  # NEW
```

### 5.3 What changes in `compat/v1_bridge.py` — `_build_consumer_results`

The batch job verification currently hardcodes one pipeline name:

```python
# Before (hardcoded):
if pipeline_name == "cdh-batchprocesses-az-cd":
    all_known_jobs = batch_job_map.get(pipeline_name, [])

# After (generalized — any pipeline in batch_job_map is a batch pipeline):
if pipeline_name in batch_job_map:
    all_known_jobs = batch_job_map[pipeline_name]
    batch_job_verification = "Verified" if consumer_name_stem in all_known_jobs else "Unverified"
```

This makes batch verification work for any multi-job pipeline, not just the one that was hardcoded.

---

## 6. Output Data Structures — What Scatter Consumes

### 6.1 `batch_job_map` (unchanged shape)

```python
{
  "cdh-batchprocesses-az-cd": [
    "AccountingProcessor", "ArchiveLogFiles", "AuthorizationProcessor",
    "AutomaticRolloverProcessor", ...,  # 57 entries
  ],
  "cdh-batchprocesses-cd": [...],  # legacy variant, if it has the same structure
}
```

### 6.2 `derived_pipeline_map` (new — augments CSV)

```python
{
  # From host_json AppName → pipeline
  "WexHealth.Apps.Web.EmployerPortal":           "cdh-employerportal-az-cd",
  "Lighthouse1.ParticipantService":              "cdh-services-az-cd",
  "WexHealth.CDH.Apps.Web.Data.Api":             "cdh-dataapi-az-cd",
  "TaskHost":                                    "cdh-taskhost-az-cd",
  "WexHealth.Apps.Web.EmployerPortal.Auth":      "cdh-authservice-az-cd",

  # From assembly name (web.config DLL / exe.config filename)
  "WexHealth.Apps.Web.Employer.Portal":          "cdh-employerportal-az-cd",
  "Lighthouse1.Apps.Console.AccountingProcessor": "cdh-batchprocesses-az-cd",
  "Lighthouse1.Apps.Console.AuthorizationProcessor": "cdh-batchprocesses-az-cd",
  ...

  # Nav fan-out: each navN pipeline maps to the same app name.
  # The flat map uses the first (alphabetically sorted) pipeline as representative.
  # Use crawl_result.app_name_to_pipelines for the full 1:many relationship.
  "Lighthouse1.Exports.Scheduler": "cdh-exportscheduler-nav1-az-cd",
}
```

### 6.3 `crawl_result.app_name_to_pipelines` (1:many — correct for nav fan-out)

```python
{
    "Lighthouse1.Exports.Scheduler": [
        "cdh-exportscheduler-nav1-az-cd",
        "cdh-exportscheduler-nav2-az-cd",
        ...
        "cdh-exportscheduler-nav25-az-cd",   # all 25 pipelines
    ],
    "WexHealth.CDH.FileImport.FileLoaderService": [
        "cdh-cdex-fileloader-nav1-az-cd",
        ...
        "cdh-cdex-fileloader-nav17-az-cd",   # all 17 pipelines
    ],
    "WexHealth.Apps.Web.EmployerPortal": [
        "cdh-employerportal-az-cd",          # single pipeline, list of 1
    ],
    ...
}
```

---

## 7. Edge Cases and How to Handle Them

### 7.1 Nav Fan-Out in Output

When a change affects `Lighthouse1.Exports.Scheduler`, it affects all 25 nav pipelines.

**Option A (Phase 1 — simple):** Show all 25 rows. No change to reporters required. Correct, if noisy.

**Option B (Phase 2 — better):** Collapse nav groups in the reporter using the `NavGroup` list from `crawl_result`. Emit one summary row per group:
```
Lighthouse1.Exports.Scheduler  →  cdh-exportscheduler-nav{1..25}-az-cd  ×25
```
Defer Option B to Phase 2.

### 7.2 Nav Fan-Out in the Flat `derived_pipeline_map`

A single `AppName` → multiple pipeline names cannot be represented in `Dict[str, str]`. Pick the first alphabetically sorted pipeline as the representative for the flat map. This is a known lossy simplification, noted in the log output. The full `crawl_result.app_name_to_pipelines` is the correct source for any code that needs all affected pipelines.

### 7.3 Case Sensitivity in AppName

Real data shows mixed casing: `WEXHealth.CDH.BatchProcesses...` vs `WexHealth.CDH...`. Normalize to lowercase for all lookups. Never compare AppNames case-sensitively.

### 7.4 Environment Selection

Only crawl `production/` by default. The `environment` parameter to `scan_config_repo` lets callers request `qa` or `staging` for pre-production blast radius analysis. The majority of useful data is in `production/`.

### 7.5 Batch Pipeline Variants (`-cd` vs `-az-cd`)

Both `cdh-batchprocesses-az-cd` and `cdh-batchprocesses-cd` exist. The crawler handles both identically — batch detection keys on whether subdirectories inside `production/` each contain their own `wexhealth.host.json`, not on the pipeline name.

### 7.6 `wexhealth.host.json` `{AppName}` Placeholder Collision

The `AppName` value is always a real string. The `{AppName}` placeholder appears only in `Scope` fields:
```json
{"Context": "AppSettings", "Scope": "{AppName}"}
```
The regex `r'"AppName"\s*:\s*"([^"]+)"'` matches only the `AppName` key and will never match a `Scope` value.

### 7.7 Pipelines Without Any Useful Signal

~150 pipelines (`pts-*`, `direct-*`, `wexhealth.card-*`) have no `wexhealth.host.json`. These belong to the COBRA/Direct Billing and Card product lines which likely live in separate source repositories. Scatter is analyzing a specific code scope, so these pipelines will almost never match any project in the source tree — returning empty for them is correct.

### 7.8 Duplicate AppNames Across Different Pipelines

Some apps are deployed to both `-az-cd` and plain `-cd` pipelines with the same `AppName`. Both appear in `app_name_to_pipelines[app_name]`. This is correct — both pipelines are affected.

---

## 8. Logging and Diagnostics

The crawl produces structured output visible with `--verbose`:

```
--- Crawling config repo: C:\_\health-benefits-app-config ---
Scanning 370 pipeline directories...

Pattern A (single-app):    214 pipelines
Pattern B (batch fan-out):   2 pipelines  (cdh-batchprocesses-az-cd: 57 jobs, cdh-batchprocesses-cd: 52 jobs)
Pattern C (nav fan-out):     4 groups     (exportscheduler ×25, cdex-fileloader ×17, jobqueue ×14, ...)
Pattern D (no host.json):  148 pipelines

Resolution sources:
  wexhealth.host.json:     187 pipelines
  web.config DLL arg:       31 pipelines
  exe.config filename:       4 pipelines
  pipeline name heuristic:  61 pipelines
  unresolved:               52 pipelines

Nav fan-out groups detected:
  cdh-exportscheduler-nav{1..25}-az-cd   → Lighthouse1.Exports.Scheduler (×25)
  cdh-cdex-fileloader-nav{1..17}-az-cd   → WexHealth.CDH.FileImport.FileLoaderService (×17)
  pts-cdb-jobqueue-jq{1..14}-az-cd       → [unknown] (×14)

Batch jobs:
  cdh-batchprocesses-az-cd:  57 jobs
  cdh-batchprocesses-cd:     52 jobs

Crawl complete in 0.3s. 370 pipelines → 289 mapped apps.
```

---

## 9. File Layout

```
scatter/
  scanners/
    config_repo_scanner.py     NEW  — crawl algorithm, data model, nav group detection
    config_repo_matcher.py     NEW  — normalize(), match_project_to_pipeline()
  modes/
    setup.py                   MOD  — load_from_config_repo() replaces load_batch_jobs()
  __main__.py                  MOD  — call load_from_config_repo(), merge pipeline maps
  core/
    models.py                  MOD  — add config_repo_crawl field to ModeContext
  compat/
    v1_bridge.py               MOD  — generalize batch verification check
```

No new dependencies. `re`, `json`, `pathlib`, `dataclasses`, `logging` — all stdlib.

---

## 10. Migration Path

### Phase 1 (this plan)
- `scan_config_repo` crawler producing `ConfigRepoCrawlResult`
- `derived_pipeline_map` merged with CSV in `__main__.py`
- Generalized batch verification in `v1_bridge.py`
- `--pipeline-csv` still works and still overrides crawled data

### Phase 2 (follow-on)
- Direct-matching path in `_build_consumer_results`: use `crawl_result.app_name_to_pipelines` for richer 1:many pipeline resolution, bypassing the solution→CSV chain
- Nav fan-out collapsing in reporters (show `×25` instead of 25 rows)
- `--dump-config-repo` flag: run crawler, print mapping table, exit — useful for debugging

### Phase 3 (long-term)
- Cache the crawl result alongside the graph cache (cheap to build ~0.3s, but worth caching for CI)
- Extend crawler to `qa` and `staging` environments for pre-production blast radius
- `scatter --generate-pipeline-csv --app-config-path ...` — generate the CSV from the crawler on demand

---

## 11. Tests to Write

Follow the existing pattern of real filesystem fixtures.

**Unit tests (`tests/unit/test_config_repo_scanner.py`)**:
```
test_extract_app_name_with_comments()        — regex handles // comments correctly
test_extract_app_name_json_placeholder()     — {AppName} in Scope is not matched
test_detect_batch_pipeline()                 — subdir detection logic
test_detect_nav_groups()                     — clustering: navN → NavGroup
test_normalize()                             — WEXHealth.CDH.Foo → cdh.foo
test_double_stem_exe_config()               — "X.exe.config" → stem → "X.exe" → stem → "X"
test_crawl_stats_totals()                    — stats add up correctly
```

**Integration tests (`tests/integration/test_config_repo_scanner_integration.py`)**

Minimal fixture directory:
```
tests/fixtures/config_repo/
  cdh-employerportal-az-cd/
    production/
      wexhealth.host.json      ← AppName with //comment
      web.config               ← DLL argument
  cdh-batchprocesses-az-cd/
    production/
      AccountingProcessor/
        wexhealth.host.json
        Lighthouse1.Apps.Console.AccountingProcessor.exe.config  ← empty file, name is the signal
      AuthorizationProcessor/
        wexhealth.host.json
  cdh-exportscheduler-nav1-az-cd/
    production/
      wexhealth.host.json
  cdh-exportscheduler-nav2-az-cd/
    production/
      wexhealth.host.json
  pts-cdb-carrierfile-az-cd/
    production/
      App_Data/
        iis_settings.json
```

Test cases:
```
test_crawl_single_app()              — Pattern A works end-to-end
test_crawl_batch_pipeline()          — Pattern B: 2 jobs, both resolved
test_crawl_nav_group()               — Pattern C: 2 nav pipelines grouped
test_crawl_no_host_json()            — Pattern D: unresolved or fallback
test_crawl_derives_pipeline_map()    — derived_pipeline_map has correct entries
test_crawl_batch_job_map()           — batch_job_map backward-compatible shape
```