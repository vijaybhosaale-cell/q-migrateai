"""P7: weakest-hop data paths.

A request or a record crosses several assets: load balancer -> API gateway -> backend -> database ->
backup. "Harvest now, decrypt later" needs only ONE of those hops to be readable, so a path is only
as quantum-safe as its weakest hop. Per-asset scores cannot show this: a load balancer that already
offers hybrid ML-KEM looks done, while the data it carries is still recorded in the clear one hop later.

This module
  * builds the data-flow graph from the dependency graph (only edges along which data moves),
  * enumerates entry-to-sink paths and finds each path's weakest hop,
  * reports "false assurance" (assets that look safe on their own but sit on a harvestable path),
  * ranks the hops that block the most sensitive paths, and
  * plans migrations path-first under a budget, to compare with the per-asset queue.

A hop is safe exactly when the platform calls the asset quantum-safe: its own algorithm is post-quantum
or symmetric-strong AND no key, certificate or token it relies on is quantum-vulnerable (the same rule
as Estate._view, computed here without the AI models so it is cheap to re-evaluate).
"""
from __future__ import annotations

from collections import defaultdict

import networkx as nx

from qmigrate.engine import migrate
from qmigrate.engine.catalog import ALGORITHMS, SAFE_STATUSES
from qmigrate.engine.graph import PROTECTIVE

INHERIT_THRESHOLD = 0.85          # same as Estate
# Relations along which data moves, with the direction the data travels.
FLOW_FORWARD = {"routes_to", "calls", "publishes_to", "tunnels_to", "sends_logs"}
FLOW_REVERSED = {"backs_up"}      # 'backup -> database' means data flows database -> backup
MAX_PATHS = 20_000
MAX_LEN = 10
SENSITIVE = 4                      # data sensitivity 4-5 on the 1-5 scale


def flow_graph(graph: nx.DiGraph) -> nx.DiGraph:
    f = nx.DiGraph()
    for u, v, d in graph.edges(data=True):
        rel = d.get("relation")
        if rel in FLOW_FORWARD:
            f.add_edge(u, v, relation=rel)
        elif rel in FLOW_REVERSED:
            f.add_edge(v, u, relation=rel)
    return f


def hop_safety(graph: nx.DiGraph, state: dict[str, dict], nodes=None) -> dict[str, dict]:
    """Per asset: safe / exposed, and why (own algorithm or the key it relies on)."""
    out = {}
    for n in (nodes if nodes is not None else graph.nodes):
        alg = ALGORITHMS[state[n]["algorithm"]]
        worst, worst_from = 0.0, None
        for s in graph.successors(n):
            if graph.edges[n, s].get("relation") in PROTECTIVE:
                e = ALGORITHMS[state[s]["algorithm"]]["exposure"]
                if e > worst:
                    worst, worst_from = e, s
        exposed = bool(alg["quantum_vulnerable"] or worst >= INHERIT_THRESHOLD)
        out[n] = {
            "safe": (not exposed) and alg["status"] in SAFE_STATUSES,
            "exposed": exposed,
            "own_unsafe": bool(alg["quantum_vulnerable"] or alg["status"] not in SAFE_STATUSES),
            "blocked_by": worst_from if worst >= INHERIT_THRESHOLD else None,
            "exposure": max(alg["exposure"], worst),
        }
    return out


def enumerate_paths(f: nx.DiGraph, max_paths: int = MAX_PATHS, max_len: int = MAX_LEN) -> tuple[list[list[str]], bool]:
    """Every simple path from an entry (no incoming flow) to a sink (no outgoing flow)."""
    sources = sorted(n for n in f.nodes if f.in_degree(n) == 0 and f.out_degree(n) > 0)
    sinks = {n for n in f.nodes if f.out_degree(n) == 0}
    paths: list[list[str]] = []
    truncated = False
    for s in sources:
        stack = [(s, [s])]
        while stack:
            node, path = stack.pop()
            nxt = [m for m in sorted(f.successors(node), reverse=True) if m not in path]
            if node in sinks or not nxt or len(path) >= max_len:
                if len(path) > 1:
                    paths.append(path)
                    if len(paths) >= max_paths:
                        return paths, True
                continue
            for m in nxt:
                stack.append((m, path + [m]))
    return paths, truncated


class PathModel:
    """Paths of one estate. `state` maps asset id -> asset dict with the current 'algorithm'."""

    def __init__(self, graph: nx.DiGraph, state: dict[str, dict]):
        self.graph = graph
        self.state = state
        self.flow = flow_graph(graph)
        self.paths, self.truncated = enumerate_paths(self.flow)
        self.value = [self._value(p) for p in self.paths]
        self.by_node: dict[str, list[int]] = defaultdict(list)
        for i, p in enumerate(self.paths):
            for n in p:
                self.by_node[n].append(i)
        # protective predecessors: migrating a key changes these hops
        self.protected_by: dict[str, set[str]] = defaultdict(set)
        for u, v, d in graph.edges(data=True):
            if d.get("relation") in PROTECTIVE:
                self.protected_by[v].add(u)

    def _value(self, path: list[str]) -> float:
        """Harvest value: the most sensitive data on the path, weighted by how long it must stay secret."""
        sens = max(self.state[n]["data_sensitivity"] for n in path)
        ret = max(self.state[n]["retention_years"] for n in path)
        return round(sens / 5 * (1 + min(ret, 20) / 20), 4)

    # ------------------------------------------------------------ evaluation
    def evaluate(self, state: dict[str, dict] | None = None) -> dict:
        state = state or self.state
        hs = hop_safety(self.graph, state)
        safe_paths = [all(hs[n]["safe"] for n in p) for p in self.paths]
        harvest = [any(hs[n]["exposed"] for n in p) for p in self.paths]
        total_v = sum(self.value) or 1.0
        sens_idx = [i for i, p in enumerate(self.paths) if max(state[n]["data_sensitivity"] for n in p) >= SENSITIVE]
        on_path = set(self.by_node)
        false_assurance = sorted(n for n in on_path if hs[n]["safe"]
                                 and any(harvest[i] for i in self.by_node[n]))
        return {
            "paths": len(self.paths),
            "safe_paths": sum(safe_paths),
            "harvestable_paths": sum(harvest),
            "safe_value_pct": round(100 * sum(v for v, s in zip(self.value, safe_paths) if s) / total_v, 1),
            "harvestable_value_pct": round(100 * sum(v for v, h in zip(self.value, harvest) if h) / total_v, 1),
            "sensitive_paths": len(sens_idx),
            "sensitive_safe": sum(safe_paths[i] for i in sens_idx),
            "assets_on_paths": len(on_path),
            "safe_assets_on_paths": sum(hs[n]["safe"] for n in on_path),
            "false_assurance": false_assurance,
            "_hs": hs, "_safe": safe_paths, "_harvest": harvest,
        }

    def weakest_hop(self, path: list[str], hs: dict[str, dict]) -> str | None:
        unsafe = [n for n in path if not hs[n]["safe"]]
        if not unsafe:
            return None
        return max(unsafe, key=lambda n: (hs[n]["exposure"], self.state[n]["data_sensitivity"], n))

    def bottlenecks(self, ev: dict, top: int = 15) -> list[dict]:
        """Unsafe hops ranked by the value of the harvestable paths they sit on; 'sole' counts paths
        where this hop (or the key behind it) is the only thing left to fix."""
        hs = ev["_hs"]
        score: dict[str, float] = defaultdict(float)
        count: dict[str, int] = defaultdict(int)
        sole: dict[str, int] = defaultdict(int)
        for i, p in enumerate(self.paths):
            if ev["_safe"][i]:
                continue
            needed = self.requirements(p, hs)
            for n in needed:
                score[n] += self.value[i]
                count[n] += 1
            if len(needed) == 1:
                sole[next(iter(needed))] += 1
        ranked = sorted(score, key=lambda n: (-score[n], n))[:top]
        return [{"asset_id": n, "paths": count[n], "only_fix_needed": sole[n], "value": round(score[n], 2),
                 "algorithm": self.state[n]["algorithm"], "service_type": self.state[n]["service_type"]}
                for n in ranked]

    # ------------------------------------------------------------ planning
    def requirements(self, path: list[str], hs: dict[str, dict], state: dict | None = None) -> set[str]:
        """The migrations that make every hop of this path safe: the hop itself when its own algorithm is
        not safe, plus the vulnerable key/certificate/token it relies on."""
        state = state or self.state
        need: set[str] = set()
        for n in path:
            if hs[n]["safe"]:
                continue
            if hs[n]["own_unsafe"]:
                need.add(n)
            for s in self.graph.successors(n):
                if (self.graph.edges[n, s].get("relation") in PROTECTIVE
                        and ALGORITHMS[state[s]["algorithm"]]["exposure"] >= INHERIT_THRESHOLD):
                    need.add(s)
        return need

    def apply(self, changes: dict[str, str], state: dict | None = None) -> dict[str, dict]:
        state = dict(state or self.state)
        for n, alg in changes.items():
            state[n] = {**state[n], "algorithm": alg}
        return state

    def plan_path_first(self, budget: int) -> list[dict]:
        """Greedy: repeatedly secure the path with the best value per migration still needed, until the
        budget (number of migrations) is used. Paths whose fix needs an asset with no recommended
        target are skipped."""
        state = dict(self.state)
        chosen: list[dict] = []
        picked: set[str] = set()
        while len(chosen) < budget:
            hs = hop_safety(self.graph, state)
            best, best_ratio = None, 0.0
            for i, p in enumerate(self.paths):
                if all(hs[n]["safe"] for n in p):
                    continue
                need = self.requirements(p, hs, state) - picked
                if not need or len(chosen) + len(need) > budget:
                    continue
                recs = {n: migrate.recommend(state[n]) for n in need}
                if any(r is None for r in recs.values()):
                    continue
                ratio = self.value[i] / len(need)
                if ratio > best_ratio:
                    best, best_ratio = (i, recs), ratio
            if best is None:
                break
            i, recs = best
            for n in sorted(recs):
                chosen.append({"asset_id": n, "target": recs[n]["target"], "for_path": i})
                picked.add(n)
                state[n] = {**state[n], "algorithm": recs[n]["target"]}
        return chosen

    def path_rows(self, ev: dict, limit: int = 200) -> list[dict]:
        hs = ev["_hs"]
        order = sorted(range(len(self.paths)), key=lambda i: (ev["_safe"][i], -self.value[i], i))[:limit]
        rows = []
        for i in order:
            p = self.paths[i]
            w = self.weakest_hop(p, hs)
            rows.append({
                "id": i, "hops": p, "value": self.value[i], "safe": ev["_safe"][i], "harvestable": ev["_harvest"][i],
                "weakest_hop": w, "weakest_reason": (None if w is None else
                                                     (f"relies on {hs[w]['blocked_by']}" if hs[w]["blocked_by"]
                                                      and not hs[w]["own_unsafe"] else self.state[w]["algorithm"])),
                "safe_hops": sum(hs[n]["safe"] for n in p),
                "max_sensitivity": max(self.state[n]["data_sensitivity"] for n in p),
            })
        return rows


def public(ev: dict) -> dict:
    return {k: v for k, v in ev.items() if not k.startswith("_")}


def _row(model: PathModel, ev: dict) -> dict:
    hs = ev["_hs"]
    total = len(hs) or 1
    return {"safe_paths": ev["safe_paths"], "safe_value_pct": ev["safe_value_pct"],
            "sensitive_safe": ev["sensitive_safe"], "harvestable_value_pct": ev["harvestable_value_pct"],
            "false_assurance": len(ev["false_assurance"]),
            "asset_coverage_pct": round(100 * sum(h["safe"] for h in hs.values()) / total, 1)}


def compare(model: PathModel, queue: list[dict], budgets=(10, 20, 40, 60)) -> list[dict]:
    """Same number of migrations, two orders: the per-asset queue (the platform's plan) and path-first."""
    out = []
    for n in budgets:
        n = min(n, len(queue))
        per_asset = model.evaluate(model.apply({x["asset_id"]: x["target"] for x in queue[:n]}))
        plan = model.plan_path_first(n)
        path_first = model.evaluate(model.apply({x["asset_id"]: x["target"] for x in plan}))
        out.append({"budget": n, "per_asset": _row(model, per_asset), "path_first": _row(model, path_first),
                    "path_first_used": len(plan)})
    return out
