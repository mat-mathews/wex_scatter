"""Centralized pipeline name resolution with layered matching strategies."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class PipelineMatch:
    """Result of a successful pipeline resolution."""

    pipeline_name: str
    strategy: str  # "exact" | "case_insensitive" | "suffix_stripped" | "prefix"
    matched_key: str
    probe: str


STRIPPABLE_SUFFIXES: Tuple[str, ...] = (
    ".IntegrationTests",
    ".UnitTests",
    ".WebApi",
    ".Service",
    ".Worker",
    ".Server",
    ".Client",
    ".Shared",
    ".Console",
    ".Host",
    ".Core",
    ".Web",
    ".Api",
    ".App",
)


class PipelineResolver:
    """Resolves project/solution names to pipeline names using layered strategies.

    Construct once with the loaded pipeline_map, then call resolve() per lookup.
    Thread-safe — all state is immutable after __init__.

    Strategy order (per probe):
      1. Exact match
      2. Case-insensitive match
      3. Suffix-stripped match (exact + case-insensitive on stripped name)
      4. Prefix match (longest CSV key that is a dotted prefix of probe)
    """

    def __init__(self, pipeline_map: Dict[str, str]) -> None:
        self._map = pipeline_map
        self._ci_index: Dict[str, str] = {k.lower(): k for k in pipeline_map}
        self._sorted_keys: List[str] = sorted(pipeline_map.keys(), key=len, reverse=True)

    def resolve(self, *probes: str) -> Optional[PipelineMatch]:
        """Try each probe name against strategies in priority order.

        Accepts multiple probe names (e.g., solution stems first, then project name).
        Returns the first match found, or None.
        """
        for probe in probes:
            if not probe:
                continue
            match = self._resolve_single(probe)
            if match is not None:
                return match
        return None

    def _resolve_single(self, probe: str) -> Optional[PipelineMatch]:
        if probe in self._map:
            return PipelineMatch(self._map[probe], "exact", probe, probe)

        lower = probe.lower()
        if lower in self._ci_index:
            key = self._ci_index[lower]
            return PipelineMatch(self._map[key], "case_insensitive", key, probe)

        stripped = _strip_suffix(probe)
        if stripped != probe:
            if stripped in self._map:
                return PipelineMatch(self._map[stripped], "suffix_stripped", stripped, probe)
            stripped_lower = stripped.lower()
            if stripped_lower in self._ci_index:
                key = self._ci_index[stripped_lower]
                return PipelineMatch(self._map[key], "suffix_stripped", key, probe)

        best = self._longest_prefix_key(probe)
        if best is not None:
            return PipelineMatch(self._map[best], "prefix", best, probe)

        return None

    def _longest_prefix_key(self, probe: str) -> Optional[str]:
        for key in self._sorted_keys:
            if probe.startswith(key + "."):
                return key
        return None


def _strip_suffix(name: str) -> str:
    lower = name.lower()
    for suffix in STRIPPABLE_SUFFIXES:
        if lower.endswith(suffix.lower()):
            return name[: -len(suffix)]
    return name
