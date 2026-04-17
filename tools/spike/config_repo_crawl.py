#!/usr/bin/env python3
"""APP_CONFIG Repo Crawler — Evidence Pass.

Read-only crawl of the health-benefits-app-config repository that produces
auditable reports about pipeline structure, signal availability, and
matcher-cascade behavior. See docs/APP_CONFIG_REPO_SPIKE.md for full spec.

THROWAWAY SPIKE. Nothing here is imported by scatter. Stdlib only.

Usage:
    python tools/spike/config_repo_crawl.py \\
        --app-config-path <path> \\
        --hand-csv <csv> \\
        --output-dir <dir> \\
        [--source-stems <txt>] \\
        [--prev-snapshot <csv>] \\
        [--redact]
"""

from __future__ import annotations

import argparse
import csv
import hmac
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Constants & regexes
# ---------------------------------------------------------------------------

_APP_NAME_RE = re.compile(r'"AppName"\s*:\s*"([^"]+)"')
_LOWERCASE_APPNAME_RE = re.compile(r'"appName"\s*:\s*"([^"]+)"')
_DLL_ARG_RE = re.compile(r'arguments="[^"]*?([A-Za-z][A-Za-z0-9.]+)\.dll"', re.IGNORECASE)
_NAV_RE = re.compile(r"^(.+?)-nav\d+(-az-cd|$)")
_PIPELINE_SUFFIX_RE = re.compile(r"-(az-cd|az-cicd|cicd|cd|mws)$", re.IGNORECASE)
_COMMENT_LINE_RE = re.compile(r"^\s*//", re.MULTILINE)
_APPNAME_PLACEHOLDER_RE = re.compile(r"\{AppName\}")
_NORM_SEP_RE = re.compile(r"[-_\s]")

SKIP_DIRS = {
    "GeneratedIisSettingsFiles",
    "MachineConfigurationsSummarizer",
    ".git",
    ".github",
    ".vs",
}
ENV_SKIP = {"App_Data", "PostDeployTests"}
KNOWN_PREFIXES = (
    "wexhealth.",
    "wex.",
    "lighthouse1.",
    "lh1.",
    # Added after Run 1 — 27 unknown-prefix families, these cover the top 5 (33+ pipelines)
    "taskhost.",
    "rdcpoint.",
    "smartcommute.",
    "dbi.",
    "lh1ondemand.",
)
DEFAULT_ENVIRONMENT = "production"
DEFAULT_L2_THRESHOLD = 0.7

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CrawlRow:
    pipeline_name: str
    job_name: Optional[str]
    pattern: str
    host_app_name: Optional[str]
    web_config_dll: Optional[str]
    exe_config_stem: Optional[str]
    heuristic_name: Optional[str]
    resolution_source: str
    has_comments_in_host_json: bool
    has_appname_placeholder_near: bool
    raw_host_json_size_bytes: int
    notes: str = ""

    def best_name(self) -> Optional[str]:
        return (
            self.host_app_name or self.web_config_dll or self.exe_config_stem or self.heuristic_name
        )


@dataclass
class NavGroup:
    canonical_name: str
    pipelines: list[str]
    shared_app_name: Optional[str]  # None if mixed across group


@dataclass
class DiffReport:
    agree: list[tuple[str, str]] = field(default_factory=list)
    disagree: list[tuple[str, str, str]] = field(default_factory=list)
    crawled_only: list[tuple[str, str, str]] = field(default_factory=list)
    csv_only: list[tuple[str, str]] = field(default_factory=list)
    hand_total: int = 0
    crawled_total: int = 0


@dataclass
class Ambiguity:
    pipeline: str
    probe: str
    level: str  # "L1" | "L2" | "L3"
    candidates: list[str]


@dataclass
class EdgeCaseReport:
    comments_count: int
    placeholder_count: int
    unknown_prefixes: dict[str, int]
    malformed_host_json: list[str]
    lowercase_appname: list[str]
    pipeline_families: dict[str, list[str]]


@dataclass
class StemResult:
    stem: str
    level: str  # "L1" | "L2" | "L3" | "NONE"
    candidates: list[str]


@dataclass
class TemporalDiff:
    added: list[str]
    removed: list[str]
    app_name_changed: list[tuple[str, str, str]]
    pattern_changed: list[tuple[str, str, str]]
    total_pipelines_prev: int
    total_pipelines_curr: int


# ---------------------------------------------------------------------------
# Normalization and tiny utilities
# ---------------------------------------------------------------------------


def normalize(name: Optional[str]) -> str:
    if not name:
        return ""
    s = _NORM_SEP_RE.sub(".", name.lower())
    for prefix in KNOWN_PREFIXES:
        if s.startswith(prefix):
            return s[len(prefix) :]
    return s


def tokens(normalized: str) -> set[str]:
    return {t for t in normalized.split(".") if t}


def jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def redactor(secret: Optional[bytes]) -> Callable[[Optional[str]], Optional[str]]:
    if secret is None:
        return lambda s: s

    def _redact(s: Optional[str]) -> Optional[str]:
        if s is None or s == "":
            return s
        return hmac.new(secret, str(s).encode("utf-8"), "sha256").hexdigest()[:10]

    return _redact


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------


_TEMPLATE_LITERAL_RE = re.compile(r"^\{[A-Za-z]+\}$")


def extract_app_name(content: str) -> Optional[str]:
    m = _APP_NAME_RE.search(content)
    if not m:
        return None
    value = m.group(1)
    # Reject template placeholders like {AppName} that haven't been substituted
    if _TEMPLATE_LITERAL_RE.match(value):
        return None
    return value


def extract_assembly_from_webconfig(env_dir: Path) -> Optional[str]:
    for name in ("web.config", "Web.Config", "Web.config"):
        p = env_dir / name
        if p.is_file():
            m = _DLL_ARG_RE.search(read_text_safe(p))
            if m:
                return m.group(1)
    return None


def extract_assembly_from_execonfig(dir_path: Path) -> Optional[str]:
    configs = sorted(dir_path.glob("*.exe.config"))
    if not configs:
        return None
    name = configs[0].name
    if name.lower().endswith(".exe.config"):
        return name[: -len(".exe.config")]
    return None


def heuristic_from_pipeline_name(pipeline_name: str) -> Optional[str]:
    stripped = _PIPELINE_SUFFIX_RE.sub("", pipeline_name)
    return stripped if "-" in stripped else None


# ---------------------------------------------------------------------------
# Crawl & classify
# ---------------------------------------------------------------------------


def _make_row(
    pipeline_name: str, scan_dir: Path, pattern: str, job_name: Optional[str] = None
) -> CrawlRow:
    host_json = scan_dir / "wexhealth.host.json"
    host_app_name: Optional[str] = None
    host_bytes = 0
    has_comments = False
    has_placeholder = False
    if host_json.is_file():
        content = read_text_safe(host_json)
        host_bytes = len(content.encode("utf-8"))
        host_app_name = extract_app_name(content)
        has_comments = bool(_COMMENT_LINE_RE.search(content))
        has_placeholder = bool(_APPNAME_PLACEHOLDER_RE.search(content))

    web_dll = extract_assembly_from_webconfig(scan_dir)
    exe_stem = extract_assembly_from_execonfig(scan_dir)
    heuristic = heuristic_from_pipeline_name(pipeline_name)

    if host_app_name:
        source = "host_json"
    elif web_dll:
        source = "web_config"
    elif exe_stem:
        source = "exe_config"
    elif heuristic:
        source = "heuristic"
    else:
        source = "none"

    return CrawlRow(
        pipeline_name=pipeline_name,
        job_name=job_name,
        pattern=pattern,
        host_app_name=host_app_name,
        web_config_dll=web_dll,
        exe_config_stem=exe_stem,
        heuristic_name=heuristic,
        resolution_source=source,
        has_comments_in_host_json=has_comments,
        has_appname_placeholder_near=has_placeholder,
        raw_host_json_size_bytes=host_bytes,
    )


def crawl(repo_path: Path, environment: str = DEFAULT_ENVIRONMENT) -> list[CrawlRow]:
    rows: list[CrawlRow] = []
    for child in sorted(repo_path.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS:
            continue

        env_dir = child / environment
        if not env_dir.is_dir():
            rows.append(
                CrawlRow(
                    pipeline_name=child.name,
                    job_name=None,
                    pattern="MISSING_ENV",
                    host_app_name=None,
                    web_config_dll=None,
                    exe_config_stem=None,
                    heuristic_name=heuristic_from_pipeline_name(child.name),
                    resolution_source="heuristic"
                    if heuristic_from_pipeline_name(child.name)
                    else "none",
                    has_comments_in_host_json=False,
                    has_appname_placeholder_near=False,
                    raw_host_json_size_bytes=0,
                    notes=f"no {environment}/ dir",
                )
            )
            continue

        subdirs = [d for d in sorted(env_dir.iterdir()) if d.is_dir() and d.name not in ENV_SKIP]

        # Pattern B: every subdir has its own host.json
        if subdirs and all((d / "wexhealth.host.json").is_file() for d in subdirs):
            for job_dir in subdirs:
                rows.append(_make_row(child.name, job_dir, pattern="B", job_name=job_dir.name))
            continue

        # Pattern A: env_dir has host.json directly (nav C upgrade happens in reporter)
        if (env_dir / "wexhealth.host.json").is_file():
            rows.append(_make_row(child.name, env_dir, pattern="A"))
            continue

        # Pattern D_PARTIAL: any .config present
        if any(env_dir.glob("*.config")) or extract_assembly_from_execonfig(env_dir):
            rows.append(_make_row(child.name, env_dir, pattern="D_PARTIAL"))
            continue

        # Pattern D_EMPTY: nothing we can use
        heuristic = heuristic_from_pipeline_name(child.name)
        rows.append(
            CrawlRow(
                pipeline_name=child.name,
                job_name=None,
                pattern="D_EMPTY",
                host_app_name=None,
                web_config_dll=None,
                exe_config_stem=None,
                heuristic_name=heuristic,
                resolution_source="heuristic" if heuristic else "none",
                has_comments_in_host_json=False,
                has_appname_placeholder_near=False,
                raw_host_json_size_bytes=0,
            )
        )

    return rows


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------


def detect_nav_groups(rows: list[CrawlRow]) -> list[NavGroup]:
    groups: dict[str, list[CrawlRow]] = defaultdict(list)
    for r in rows:
        m = _NAV_RE.match(r.pipeline_name)
        if m:
            groups[m.group(1)].append(r)
    out: list[NavGroup] = []
    for canonical, members in sorted(groups.items()):
        names = {r.host_app_name for r in members if r.host_app_name}
        shared = next(iter(names)) if len(names) == 1 else None
        out.append(
            NavGroup(
                canonical_name=canonical,
                pipelines=sorted({r.pipeline_name for r in members}),
                shared_app_name=shared,
            )
        )
    return out


def cluster_pipeline_prefixes(rows: list[CrawlRow]) -> dict[str, list[str]]:
    families: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        stripped = _PIPELINE_SUFFIX_RE.sub("", r.pipeline_name)
        first = stripped.split("-", 1)[0] if "-" in stripped else stripped
        families[first].append(r.pipeline_name)
    return dict(sorted(families.items()))


def load_hand_csv(csv_path: Path) -> dict[str, str]:
    """Return normalized_app -> pipeline_name."""
    if not csv_path.is_file():
        return {}
    out: dict[str, str] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            app = (row.get("Application Name") or row.get("ApplicationName") or "").strip()
            pipeline = (row.get("Pipeline Name") or row.get("PipelineName") or "").strip()
            if app and pipeline:
                out[normalize(app)] = pipeline
    return out


def diff_against_hand_csv(rows: list[CrawlRow], hand_map: dict[str, str]) -> DiffReport:
    report = DiffReport(hand_total=len(hand_map))
    crawled_map: dict[str, tuple[str, str]] = {}
    for r in rows:
        best = r.best_name()
        if not best:
            continue
        key = normalize(best)
        if not key or key in crawled_map:
            continue
        crawled_map[key] = (r.pipeline_name, r.resolution_source)
    report.crawled_total = len(crawled_map)

    for key, hand_pipeline in hand_map.items():
        if key in crawled_map:
            crawled_pipeline, _ = crawled_map[key]
            if crawled_pipeline == hand_pipeline:
                report.agree.append((key, hand_pipeline))
            else:
                report.disagree.append((key, hand_pipeline, crawled_pipeline))
        else:
            report.csv_only.append((key, hand_pipeline))

    for key, (crawled_pipeline, source) in crawled_map.items():
        if key not in hand_map:
            report.crawled_only.append((key, crawled_pipeline, source))

    report.agree.sort()
    report.disagree.sort()
    report.crawled_only.sort()
    report.csv_only.sort()
    return report


def _build_name_index(rows: list[CrawlRow]) -> list[tuple[str, str]]:
    """Flatten every (pipeline, signal-name) pair across all signal sources.

    The plan's matcher indexes host_app_name, web_config_dll, AND exe_config_stem
    separately — any of them can produce an L1 hit. This mirrors that.
    """
    indexed: list[tuple[str, str]] = []
    for r in rows:
        for name in (r.host_app_name, r.web_config_dll, r.exe_config_stem):
            if name:
                indexed.append((r.pipeline_name, name))
    return indexed


def find_within_repo_ambiguities(
    rows: list[CrawlRow], l2_threshold: float = DEFAULT_L2_THRESHOLD
) -> list[Ambiguity]:
    indexed = _build_name_index(rows)
    ambig: list[Ambiguity] = []
    for r in rows:
        probe = r.best_name()
        if not probe:
            continue
        norm = normalize(probe)
        probe_tokens = tokens(norm)
        probe_tail = norm.split(".")[-2:]

        l1 = sorted({p for p, n in indexed if p != r.pipeline_name and normalize(n) == norm})
        if l1:
            ambig.append(Ambiguity(r.pipeline_name, probe, "L1", l1))
            continue

        l2 = sorted(
            {
                p
                for p, n in indexed
                if p != r.pipeline_name
                and jaccard(probe_tokens, tokens(normalize(n))) >= l2_threshold
            }
        )
        if len(l2) >= 2:
            ambig.append(Ambiguity(r.pipeline_name, probe, "L2", l2))
            continue

        l3 = sorted(
            {
                p
                for p, n in indexed
                if p != r.pipeline_name and normalize(n).split(".")[-2:] == probe_tail
            }
        )
        if len(l3) >= 2:
            ambig.append(Ambiguity(r.pipeline_name, probe, "L3", l3))
    return ambig


def audit_edge_cases(rows: list[CrawlRow], repo_path: Path, environment: str) -> EdgeCaseReport:
    comments = sum(1 for r in rows if r.has_comments_in_host_json)
    placeholders = sum(1 for r in rows if r.has_appname_placeholder_near)

    unknown_prefixes: Counter[str] = Counter()
    for r in rows:
        name = r.host_app_name or r.web_config_dll or r.exe_config_stem
        if not name:
            continue
        lower = name.lower()
        if not any(lower.startswith(p) for p in KNOWN_PREFIXES):
            first = lower.split(".", 1)[0] if "." in lower else lower
            unknown_prefixes[first + "."] += 1

    malformed: list[str] = []
    lowercase_appname: list[str] = []
    for r in rows:
        if r.pattern not in ("A", "B"):
            continue
        if r.job_name:
            host_json = (
                repo_path / r.pipeline_name / environment / r.job_name / "wexhealth.host.json"
            )
        else:
            host_json = repo_path / r.pipeline_name / environment / "wexhealth.host.json"
        if not host_json.is_file():
            continue
        content = read_text_safe(host_json)
        key = r.pipeline_name + (f" / {r.job_name}" if r.job_name else "")
        if content and not r.host_app_name:
            malformed.append(key)
        if _LOWERCASE_APPNAME_RE.search(content):
            lowercase_appname.append(key)

    return EdgeCaseReport(
        comments_count=comments,
        placeholder_count=placeholders,
        unknown_prefixes=dict(unknown_prefixes),
        malformed_host_json=malformed,
        lowercase_appname=lowercase_appname,
        pipeline_families=cluster_pipeline_prefixes(rows),
    )


# ---------------------------------------------------------------------------
# Optional: source-stems cascade & temporal diff
# ---------------------------------------------------------------------------


def simulate_source_match(
    rows: list[CrawlRow], stems: list[str], l2_threshold: float = DEFAULT_L2_THRESHOLD
) -> list[StemResult]:
    indexed = _build_name_index(rows)
    results: list[StemResult] = []
    for stem in stems:
        norm = normalize(stem)
        probe_tokens = tokens(norm)
        probe_tail = norm.split(".")[-2:]

        l1 = sorted({p for p, n in indexed if normalize(n) == norm})
        if l1:
            results.append(StemResult(stem, "L1", l1))
            continue
        l2 = sorted(
            {p for p, n in indexed if jaccard(probe_tokens, tokens(normalize(n))) >= l2_threshold}
        )
        if l2:
            results.append(StemResult(stem, "L2", l2))
            continue
        l3 = sorted({p for p, n in indexed if normalize(n).split(".")[-2:] == probe_tail})
        if l3:
            results.append(StemResult(stem, "L3", l3))
            continue
        results.append(StemResult(stem, "NONE", []))
    return results


def load_prev_snapshot(path: Path) -> dict[str, CrawlRow]:
    if not path.is_file():
        return {}
    out: dict[str, CrawlRow] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get("pipeline_name", "") + "::" + (row.get("job_name") or "")
            out[key] = CrawlRow(
                pipeline_name=row.get("pipeline_name", ""),
                job_name=row.get("job_name") or None,
                pattern=row.get("pattern", ""),
                host_app_name=row.get("host_app_name") or None,
                web_config_dll=row.get("web_config_dll") or None,
                exe_config_stem=row.get("exe_config_stem") or None,
                heuristic_name=row.get("heuristic_name") or None,
                resolution_source=row.get("resolution_source", "none"),
                has_comments_in_host_json=row.get("has_comments") in ("True", "true", "1"),
                has_appname_placeholder_near=row.get("has_placeholder") in ("True", "true", "1"),
                raw_host_json_size_bytes=int(row.get("host_json_bytes") or 0),
                notes=row.get("notes", ""),
            )
    return out


def temporal_diff(curr: list[CrawlRow], prev: dict[str, CrawlRow]) -> TemporalDiff:
    curr_keyed = {r.pipeline_name + "::" + (r.job_name or ""): r for r in curr}
    added = sorted(set(curr_keyed) - set(prev))
    removed = sorted(set(prev) - set(curr_keyed))
    app_changed: list[tuple[str, str, str]] = []
    pattern_changed: list[tuple[str, str, str]] = []
    for key in set(curr_keyed) & set(prev):
        c, p = curr_keyed[key], prev[key]
        if (c.host_app_name or "") != (p.host_app_name or ""):
            app_changed.append((key, p.host_app_name or "", c.host_app_name or ""))
        if c.pattern != p.pattern:
            pattern_changed.append((key, p.pattern, c.pattern))
    return TemporalDiff(
        added=added,
        removed=removed,
        app_name_changed=sorted(app_changed),
        pattern_changed=sorted(pattern_changed),
        total_pipelines_prev=len(prev),
        total_pipelines_curr=len(curr_keyed),
    )


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------


def _pct(n: int, total: int) -> str:
    return f"{(100 * n / total):.1f}%" if total else "0%"


def _rd(fn: Optional[Callable], s: Optional[str]) -> str:
    if fn is None:
        return s or ""
    out = fn(s)
    return out if out is not None else ""


def write_raw_csv(rows: list[CrawlRow], path: Path, rd: Optional[Callable]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "pipeline_name",
                "job_name",
                "pattern",
                "host_app_name",
                "web_config_dll",
                "exe_config_stem",
                "heuristic_name",
                "resolution_source",
                "has_comments",
                "has_placeholder",
                "host_json_bytes",
                "notes",
            ]
        )
        for r in sorted(rows, key=lambda x: (x.pipeline_name, x.job_name or "")):
            w.writerow(
                [
                    _rd(rd, r.pipeline_name),
                    _rd(rd, r.job_name),
                    r.pattern,
                    _rd(rd, r.host_app_name),
                    _rd(rd, r.web_config_dll),
                    _rd(rd, r.exe_config_stem),
                    _rd(rd, r.heuristic_name),
                    r.resolution_source,
                    r.has_comments_in_host_json,
                    r.has_appname_placeholder_near,
                    r.raw_host_json_size_bytes,
                    r.notes,
                ]
            )


def write_pattern_taxonomy(
    rows: list[CrawlRow], nav_groups: list[NavGroup], path: Path, rd: Optional[Callable]
) -> None:
    counts = Counter(r.pattern for r in rows)
    nav_pipelines = {p for g in nav_groups for p in g.pipelines}
    c_count = sum(1 for r in rows if r.pattern == "A" and r.pipeline_name in nav_pipelines)
    a_count = counts.get("A", 0) - c_count
    total = len(rows)

    lines = [
        "# Pattern Taxonomy",
        "",
        f"**Total rows (pipelines + batch jobs):** {total}",
        "",
        "| Pattern | Count | % | Description |",
        "|---|---|---|---|",
        f"| A | {a_count} | {_pct(a_count, total)} | Single-app with host.json (non-nav) |",
        f"| B | {counts.get('B', 0)} | {_pct(counts.get('B', 0), total)} | Batch fan-out (per-job host.json) |",
        f"| C | {c_count} | {_pct(c_count, total)} | Nav fan-out (subset of A) |",
        f"| D_PARTIAL | {counts.get('D_PARTIAL', 0)} | {_pct(counts.get('D_PARTIAL', 0), total)} | No host.json, has .config |",
        f"| D_EMPTY | {counts.get('D_EMPTY', 0)} | {_pct(counts.get('D_EMPTY', 0), total)} | No resolvable signals |",
        f"| MISSING_ENV | {counts.get('MISSING_ENV', 0)} | {_pct(counts.get('MISSING_ENV', 0), total)} | No production/ dir |",
        "",
        "## Nav groups detected",
        "",
    ]
    if nav_groups:
        for g in nav_groups:
            shared = _rd(rd, g.shared_app_name) if g.shared_app_name else "MIXED"
            lines.append(
                f"- `{g.canonical_name}` ({len(g.pipelines)} pipelines) → AppName: `{shared}`"
            )
    else:
        lines.append("(none)")

    lines.extend(["", "## Batch pipelines (Pattern B)", ""])
    batch_jobs: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r.pattern == "B":
            batch_jobs[r.pipeline_name].append(r.job_name or "")
    if batch_jobs:
        for p, jobs in sorted(batch_jobs.items()):
            lines.append(f"- `{p}`: {len(jobs)} jobs")
    else:
        lines.append("(none)")

    lines.extend(["", "## Resolution source distribution", ""])
    sources = Counter(r.resolution_source for r in rows)
    for src, n in sorted(sources.items(), key=lambda x: -x[1]):
        lines.append(f"- `{src}`: {n} ({_pct(n, total)})")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv_diff(diff: DiffReport, path: Path, rd: Optional[Callable]) -> None:
    lines = [
        "# Hand CSV vs Crawler",
        "",
        f"**Hand CSV entries:** {diff.hand_total}",
        f"**Crawler resolved entries:** {diff.crawled_total}",
        f"**Agreement:** {len(diff.agree)}",
        f"**Disagreement:** {len(diff.disagree)}",
        f"**Crawler-only:** {len(diff.crawled_only)}",
        f"**CSV-only:** {len(diff.csv_only)}",
        "",
        "## Agreement (sample 10)",
    ]
    for key, pipeline in diff.agree[:10]:
        lines.append(f"- `{_rd(rd, key)}` → `{pipeline}`")

    lines.extend(["", "## Disagreement — HUMAN REVIEW REQUIRED"])
    if diff.disagree:
        lines.extend(["| App | Hand pipeline | Crawled pipeline |", "|---|---|---|"])
        for key, hand, crawled in diff.disagree:
            lines.append(f"| `{_rd(rd, key)}` | `{hand}` | `{crawled}` |")
    else:
        lines.append("(none)")

    lines.extend(["", "## Crawler-only (CSV misses)"])
    if diff.crawled_only:
        lines.extend(["| App | Crawled pipeline | Source |", "|---|---|---|"])
        for key, pipeline, source in diff.crawled_only:
            lines.append(f"| `{_rd(rd, key)}` | `{pipeline}` | `{source}` |")
    else:
        lines.append("(none)")

    lines.extend(["", "## CSV-only (crawler missed)"])
    if diff.csv_only:
        lines.extend(["| App | Hand pipeline |", "|---|---|"])
        for key, pipeline in diff.csv_only:
            lines.append(f"| `{_rd(rd, key)}` | `{pipeline}` |")
    else:
        lines.append("(none)")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_ambiguity_report(
    ambiguities: list[Ambiguity],
    stem_results: Optional[list[StemResult]],
    path: Path,
    p_label: str,
    rd: Optional[Callable],
    l2_threshold: float = DEFAULT_L2_THRESHOLD,
) -> None:
    lines = [
        "# Matcher Cascade — Ambiguity & Collision Analysis",
        "",
        f"**Population:** {p_label}",
        f"**L2 Jaccard threshold:** {l2_threshold}",
        "",
        "## Within-repo collisions",
        f"Total probes with ambiguity: **{len(ambiguities)}**",
        "",
    ]
    by_level: dict[str, list[Ambiguity]] = defaultdict(list)
    for a in ambiguities:
        by_level[a.level].append(a)
    for level in ("L1", "L2", "L3"):
        items = by_level.get(level, [])
        lines.append(f"### {level} ({len(items)})")
        if not items:
            lines.extend(["(none)", ""])
            continue
        for a in items[:25]:
            cand = ", ".join(f"`{c}`" for c in a.candidates)
            lines.append(f"- `{a.pipeline}` probe=`{_rd(rd, a.probe)}` → {cand}")
        if len(items) > 25:
            lines.append(f"(… {len(items) - 25} more)")
        lines.append("")

    if stem_results is not None:
        counts = Counter(r.level for r in stem_results)
        ambig = [r for r in stem_results if len(r.candidates) > 1]
        lines.extend(
            [
                "---",
                "",
                "## Source-stems cascade (P-intersect)",
                f"Total stems: **{len(stem_results)}**",
                f"- L1: {counts.get('L1', 0)}",
                f"- L2: {counts.get('L2', 0)}",
                f"- L3: {counts.get('L3', 0)}",
                f"- NONE: {counts.get('NONE', 0)}",
                f"- **Ambiguous (≥2 candidates):** {len(ambig)}",
                "",
                "### Ambiguous — SILENT WRONG-ANSWER RISK",
            ]
        )
        if ambig:
            for r in ambig[:50]:
                cand = ", ".join(f"`{c}`" for c in r.candidates)
                lines.append(f"- `{_rd(rd, r.stem)}` @ {r.level} → {cand}")
            if len(ambig) > 50:
                lines.append(f"(… {len(ambig) - 50} more)")
        else:
            lines.append("(none)")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_edge_cases(edge: EdgeCaseReport, total: int, path: Path, rd: Optional[Callable]) -> None:
    lines = [
        "# Edge Cases",
        "",
        f"## `//` comments in host.json: {edge.comments_count} ({_pct(edge.comments_count, total)})",
        f"## `{{AppName}}` placeholder occurrences: {edge.placeholder_count}",
        "",
        "## Unknown org prefixes",
    ]
    if edge.unknown_prefixes:
        for prefix, n in sorted(edge.unknown_prefixes.items(), key=lambda x: -x[1]):
            lines.append(f"- `{_rd(rd, prefix)}`: {n}")
    else:
        lines.append("(none — all resolved names match known prefixes)")

    lines.extend(["", "## Malformed host.json (AppName regex failed)"])
    if edge.malformed_host_json:
        for p in edge.malformed_host_json[:50]:
            lines.append(f"- `{p}`")
        if len(edge.malformed_host_json) > 50:
            lines.append(f"(… {len(edge.malformed_host_json) - 50} more)")
    else:
        lines.append("(none)")

    lines.extend(["", "## Lowercase `appName` observed"])
    if edge.lowercase_appname:
        for p in edge.lowercase_appname:
            lines.append(f"- `{p}`")
    else:
        lines.append("(none)")

    lines.extend(
        [
            "",
            "## Pipeline name families (prefix clusters)",
            "",
            "| Family | Count | Sample |",
            "|---|---|---|",
        ]
    )
    for family, members in edge.pipeline_families.items():
        lines.append(f"| `{family}` | {len(members)} | `{members[0]}` |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_temporal_diff(td: TemporalDiff, path: Path) -> None:
    total = td.total_pipelines_curr
    churn = len(td.added) + len(td.removed) + len(td.app_name_changed) + len(td.pattern_changed)
    churn_pct = 100 * churn / max(1, total)
    if churn_pct < 5:
        verdict = "Path 2 viable — annual regeneration"
    elif churn_pct < 15:
        verdict = "Path 2 viable — quarterly regeneration"
    else:
        verdict = "Path 2 NOT viable — churn too high"

    lines = [
        "# Temporal Stability Diff",
        "",
        f"**Pipelines (prev):** {td.total_pipelines_prev}",
        f"**Pipelines (curr):** {td.total_pipelines_curr}",
        f"**Total churn events:** {churn} ({churn_pct:.1f}%)",
        f"**Path 2 verdict:** {verdict}",
        "",
        f"## Added ({len(td.added)})",
    ]
    for a in td.added:
        lines.append(f"- `{a}`")
    lines.extend(["", f"## Removed ({len(td.removed)})"])
    for r in td.removed:
        lines.append(f"- `{r}`")
    lines.extend(["", f"## AppName changed ({len(td.app_name_changed)})"])
    for key, prev, curr in td.app_name_changed:
        lines.append(f"- `{key}`: `{prev}` → `{curr}`")
    lines.extend(["", f"## Pattern re-classifications ({len(td.pattern_changed)})"])
    for key, prev, curr in td.pattern_changed:
        lines.append(f"- `{key}`: `{prev}` → `{curr}`")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_source_match(
    stem_results: list[StemResult],
    path: Path,
    rd: Optional[Callable],
    l2_threshold: float = DEFAULT_L2_THRESHOLD,
) -> None:
    counts = Counter(r.level for r in stem_results)
    total = len(stem_results)
    resolved = total - counts.get("NONE", 0)
    lines = [
        "# Source Project → Pipeline Cascade Simulation (P-intersect)",
        "",
        f"**Source stems supplied:** {total}",
        f"**Resolved (any level):** {resolved} ({_pct(resolved, total)})",
        f"**Unresolved:** {counts.get('NONE', 0)} ({_pct(counts.get('NONE', 0), total)})",
        "",
        f"- L1 exact: {counts.get('L1', 0)} ({_pct(counts.get('L1', 0), total)})",
        f"- L2 Jaccard ≥{l2_threshold}: {counts.get('L2', 0)} ({_pct(counts.get('L2', 0), total)})",
        f"- L3 tail-2 tokens: {counts.get('L3', 0)} ({_pct(counts.get('L3', 0), total)})",
        "",
    ]
    for level in ("L1", "L2", "L3", "NONE"):
        items = [r for r in stem_results if r.level == level]
        if not items:
            continue
        ambig = [r for r in items if len(r.candidates) > 1]
        lines.append(f"## {level} ({len(items)}) — ambiguous: {len(ambig)}")
        for r in items[:50]:
            cand = ", ".join(f"`{c}`" for c in r.candidates) or "(no candidates)"
            flag = " ⚠" if len(r.candidates) > 1 else ""
            lines.append(f"- `{_rd(rd, r.stem)}`{flag} → {cand}")
        if len(items) > 50:
            lines.append(f"(… {len(items) - 50} more)")
        lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main / argparse
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="APP_CONFIG Repo Crawler — Evidence Pass",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="THROWAWAY SPIKE. See docs/APP_CONFIG_REPO_SPIKE.md for context.",
    )
    p.add_argument("--app-config-path", required=True, type=Path)
    p.add_argument("--hand-csv", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--source-stems", type=Path, default=None)
    p.add_argument("--prev-snapshot", type=Path, default=None)
    p.add_argument("--redact", action="store_true")
    p.add_argument(
        "--l2-threshold",
        type=float,
        default=DEFAULT_L2_THRESHOLD,
        help=f"Jaccard threshold for L2 cascade level (default {DEFAULT_L2_THRESHOLD}). "
        "Try 0.6 or 0.7 to tighten after observing false positives at 0.5.",
    )
    p.add_argument("--environment", default=DEFAULT_ENVIRONMENT)
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if not args.app_config_path.is_dir():
        print(f"ERROR: --app-config-path not a directory: {args.app_config_path}", file=sys.stderr)
        return 2
    if not args.hand_csv.is_file():
        print(f"ERROR: --hand-csv not a file: {args.hand_csv}", file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rd: Optional[Callable] = None
    if args.redact:
        secret = os.environ.get("SPIKE_REDACT_SECRET")
        if not secret:
            print("ERROR: --redact requires SPIKE_REDACT_SECRET env var", file=sys.stderr)
            return 2
        rd = redactor(secret.encode("utf-8"))

    l2_thresh = args.l2_threshold
    if l2_thresh != DEFAULT_L2_THRESHOLD:
        print(f"  L2 Jaccard threshold: {l2_thresh} (default is {DEFAULT_L2_THRESHOLD})")

    print(f"Crawling {args.app_config_path} (environment={args.environment}) ...")
    rows = crawl(args.app_config_path, args.environment)
    print(f"  {len(rows)} rows")

    nav_groups = detect_nav_groups(rows)
    print(f"  {len(nav_groups)} nav groups")

    hand_map = load_hand_csv(args.hand_csv)
    diff = diff_against_hand_csv(rows, hand_map)
    print(
        f"  CSV diff: agree={len(diff.agree)} "
        f"disagree={len(diff.disagree)} "
        f"crawled-only={len(diff.crawled_only)} "
        f"csv-only={len(diff.csv_only)}"
    )

    ambiguities = find_within_repo_ambiguities(rows, l2_threshold=l2_thresh)
    print(f"  {len(ambiguities)} within-repo ambiguities (L2 threshold={l2_thresh})")

    edge = audit_edge_cases(rows, args.app_config_path, args.environment)

    stem_results: Optional[list[StemResult]] = None
    if args.source_stems:
        if not args.source_stems.is_file():
            print(f"ERROR: --source-stems not a file: {args.source_stems}", file=sys.stderr)
            return 2
        stems = [
            s.strip()
            for s in args.source_stems.read_text(encoding="utf-8").splitlines()
            if s.strip()
        ]
        stem_results = simulate_source_match(rows, stems, l2_threshold=l2_thresh)
        print(f"  {len(stems)} source stems simulated")

    temporal: Optional[TemporalDiff] = None
    if args.prev_snapshot:
        if not args.prev_snapshot.is_file():
            print(f"ERROR: --prev-snapshot not a file: {args.prev_snapshot}", file=sys.stderr)
            return 2
        temporal = temporal_diff(rows, load_prev_snapshot(args.prev_snapshot))
        print(f"  temporal: added={len(temporal.added)} removed={len(temporal.removed)}")

    out = args.output_dir
    p_label = (
        "P-intersect (source stems supplied)"
        if stem_results
        else "P-resolvable — proxy; no --source-stems supplied"
    )
    print(f"Writing reports to {out}/ ...")
    write_raw_csv(rows, out / "01_raw_crawl.csv", rd)
    write_pattern_taxonomy(rows, nav_groups, out / "02_pattern_taxonomy.md", rd)
    write_csv_diff(diff, out / "03_csv_diff.md", rd)
    write_ambiguity_report(
        ambiguities, stem_results, out / "04_ambiguity_report.md", p_label, rd, l2_thresh
    )
    write_edge_cases(edge, len(rows), out / "05_edge_cases.md", rd)
    if temporal:
        write_temporal_diff(temporal, out / "06_temporal_diff.md")
    if stem_results:
        write_source_match(stem_results, out / "07_source_project_match.md", rd, l2_thresh)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
