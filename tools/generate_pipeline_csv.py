#!/usr/bin/env python3
"""Generate pipeline_to_app_mapping.csv from the WEX app-config repo.

Crawls the health-benefits-app-config repository structure and extracts
pipeline → application name mappings from wexhealth.host.json, web.config,
and *.exe.config files.

Output is a clean CSV that scatter consumes via --pipeline-csv. Manual
overrides live in a separate file (pipeline_manual_overrides.csv) and
are never touched by this tool.

Stdlib only — no scatter imports, no third-party dependencies.

Usage:
    python tools/generate_pipeline_csv.py \\
        --app-config-path /path/to/health-benefits-app-config \\
        --output examples/pipeline_to_app_mapping.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants & regexes
# ---------------------------------------------------------------------------

_APP_NAME_RE = re.compile(r'"AppName"\s*:\s*"([^"]+)"')
_DLL_ARG_RE = re.compile(r'arguments="[^"]*?([A-Za-z][A-Za-z0-9.]+)\.dll"', re.IGNORECASE)
_PIPELINE_SUFFIX_RE = re.compile(r"-(az-cd|az-cicd|cicd|cd|mws)$", re.IGNORECASE)
_TEMPLATE_LITERAL_RE = re.compile(r"^\{[A-Za-z]+\}$")

SKIP_DIRS = {
    "GeneratedIisSettingsFiles",
    "MachineConfigurationsSummarizer",
    ".git",
    ".github",
    ".vs",
}
ENV_SKIP = {"App_Data", "PostDeployTests"}
DEFAULT_ENVIRONMENT = "production"
CSV_COLUMNS = ["pipeline_name", "app_name", "assembly_name", "source"]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CrawlRow:
    pipeline_name: str
    job_name: Optional[str]
    app_name: Optional[str]
    assembly_name: Optional[str]
    source: str  # host_json | web_config | exe_config | heuristic | none


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _extract_app_name(content: str) -> Optional[str]:
    m = _APP_NAME_RE.search(content)
    if not m:
        return None
    value = m.group(1)
    if _TEMPLATE_LITERAL_RE.match(value):
        return None
    return value


def _extract_assembly_from_webconfig(scan_dir: Path) -> Optional[str]:
    for name in ("web.config", "Web.Config", "Web.config"):
        p = scan_dir / name
        if p.is_file():
            m = _DLL_ARG_RE.search(_read_text_safe(p))
            if m:
                return m.group(1)
    return None


def _extract_assembly_from_execonfig(scan_dir: Path) -> Optional[str]:
    configs = sorted(scan_dir.glob("*.exe.config"))
    if not configs:
        return None
    name = configs[0].name
    if name.lower().endswith(".exe.config"):
        return name[: -len(".exe.config")]
    return None


def _heuristic_from_pipeline_name(pipeline_name: str) -> Optional[str]:
    stripped = _PIPELINE_SUFFIX_RE.sub("", pipeline_name)
    return stripped if "-" in stripped else None


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------


def _make_row(pipeline_name: str, scan_dir: Path, job_name: Optional[str] = None) -> CrawlRow:
    host_json = scan_dir / "wexhealth.host.json"
    app_name: Optional[str] = None
    if host_json.is_file():
        app_name = _extract_app_name(_read_text_safe(host_json))

    assembly = _extract_assembly_from_webconfig(scan_dir) or _extract_assembly_from_execonfig(
        scan_dir
    )

    if app_name:
        source = "host_json"
    elif assembly:
        source = "web_config" if _extract_assembly_from_webconfig(scan_dir) else "exe_config"
    else:
        source = "heuristic" if _heuristic_from_pipeline_name(pipeline_name) else "none"

    return CrawlRow(
        pipeline_name=pipeline_name,
        job_name=job_name,
        app_name=app_name or assembly or _heuristic_from_pipeline_name(pipeline_name),
        assembly_name=assembly,
        source=source,
    )


def crawl(repo_path: Path, environment: str = DEFAULT_ENVIRONMENT) -> list[CrawlRow]:
    rows: list[CrawlRow] = []
    for child in sorted(repo_path.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS:
            continue

        env_dir = child / environment
        if not env_dir.is_dir():
            heuristic = _heuristic_from_pipeline_name(child.name)
            if heuristic:
                rows.append(CrawlRow(child.name, None, heuristic, None, "heuristic"))
            continue

        subdirs = [d for d in sorted(env_dir.iterdir()) if d.is_dir() and d.name not in ENV_SKIP]

        # Pattern B: batch fan-out — every subdir has its own host.json
        if subdirs and all((d / "wexhealth.host.json").is_file() for d in subdirs):
            for job_dir in subdirs:
                rows.append(_make_row(child.name, job_dir, job_name=job_dir.name))
            continue

        # Pattern A/C: env_dir has host.json directly
        if (env_dir / "wexhealth.host.json").is_file():
            rows.append(_make_row(child.name, env_dir))
            continue

        # Pattern D_PARTIAL: has .config files but no host.json
        if any(env_dir.glob("*.config")) or _extract_assembly_from_execonfig(env_dir):
            rows.append(_make_row(child.name, env_dir))
            continue

        # Pattern D_EMPTY / MISSING_ENV: only emit if heuristic produces something
        heuristic = _heuristic_from_pipeline_name(child.name)
        if heuristic:
            rows.append(CrawlRow(child.name, None, heuristic, None, "heuristic"))

    return rows


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------


def write_csv(rows: list[CrawlRow], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for r in sorted(rows, key=lambda x: (x.pipeline_name, x.job_name or "")):
            writer.writerow([r.pipeline_name, r.app_name or "", r.assembly_name or "", r.source])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description="Generate pipeline_to_app_mapping.csv from the WEX app-config repo.",
        epilog="Output is consumed by scatter via --pipeline-csv. "
        "Manual overrides belong in pipeline_manual_overrides.csv (separate file).",
    )
    p.add_argument("--app-config-path", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--environment", default=DEFAULT_ENVIRONMENT)
    args = p.parse_args()

    if not args.app_config_path.is_dir():
        print(f"ERROR: not a directory: {args.app_config_path}", file=sys.stderr)
        return 2

    print(f"Crawling {args.app_config_path} (environment={args.environment}) ...")
    rows = crawl(args.app_config_path, args.environment)

    sources = Counter(r.source for r in rows)
    print(
        f"  {len(rows)} rows written"
        f" ({sources.get('host_json', 0)} host_json,"
        f" {sources.get('web_config', 0)} web_config,"
        f" {sources.get('exe_config', 0)} exe_config,"
        f" {sources.get('heuristic', 0)} heuristic)"
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_csv(rows, args.output)
    print(f"  Written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
