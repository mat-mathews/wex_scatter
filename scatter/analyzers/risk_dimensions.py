"""Per-dimension risk scoring functions.

Six dimension scorers for the risk engine. Each is a pure function:
graph data in, RiskDimension out. No AI, no I/O, no side effects.

Naming: score_* (Decision #3, Devon).
Scoring: piecewise linear interpolation between thresholds (Decision #2, Devon).
Missing data: returns data_available=False (Decision #7, Fatima).
"""

from typing import Dict, List, Optional, Set

from scatter.analyzers.coupling_analyzer import CycleGroup, ProjectMetrics
from scatter.core.graph import DependencyGraph
from scatter.core.risk_models import RiskDimension, score_to_severity


# --- Interpolation helper ---


def _interpolate(value: float, low: float, high: float, low_score: float, high_score: float) -> float:
    """Piecewise linear interpolation. Clamps to [low_score, high_score]."""
    if high <= low:
        return high_score
    t = (value - low) / (high - low)
    t = max(0.0, min(1.0, t))
    return low_score + t * (high_score - low_score)


def _unavailable(name: str, label: str) -> RiskDimension:
    """Return a dimension with data_available=False (Decision #7)."""
    return RiskDimension(
        name=name,
        label=label,
        score=0.0,
        severity="low",
        factors=["data_unavailable"],
        raw_metrics={},
        data_available=False,
    )


# --- 1. Structural Coupling ---


def score_structural(
    target: str,
    metrics: Optional[ProjectMetrics],
    all_metrics: Dict[str, ProjectMetrics],
) -> RiskDimension:
    """Score structural coupling risk based on fan-in and coupling score.

    Piecewise linear on fan_in:
      0–3   → 0.1–0.4
      3–5   → 0.4–0.7
      5–10  → 0.7–1.0
      10+   → 1.0
    """
    name = "structural"
    label = "Structural coupling"

    if metrics is None:
        return _unavailable(name, label)

    fan_in = metrics.fan_in

    if fan_in >= 10:
        score = 1.0
    elif fan_in >= 5:
        score = _interpolate(fan_in, 5, 10, 0.7, 1.0)
    elif fan_in >= 3:
        score = _interpolate(fan_in, 3, 5, 0.4, 0.7)
    else:
        score = _interpolate(fan_in, 0, 3, 0.1, 0.4)

    # Percentile bump: top 5% by coupling score gets +0.1 (capped at 1.0)
    # Need at least 10 projects for percentile to be meaningful
    if len(all_metrics) >= 10:
        all_scores = sorted(m.coupling_score for m in all_metrics.values())
        p95_idx = max(0, int(len(all_scores) * 0.95) - 1)
        if metrics.coupling_score >= all_scores[p95_idx]:
            score = min(1.0, score + 0.1)

    factors = [f"Fan-in of {fan_in}"]
    if all_metrics:
        rank = sum(1 for m in all_metrics.values() if m.coupling_score <= metrics.coupling_score)
        percentile = int(100 * rank / len(all_metrics)) if all_metrics else 0
        factors[0] += f" (top {100 - percentile}% of codebase by coupling)"
    factors.append(f"Coupling score {metrics.coupling_score:.2f}")

    return RiskDimension(
        name=name,
        label=label,
        score=round(score, 3),
        severity=score_to_severity(score),
        factors=factors,
        raw_metrics={
            "fan_in": fan_in,
            "fan_out": metrics.fan_out,
            "coupling_score": metrics.coupling_score,
            "afferent_coupling": metrics.afferent_coupling,
            "efferent_coupling": metrics.efferent_coupling,
        },
    )


# --- 2. Instability ---


def score_instability(
    target: str,
    metrics: Optional[ProjectMetrics],
) -> RiskDimension:
    """Score instability risk. Instability alone is fine; instability + high fan-in is dangerous.

    Two-input scoring (instability × fan_in):
      instability >= 0.8 AND fan_in >= 3  → 0.7–0.9
      instability 0.6–0.8 AND fan_in >= 3 → 0.5–0.7
      instability >= 0.8 AND fan_in < 3   → 0.3
      instability 0.5–0.6 AND fan_in >= 3 → 0.3–0.5
      instability < 0.5                   → 0.1
    """
    name = "instability"
    label = "Instability"

    if metrics is None:
        return _unavailable(name, label)

    inst = metrics.instability
    fan_in = metrics.fan_in

    if fan_in >= 3:
        if inst >= 0.8:
            score = _interpolate(inst, 0.8, 1.0, 0.7, 0.9)
        elif inst >= 0.6:
            score = _interpolate(inst, 0.6, 0.8, 0.5, 0.7)
        elif inst >= 0.5:
            score = _interpolate(inst, 0.5, 0.6, 0.3, 0.5)
        else:
            score = 0.1
    else:
        # Leaf project — instability is acceptable
        if inst >= 0.8:
            score = 0.3
        else:
            score = 0.1

    factors = []
    if score >= 0.5:
        factors.append(
            f"Instability {inst:.2f} with fan-in {fan_in} — fragile foundation pattern"
        )
    elif inst >= 0.8:
        factors.append(
            f"Instability {inst:.2f} — unstable but low fan-in (acceptable for leaf projects)"
        )
    else:
        factors.append(f"Instability {inst:.2f}")

    return RiskDimension(
        name=name,
        label=label,
        score=round(score, 3),
        severity=score_to_severity(score),
        factors=factors,
        raw_metrics={
            "instability": inst,
            "fan_in": fan_in,
            "fan_out": metrics.fan_out,
        },
    )


# --- 3. Cycle Entanglement ---


def score_cycle(
    target: str,
    cycles: List[CycleGroup],
) -> RiskDimension:
    """Score cycle risk based on membership and cycle size.

    Scoring:
      in cycle of size >= 5   → 1.0 (critical — large cycle is systemic)
      in cycle of size 3–5    → 0.6–1.0 (interpolated)
      in cycle of size 2      → 0.6 (mutual dependency)
      not in any cycle        → 0.0

    Multiple cycle membership: add 0.1 per extra cycle, cap at 1.0.
    """
    name = "cycle"
    label = "Cycle entanglement"

    target_cycles = [c for c in cycles if target in c.projects]

    if not target_cycles:
        return RiskDimension(
            name=name,
            label=label,
            score=0.0,
            severity="low",
            factors=[],
            raw_metrics={"cycle_count": 0},
        )

    # Score from largest cycle
    largest = max(target_cycles, key=lambda c: c.size)
    size = largest.size

    if size >= 5:
        score = 1.0
    elif size > 2:
        score = _interpolate(size, 2, 5, 0.6, 1.0)
    else:
        score = 0.6

    # Multiple cycle bonus
    if len(target_cycles) > 1:
        score = min(1.0, score + 0.1 * (len(target_cycles) - 1))

    factors = []
    for cyc in target_cycles:
        cycle_path = " → ".join(cyc.shortest_cycle)
        factors.append(
            f"{target} is in a dependency cycle: {cycle_path} ({cyc.size} projects)"
        )
    if len(target_cycles) > 1:
        factors.append(f"{target} is in {len(target_cycles)} overlapping cycles — deeply entangled")

    return RiskDimension(
        name=name,
        label=label,
        score=round(min(1.0, score), 3),
        severity=score_to_severity(score),
        factors=factors,
        raw_metrics={
            "cycle_count": len(target_cycles),
            "largest_cycle_size": largest.size,
            "cycle_projects": largest.projects,
        },
    )


# --- 4. Database Coupling ---


def score_database(
    target: str,
    graph: DependencyGraph,
    metrics: Optional[ProjectMetrics],
    team_map: Optional[Dict[str, str]] = None,
) -> RiskDimension:
    """Score database coupling risk via shared stored procedures.

    Scoring (piecewise linear on shared_db_density):
      shared_db_density > 0.5 AND cross-team   → 0.8–1.0
      shared_db_density > 0.3 OR cross-team     → 0.5–0.8
      any shared sprocs, same team              → 0.2–0.5
      no shared sprocs                          → 0.0
    """
    name = "database"
    label = "Database coupling"

    if metrics is None:
        return _unavailable(name, label)

    # Find shared sprocs for this target
    node = graph.get_node(target)
    if not node:
        return _unavailable(name, label)

    target_sprocs = set(node.sproc_references)
    if not target_sprocs:
        return RiskDimension(
            name=name,
            label=label,
            score=0.0,
            severity="low",
            factors=[],
            raw_metrics={"shared_sproc_count": 0, "shared_db_density": 0.0},
        )

    # Find which other projects share these sprocs
    shared_sprocs: Dict[str, List[str]] = {}  # sproc → [project names]
    for other_node in graph.get_all_nodes():
        if other_node.name == target:
            continue
        overlap = target_sprocs & set(other_node.sproc_references)
        for sproc in overlap:
            shared_sprocs.setdefault(sproc, []).append(other_node.name)

    if not shared_sprocs:
        return RiskDimension(
            name=name,
            label=label,
            score=0.0,
            severity="low",
            factors=[],
            raw_metrics={"shared_sproc_count": 0, "shared_db_density": 0.0},
        )

    shared_count = len(shared_sprocs)
    density = metrics.shared_db_density

    # Check cross-team
    cross_team = False
    teams_involved: Set[str] = set()
    if team_map:
        target_team = team_map.get(target)
        for projects in shared_sprocs.values():
            for proj in projects:
                proj_team = team_map.get(proj)
                if proj_team:
                    teams_involved.add(proj_team)
                    if target_team and proj_team != target_team:
                        cross_team = True

    if density > 0.5 and cross_team:
        score = _interpolate(density, 0.5, 1.0, 0.8, 1.0)
    elif density > 0.3 or cross_team:
        score = _interpolate(density, 0.1, 0.5, 0.5, 0.8)
    else:
        score = _interpolate(density, 0.0, 0.3, 0.2, 0.5)

    factors = [f"{shared_count} stored procedures shared with other projects"]
    if cross_team:
        sproc_names = ", ".join(list(shared_sprocs.keys())[:3])
        factors.append(
            f"Sprocs {sproc_names} are cross-team — changes require coordinated migration"
        )

    return RiskDimension(
        name=name,
        label=label,
        score=round(score, 3),
        severity=score_to_severity(score),
        factors=factors,
        raw_metrics={
            "shared_sproc_count": shared_count,
            "shared_db_density": density,
            "cross_team": cross_team,
            "teams_involved": sorted(teams_involved),
            "shared_sproc_names": list(shared_sprocs.keys()),
        },
    )


# --- 5. Blast Radius ---


def score_blast_radius(
    target: str,
    direct_consumer_count: int,
    transitive_consumer_count: int,
    all_metrics: Optional[Dict[str, ProjectMetrics]] = None,
) -> RiskDimension:
    """Score blast radius based on consumer count and depth.

    Piecewise linear on transitive consumers:
      transitive >= 20  → 1.0
      transitive 10–20  → 0.7–1.0
      direct >= 5       → 0.5–0.7
      direct 2–5        → 0.3–0.5
      direct <= 1       → 0.1
    """
    name = "blast_radius"
    label = "Blast radius"

    total = direct_consumer_count + transitive_consumer_count

    if transitive_consumer_count >= 20:
        score = 1.0
    elif transitive_consumer_count >= 10:
        score = _interpolate(transitive_consumer_count, 10, 20, 0.7, 1.0)
    elif direct_consumer_count >= 5:
        score = _interpolate(direct_consumer_count, 5, 10, 0.5, 0.7)
    elif direct_consumer_count >= 2:
        score = _interpolate(direct_consumer_count, 2, 5, 0.3, 0.5)
    else:
        score = 0.1

    factors = [f"{direct_consumer_count} direct consumers, {transitive_consumer_count} transitive"]

    # Percentile context
    if all_metrics:
        all_fan_ins = sorted(m.fan_in for m in all_metrics.values())
        rank = sum(1 for fi in all_fan_ins if fi <= direct_consumer_count)
        percentile = int(100 * rank / len(all_fan_ins)) if all_fan_ins else 0
        if percentile >= 90:
            factors.append(f"Blast radius reaches {total} projects — top {100 - percentile}% widest in codebase")

    return RiskDimension(
        name=name,
        label=label,
        score=round(score, 3),
        severity=score_to_severity(score),
        factors=factors,
        raw_metrics={
            "direct_consumers": direct_consumer_count,
            "transitive_consumers": transitive_consumer_count,
            "total": total,
        },
    )


# --- 6. Domain Boundary ---


def score_domain_boundary(
    target: str,
    consumer_cluster_ids: List[str],
    target_cluster_id: Optional[str] = None,
    team_map: Optional[Dict[str, str]] = None,
    consumer_names: Optional[List[str]] = None,
) -> RiskDimension:
    """Score domain boundary risk based on cluster/team crossings.

    Piecewise linear on unique clusters crossed:
      3+ clusters (or 3+ teams)  → 0.6–0.8
      2 clusters (or 2 teams)    → 0.3–0.6
      1 cluster boundary         → 0.2–0.3
      same cluster               → 0.0
    """
    name = "domain_boundary"
    label = "Domain boundary"

    # Count unique clusters that differ from target's cluster
    unique_clusters = set(consumer_cluster_ids)
    if target_cluster_id:
        unique_clusters.discard(target_cluster_id)
    clusters_crossed = len(unique_clusters)

    # Count unique teams
    teams_crossed = 0
    team_names: Set[str] = set()
    if team_map and consumer_names:
        target_team = team_map.get(target)
        for cname in consumer_names:
            cteam = team_map.get(cname)
            if cteam and cteam != target_team:
                team_names.add(cteam)
        teams_crossed = len(team_names)

    # Use the higher of cluster or team crossings
    crossings = max(clusters_crossed, teams_crossed)

    if crossings >= 3:
        score = _interpolate(crossings, 3, 6, 0.6, 0.8)
    elif crossings >= 2:
        score = _interpolate(crossings, 2, 3, 0.3, 0.6)
    elif crossings >= 1:
        score = _interpolate(crossings, 1, 2, 0.2, 0.3)
    else:
        score = 0.0

    factors = []
    if clusters_crossed > 0:
        factors.append(f"Change crosses {clusters_crossed} domain clusters")
    if team_names:
        factors.append(f"Consumers span {teams_crossed} teams: {', '.join(sorted(team_names))} — coordination required")

    return RiskDimension(
        name=name,
        label=label,
        score=round(score, 3),
        severity=score_to_severity(score),
        factors=factors,
        raw_metrics={
            "clusters_crossed": clusters_crossed,
            "teams_crossed": teams_crossed,
            "team_names": sorted(team_names),
        },
    )
