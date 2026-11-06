"""Dependency graph built with NetworkX.

Edge direction: source -> target means "source depends on target"
(for example a database -> the KMS key that wraps its data key).
So the assets that depend on X are X's ancestors in the graph.
"""
from __future__ import annotations

import math

import networkx as nx

from qmigrate.engine.catalog import ALGORITHMS

PROTECTIVE = {"uses_key", "trusts_cert", "validates_token", "verifies_signature"}


def build_graph(assets: list[dict], edges: list[dict]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for a in assets:
        graph.add_node(a["asset_id"])
    for e in edges:
        if e["source"] in graph and e["target"] in graph:
            graph.add_edge(e["source"], e["target"], relation=e["relation"])
    return graph


def structural_metrics(graph: nx.DiGraph) -> dict[str, dict]:
    """Metrics that depend only on the shape of the graph (computed once)."""
    nodes = list(graph.nodes)
    dependents = {n: len(nx.ancestors(graph, n)) for n in nodes}
    max_dep = max(dependents.values()) or 1
    pagerank = nx.pagerank(graph, alpha=0.85)
    betweenness = nx.betweenness_centrality(graph, normalized=True)
    in_deg = dict(graph.in_degree())
    out_deg = dict(graph.out_degree())
    max_pr = max(pagerank.values()) or 1
    max_bt = max(betweenness.values()) or 1
    max_in = max(in_deg.values()) or 1
    max_out = max(out_deg.values()) or 1
    return {
        n: {
            "dependents": dependents[n],
            "dependency_impact": math.log1p(dependents[n]) / math.log1p(max_dep),
            "pagerank": pagerank[n] / max_pr,
            "betweenness": betweenness[n] / max_bt,
            "in_degree": in_deg[n] / max_in,
            "out_degree": out_deg[n] / max_out,
        }
        for n in nodes
    }


def exposure_features(graph: nx.DiGraph, assets: dict[str, dict]) -> dict[str, dict]:
    """Features that change when an algorithm is migrated."""
    exposure = {n: ALGORITHMS[assets[n]["algorithm"]]["exposure"] for n in graph.nodes}
    vulnerable = {n: ALGORITHMS[assets[n]["algorithm"]]["quantum_vulnerable"] for n in graph.nodes}
    out = {}
    for n in graph.nodes:
        succ = list(graph.successors(n))
        protective = [s for s in succ if graph.edges[n, s]["relation"] in PROTECTIVE]
        inherited, inherited_from = 0.0, None
        for s in protective:
            if exposure[s] > inherited:
                inherited, inherited_from = exposure[s], s
        neighbours = set(succ) | set(graph.predecessors(n))
        out[n] = {
            "inherited_exposure": inherited,
            "inherited_from": inherited_from,
            "succ_qv_frac": (sum(vulnerable[s] for s in succ) / len(succ)) if succ else 0.0,
            "neighbor_mean_exposure": (sum(exposure[s] for s in neighbours) / len(neighbours)) if neighbours else 0.0,
        }
    return out


def dependents_of(graph: nx.DiGraph, node: str) -> dict:
    direct = sorted(graph.predecessors(node))
    everything = sorted(nx.ancestors(graph, node))
    return {"direct": direct, "all": everything}


def layout(graph: nx.DiGraph, seed: int) -> dict[str, tuple[float, float]]:
    pos = nx.spring_layout(graph.to_undirected(), seed=seed, iterations=80, k=0.12)
    return {n: (float(x), float(y)) for n, (x, y) in pos.items()}
