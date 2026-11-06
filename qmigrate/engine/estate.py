"""One tenant's cryptographic estate: graph, risk scores, plan, what-if and simulations.

The Estate is pure computation. It never touches the database: the server
loads assets/edges/model from PostgreSQL, builds an Estate, and persists any
change (a migration) itself. That keeps the AI logic testable on its own.

Two states are kept:
  * discovered: the algorithms as first found by discovery (the "before")
  * current:    the algorithms after migrations (the "after")
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np

from qmigrate.engine import graph as g
from qmigrate.engine import deadline as dl
from qmigrate.engine import explain as xai
from qmigrate.engine import migrate, models, paths, risk
from qmigrate.engine.catalog import ALGORITHMS, MIGRATION_EFFORT, SAFE_STATUSES, SERVICE_LABELS, USAGE_TEXT

INHERIT_THRESHOLD = 0.85
WAVES = [(20, "Wave 1"), (60, "Wave 2"), (10**9, "Wave 3")]
POINTS_PER_PERSON_DAY = 10
DEADLINE_FIELDS = ("status", "finish_by", "start_by", "years_left", "crqc_year", "fix_asset")  # assumption shown in the UI: 10 effort points ~ 1 person-day


def clean(obj):
    """Convert numpy types (and NaN) into plain JSON-safe Python values."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return clean(obj.tolist())
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        value = float(obj)
        return None if math.isnan(value) or math.isinf(value) else value
    return obj


def wave_of(rank: int) -> str:
    for limit, name in WAVES:
        if rank <= limit:
            return name
    return WAVES[-1][1]


# ---------------------------------------------------------------- training
def train_bundle(assets: list[dict], edges: list[dict], seed: int = 42) -> dict:
    """Train all five models on the discovered state (expensive: ~10-40 s)."""
    ids = [a["asset_id"] for a in assets]
    state = {a["asset_id"]: {**a, "algorithm": a["algorithm_discovered"]} for a in assets}
    graph = g.build_graph(list(state.values()), edges)
    structural = g.structural_metrics(graph)
    prop = models.propagation_matrices(graph, ids)
    expo = g.exposure_features(graph, state)
    comps = {n: risk.components(state[n], structural[n]) for n in ids}
    feats = models.build_features(ids, state, comps, structural, expo, prop)
    rule_scores = np.array([risk.score(comps[n]) for n in ids])
    labels = np.array([models.CLASSES.index(state[n]["analyst_label"]) for n in ids])
    bundle = models.train_all(feats, rule_scores, labels, seed)
    bundle["train_ids"] = sorted(ids[i] for i in bundle["train_idx"])
    bundle["label_distribution"] = dict(Counter(state[n]["analyst_label"] for n in ids))
    return bundle


class Estate:
    def __init__(self, assets: list[dict], edges: list[dict], bundle: dict, positions: dict | None = None):
        if not assets:
            raise ValueError("an estate needs at least one asset")
        self.ids = [a["asset_id"] for a in assets]
        self.discovered = {a["asset_id"]: {**a, "algorithm": a["algorithm_discovered"]} for a in assets}
        self.current = {a["asset_id"]: {**a, "algorithm": a["algorithm_current"]} for a in assets}
        self.edges = edges
        self.graph = g.build_graph(list(self.discovered.values()), edges)
        self.structural = g.structural_metrics(self.graph)
        self.prop = models.propagation_matrices(self.graph, self.ids)
        self.bundle = bundle
        self.train_ids = set(bundle.get("train_ids", []))
        self._positions = positions
        self.baseline_view = self._view(self.discovered)
        self.view = self._view(self.current)
        self._queue_cache = None
        self._whatif_cache = None
        self._deadline_cache: dict[str, dict] = {}
        self._paths_cache: dict | None = None

    # ------------------------------------------------------------ internals
    def _features(self, state: dict):
        expo = g.exposure_features(self.graph, state)
        comps = {n: risk.components(state[n], self.structural[n]) for n in self.ids}
        feats = models.build_features(self.ids, state, comps, self.structural, expo, self.prop)
        return expo, comps, feats

    def _view(self, state: dict) -> dict:
        expo, comps, feats = self._features(state)
        proba = self.bundle["models"][models.PRIMARY].predict_proba(feats["graph"])
        thresholds = self.bundle["thresholds"]
        rows = {}
        for i, n in enumerate(self.ids):
            a = state[n]
            alg = ALGORITHMS[a["algorithm"]]
            p = proba[i]
            inherited = expo[n]["inherited_exposure"]
            exposed = alg["quantum_vulnerable"] or inherited >= INHERIT_THRESHOLD
            rule_score = risk.score(comps[n])
            rows[n] = {
                "asset_id": n,
                "cloud": a["cloud"], "region": a["region"], "application": a["application"],
                "owner_team": a.get("owner_team", ""), "service_type": a["service_type"],
                "service_label": SERVICE_LABELS[a["service_type"]], "usage": a["usage"],
                "protocol": a["protocol"], "algorithm": a["algorithm"],
                "algorithm_discovered": self.discovered[n]["algorithm"],
                "algorithm_status": alg["status"], "exposure": a["exposure"],
                "data_sensitivity": a["data_sensitivity"], "retention_years": a["retention_years"],
                "business_criticality": a["business_criticality"],
                "clients_support_pqc": bool(a["clients_support_pqc"]),
                "analyst_label": a.get("analyst_label"),
                "quantum_vulnerable": bool(alg["quantum_vulnerable"]),
                "inherited_exposure": round(inherited, 3),
                "inherited_from": expo[n]["inherited_from"],
                "quantum_exposed": bool(exposed),
                "quantum_safe": bool((not exposed) and alg["status"] in SAFE_STATUSES),
                "dependents": self.structural[n]["dependents"],
                "components": {k: round(v, 3) for k, v in comps[n].items()},
                "rule_score": rule_score,
                "rule_class": risk.classify(rule_score, thresholds),
                "ai_class": models.CLASSES[int(np.argmax(p))],
                "ai_score": round(float(sum(p[k] * risk.CLASS_MIDPOINT[c] for k, c in enumerate(models.CLASSES))), 1),
                "ai_confidence": round(float(np.max(p)), 3),
                "ai_probabilities": {c: round(float(p[k]), 3) for k, c in enumerate(models.CLASSES)},
                "split": "train" if n in self.train_ids else "test",
            }
        return {"rows": rows, "features": feats}

    @staticmethod
    def _kpis(view: dict) -> dict:
        rows = list(view["rows"].values())
        total = len(rows)
        safe = sum(r["quantum_safe"] for r in rows)
        return {
            "total_assets": total,
            "quantum_vulnerable": sum(r["quantum_vulnerable"] for r in rows),
            "quantum_exposed": sum(r["quantum_exposed"] for r in rows),
            "quantum_safe": safe,
            "coverage_pct": round(100 * safe / total, 1) if total else 0.0,
            "critical": sum(r["ai_class"] == "Critical" for r in rows),
            "high_critical": sum(r["ai_class"] in ("High", "Critical") for r in rows),
            "mean_ai_score": round(sum(r["ai_score"] for r in rows) / total, 1) if total else 0.0,
            "mean_rule_score": round(sum(r["rule_score"] for r in rows) / total, 1) if total else 0.0,
        }

    def _summary(self, view: dict) -> dict:
        rows = list(view["rows"].values())
        by_cloud = {}
        for cloud in sorted({r["cloud"] for r in rows}):
            rs = [r for r in rows if r["cloud"] == cloud]
            by_cloud[cloud] = {
                "assets": len(rs),
                "quantum_exposed": sum(r["quantum_exposed"] for r in rs),
                "quantum_safe": sum(r["quantum_safe"] for r in rs),
                "needs_review": sum((not r["quantum_exposed"]) and (not r["quantum_safe"]) for r in rs),
                "critical": sum(r["ai_class"] == "Critical" for r in rs),
            }
        return {
            **self._kpis(view),
            "ai_classes": {c: sum(r["ai_class"] == c for r in rows) for c in models.CLASSES},
            "by_cloud": by_cloud,
            "by_algorithm": dict(Counter(r["algorithm"] for r in rows)),
        }

    def _state_with(self, changes: dict[str, str]) -> dict:
        state = dict(self.current)
        for n, alg in changes.items():
            state[n] = {**state[n], "algorithm": alg}
        return state

    # ------------------------------------------------------------ read API
    def overview(self) -> dict:
        return clean({"now": self._summary(self.view), "before": self._summary(self.baseline_view)})

    def assets(self) -> list[dict]:
        dls = self.deadlines()
        return clean([{**r, "why": xai.why(r), "deadline": {k: dls[n].get(k) for k in DEADLINE_FIELDS}}
                      for n, r in self.view["rows"].items()])

    # ------------------------------------------------------------ quantum deadlines (Mosca)
    def deadlines(self, scenario: str = dl.DEFAULT_SCENARIO) -> dict[str, dict]:
        if scenario not in self._deadline_cache:
            rows = self.view["rows"]
            self._deadline_cache[scenario] = {n: dl.deadline_for(rows[n], rows, scenario) for n in self.ids}
        return self._deadline_cache[scenario]

    def deadline_overview(self, scenario: str = dl.DEFAULT_SCENARIO) -> dict:
        """Deadline per asset, ordered by when work must start, plus the same counts for every scenario."""
        rows = self.view["rows"]
        dls = self.deadlines(scenario)
        rank = {x["asset_id"]: x for x in self.queue()}
        items = []
        for n, d in dls.items():
            if d["status"] == "safe":
                continue
            r = rows[n]
            items.append({"asset_id": n, "application": r["application"], "service_label": r["service_label"],
                          "cloud": r["cloud"], "algorithm": r["algorithm"], "ai_class": r["ai_class"],
                          "rule_score": r["rule_score"], "queue_rank": rank.get(n, {}).get("rank"),
                          "queue_wave": rank.get(n, {}).get("wave"), "sentence": dl.sentence(d, r), **d})
        order = {s: i for i, s in enumerate(dl.STATUS_ORDER)}
        items.sort(key=lambda x: (order[x["status"]], x["start_by"] if x["start_by"] is not None else 9999,
                                  -x["rule_score"], x["asset_id"]))
        return clean({"scenario": scenario, "summary": dl.summarize(dls),
                      "by_scenario": {k: dl.summarize(self.deadlines(k)) for k in dl.SCENARIOS},
                      "items": items, "assumptions": dl.assumptions()})

    def positions(self) -> dict:
        if self._positions is None:
            self._positions = g.layout(self.graph, 42)
        return self._positions

    def graph_data(self) -> dict:
        rows = self.view["rows"]
        pos = self.positions()
        nodes = [{
            "id": n, "x": round(pos[n][0], 2), "y": round(pos[n][1], 2),
            "cloud": rows[n]["cloud"], "service_label": rows[n]["service_label"],
            "application": rows[n]["application"], "algorithm": rows[n]["algorithm"],
            "ai_class": rows[n]["ai_class"], "ai_score": rows[n]["ai_score"],
            "quantum_safe": rows[n]["quantum_safe"], "quantum_exposed": rows[n]["quantum_exposed"],
            "dependents": rows[n]["dependents"], "exposure": rows[n]["exposure"],
        } for n in self.ids]
        edges = [{"source": u, "target": v, "relation": d["relation"]} for u, v, d in self.graph.edges(data=True)]
        return clean({"nodes": nodes, "edges": edges})

    def dependents(self, asset_id: str) -> dict:
        return clean(g.dependents_of(self.graph, asset_id))

    def models_summary(self) -> dict:
        b = self.bundle
        table = [{"key": key, **models.MODEL_INFO[key], **b["results"][key]} for key in models.MODEL_ORDER]
        return clean({
            "primary": models.PRIMARY, "models": table, "curve": b["curve"], "importance": b["importance"],
            "thresholds": b["thresholds"], "classes": models.CLASSES,
            "architecture": {
                "inputs": len(models.ASSET_FEATURES) + len(models.GRAPH_FEATURES),
                "hidden": list(models.HIDDEN), "outputs": len(models.CLASSES),
                "activation": "ReLU", "optimizer": "Adam", "epochs": models.EPOCHS,
            },
            "split": {"train": len(b["train_idx"]), "test": len(b["test_idx"])},
            "label_distribution": b.get("label_distribution", {}),
            "seed": b["seed"],
        })

    def reasons(self, r: dict) -> list[str]:
        alg = ALGORITHMS[r["algorithm"]]
        usage = USAGE_TEXT[r["usage"]]
        out = []
        if alg["quantum_vulnerable"]:
            out.append(f"Uses {r['algorithm']} for {usage}. Shor's algorithm on a large quantum computer can break it.")
        elif alg["status"] == "legacy-weak":
            out.append(f"Uses {r['algorithm']} for {usage}, which is already weak against classical attacks.")
        elif r["algorithm"] == "AES-128":
            out.append("Uses AES-128. Grover's algorithm halves its effective strength, so AES-256 is preferred.")
        else:
            out.append(f"Uses {r['algorithm']} for {usage}, which is considered quantum-safe.")
        if not alg["quantum_vulnerable"] and r["inherited_exposure"] >= INHERIT_THRESHOLD and r["inherited_from"]:
            src = self.current[r["inherited_from"]]
            out.append(f"It relies on {r['inherited_from']} ({SERVICE_LABELS[src['service_type']]}, {src['algorithm']}), "
                       "which a quantum computer can break, so its protection is only as strong as that key.")
        if r["quantum_exposed"] and r["data_sensitivity"] >= 4 and r["retention_years"] >= 7:
            out.append(f"It holds sensitivity {r['data_sensitivity']}/5 data kept for {r['retention_years']} years: "
                       "an attacker can harvest it now and decrypt it later.")
        if r["exposure"] == "internet":
            out.append("It is reachable from the internet, so its traffic can be recorded by anyone on the path.")
        elif r["exposure"] == "partner":
            out.append("It is exposed to partner networks.")
        if r["dependents"] >= 10:
            out.append(f"{r['dependents']} other assets depend on it, so a break would spread widely.")
        if r["business_criticality"] == 5:
            out.append("It is marked business-critical (5/5).")
        return out

    def explain(self, asset_id: str) -> dict:
        r = self.view["rows"][asset_id]
        i = self.ids.index(asset_id)
        attributions = models.local_attribution(self.bundle["models"][models.PRIMARY],
                                                self.view["features"]["graph"][i], self.bundle["baseline"])
        why = xai.explanation(r, attributions)
        d = self.deadlines()[asset_id]
        first = [why["summary"], why["ai_note"]] + ([dl.sentence(d, r)] if dl.sentence(d, r) else [])
        return clean({
            "asset": {k: v for k, v in r.items() if k not in ("components", "ai_probabilities")},
            "rule": {"score": r["rule_score"], "class": r["rule_class"],
                     "contributions": risk.contributions(r["components"]), "thresholds": self.bundle["thresholds"]},
            "ai": {"model": models.MODEL_INFO[models.PRIMARY]["name"], "class": r["ai_class"], "score": r["ai_score"],
                   "confidence": r["ai_confidence"], "probabilities": r["ai_probabilities"],
                   "attributions": attributions},
            "reasons": first + self.reasons(r),
            "why": why,
            "deadline": {**d, "sentence": dl.sentence(d, r)},
            "recommendation": migrate.recommend(self.current[asset_id]),
            "targets": migrate.allowed_targets(self.current[asset_id]),
            "dependents": g.dependents_of(self.graph, asset_id),
        })

    def queue(self) -> list[dict]:
        if self._queue_cache is not None:
            return self._queue_cache
        items = []
        dls = self.deadlines()
        for n, r in self.view["rows"].items():
            rec = migrate.recommend(self.current[n])
            if rec is None:
                continue
            effort = MIGRATION_EFFORT[r["service_type"]]
            priority = (0.40 * r["rule_score"] + 0.35 * r["ai_score"]
                        + 15 * self.structural[n]["dependency_impact"] + 0.10 * (100 - effort))
            items.append({
                "asset_id": n, "cloud": r["cloud"], "application": r["application"],
                "service_label": r["service_label"], "algorithm": r["algorithm"], "target": rec["target"],
                "standard": rec["standard"], "reason": rec["reason"], "rule_score": r["rule_score"],
                "ai_class": r["ai_class"], "ai_score": r["ai_score"], "dependents": r["dependents"],
                "exposure": r["exposure"], "effort": effort, "priority": round(priority, 1),
                "finish_by": dls[n]["finish_by"], "deadline_status": dls[n]["status"],
            })
        items.sort(key=lambda x: (-x["priority"], x["asset_id"]))
        for rank, item in enumerate(items, start=1):
            item["rank"] = rank
            item["wave"] = wave_of(rank)
        self._queue_cache = clean(items)
        return self._queue_cache

    # ------------------------------------------------------------ data paths (P7)
    def path_report(self) -> dict:
        """End-to-end view: each data path is as quantum-safe as its weakest hop (see engine/paths.py)."""
        if self._paths_cache is not None:
            return self._paths_cache
        m = paths.PathModel(self.graph, self.current)
        if not m.paths:
            self._paths_cache = {"has_paths": False, "paths": 0}
            return self._paths_cache
        ev = m.evaluate()
        before = m.evaluate(self.discovered)
        rows = self.view["rows"]
        label = lambda n: {"asset_id": n, "service_label": rows[n]["service_label"],  # noqa: E731
                           "application": rows[n]["application"], "algorithm": rows[n]["algorithm"],
                           "safe": rows[n]["quantum_safe"]}
        wave1 = sum(1 for x in self.queue() if x["wave"] == "Wave 1")
        plan = m.plan_path_first(wave1) if wave1 else []
        top = m.path_rows(ev, limit=150)
        for r in top:
            r["hops"] = [label(n) for n in r["hops"]]
        self._paths_cache = clean({
            "has_paths": True,
            "now": paths._row(m, ev) | {"paths": ev["paths"], "sensitive_paths": ev["sensitive_paths"],
                                        "harvestable_paths": ev["harvestable_paths"]},
            "discovered": paths._row(m, before) | {"paths": before["paths"]},
            "truncated": m.truncated,
            "false_assurance": [label(n) for n in ev["false_assurance"]][:100],
            "bottlenecks": [b | {"service_label": rows[b["asset_id"]]["service_label"],
                                 "application": rows[b["asset_id"]]["application"]} for b in m.bottlenecks(ev, 12)],
            "paths": top,
            "comparison": paths.compare(m, self.queue(), sorted({wave1, 60}) if wave1 else (20, 60)),
            "path_first_wave": [{**x, "service_label": rows[x["asset_id"]]["service_label"],
                                 "algorithm": rows[x["asset_id"]]["algorithm"]} for x in plan],
            "wave1_size": wave1,
        })
        return self._paths_cache

    def plan(self) -> dict:
        q = self.queue()
        waves = []
        for _, name in WAVES:
            items = [x for x in q if x["wave"] == name]
            effort = sum(x["effort"] for x in items)
            waves.append({"name": name, "assets": len(items), "effort_points": effort,
                          "person_days": round(effort / POINTS_PER_PERSON_DAY, 1)})
        return {"queue": q, "waves": waves, "points_per_person_day": POINTS_PER_PERSON_DAY}

    def whatif_curve(self, max_n: int = 60) -> list[dict]:
        """Projected KPIs if the top-n assets of today's queue were migrated (n = 0..max_n)."""
        if self._whatif_cache is not None and self._whatif_cache[0] >= max_n:
            return [p for p in self._whatif_cache[1] if p["n"] <= max_n]
        q = self.queue()
        max_n = min(max_n, len(q))
        points, effort = [], 0
        for n in range(0, max_n + 1):
            if n:
                effort += q[n - 1]["effort"]
            changes = {x["asset_id"]: x["target"] for x in q[:n]}
            kpis = self._kpis(self._view(self._state_with(changes))) if n else self._kpis(self.view)
            points.append({"n": n, **kpis, "effort_points": effort,
                           "person_days": round(effort / POINTS_PER_PERSON_DAY, 1)})
        self._whatif_cache = (max_n, clean(points))
        return self._whatif_cache[1]

    def simulate(self, asset_id: str, target: str) -> dict:
        """What a migration of one asset would do, without changing anything."""
        before_view = self.view
        cur = self.current[asset_id]
        dependents = [self.current[d] for d in self.graph.predecessors(asset_id)]
        checks = migrate.validation_checks(cur, target, dependents)
        after_view = self._view(self._state_with({asset_id: target}))
        b, a = before_view["rows"][asset_id], after_view["rows"][asset_id]
        ripple = []
        for n in self.ids:
            if n == asset_id:
                continue
            x, y = before_view["rows"][n], after_view["rows"][n]
            if x["quantum_safe"] != y["quantum_safe"] or abs(x["ai_score"] - y["ai_score"]) >= 0.5:
                ripple.append({"asset_id": n, "service_label": y["service_label"], "algorithm": y["algorithm"],
                               "class_before": x["ai_class"], "class_after": y["ai_class"],
                               "score_before": x["ai_score"], "score_after": y["ai_score"],
                               "now_quantum_safe": y["quantum_safe"]})
        ripple.sort(key=lambda r: r["score_after"] - r["score_before"])
        return clean({
            "asset_id": asset_id, "from": cur["algorithm"], "to": target,
            "standard": ALGORITHMS[target].get("standard", ""),
            "checks": checks, "valid": all(c["result"] != "FAIL" for c in checks),
            "rule_before": b["rule_score"], "rule_after": a["rule_score"],
            "ai_before": b["ai_score"], "ai_after": a["ai_score"],
            "class_before": b["ai_class"], "class_after": a["ai_class"],
            "kpis_before": self._kpis(before_view), "kpis_after": self._kpis(after_view),
            "ripple": ripple,
        })

    def wave_steps(self, wave: str = "Wave 1") -> list[dict]:
        """Migrate a wave one asset at a time (pure). Each step carries the KPIs and the
        nodes whose risk class changed, so the UI can animate it."""
        targets = [x for x in self.queue() if x["wave"] == wave]
        changes: dict[str, str] = {}
        prev = self.view
        steps = []
        for item in targets:
            changes[item["asset_id"]] = item["target"]
            view = self._view(self._state_with(changes))
            changed = [{"id": n, "ai_class": view["rows"][n]["ai_class"], "quantum_safe": view["rows"][n]["quantum_safe"]}
                       for n in self.ids
                       if view["rows"][n]["ai_class"] != prev["rows"][n]["ai_class"]
                       or view["rows"][n]["quantum_safe"] != prev["rows"][n]["quantum_safe"]]
            steps.append({"asset_id": item["asset_id"], "from": item["algorithm"], "to": item["target"],
                          "standard": item["standard"],
                          "rule_before": prev["rows"][item["asset_id"]]["rule_score"],
                          "rule_after": view["rows"][item["asset_id"]]["rule_score"],
                          "ai_before": prev["rows"][item["asset_id"]]["ai_score"],
                          "ai_after": view["rows"][item["asset_id"]]["ai_score"],
                          "class_before": prev["rows"][item["asset_id"]]["ai_class"],
                          "class_after": view["rows"][item["asset_id"]]["ai_class"],
                          "kpis": self._kpis(view), "changed": changed})
            prev = view
        return clean(steps)

    def report(self) -> dict:
        before, after = self.baseline_view["rows"], self.view["rows"]
        changes = []
        for n in self.ids:
            b, a = before[n], after[n]
            if b["algorithm"] != a["algorithm"] or b["quantum_safe"] != a["quantum_safe"] or abs(b["ai_score"] - a["ai_score"]) >= 0.5:
                changes.append({"asset_id": n, "service_label": a["service_label"], "cloud": a["cloud"],
                                "algorithm_before": b["algorithm"], "algorithm_after": a["algorithm"],
                                "class_before": b["ai_class"], "class_after": a["ai_class"],
                                "score_before": b["ai_score"], "score_after": a["ai_score"],
                                "quantum_safe_after": a["quantum_safe"],
                                "directly_migrated": b["algorithm"] != a["algorithm"]})
        changes.sort(key=lambda x: x["score_after"] - x["score_before"])
        top_risks = sorted(after.values(), key=lambda r: -r["ai_score"])[:10]
        return clean({"before": self._summary(self.baseline_view), "after": self._summary(self.view),
                      "changes": changes, "deadlines": dl.summarize(self.deadlines()),
                      "deadline_items": self.deadline_overview()["items"][:15],
                      "top_risks": [{k: r[k] for k in ("asset_id", "service_label", "cloud", "algorithm", "ai_class",
                                                       "ai_score", "dependents", "exposure")} for r in top_risks]})

    def readiness(self, discovery_age_days: float | None, migrations_done: int) -> dict:
        """Indicative post-quantum readiness, built from checks in the spirit of NIST's
        PQC transition guidance. Not a certification."""
        rows = list(self.view["rows"].values())

        def pct(selected, ok) -> float | None:
            sel = [r for r in rows if selected(r)]
            return round(100 * sum(ok(r) for r in sel) / len(sel), 1) if sel else None

        pqc_ok = lambda r: r["algorithm_status"] in ("pqc", "hybrid")  # noqa: E731
        items = [
            {"key": "inventory", "title": "Cryptographic inventory is current",
             "detail": "A discovery scan ran in the last 30 days.",
             "score": 100.0 if discovery_age_days is not None and discovery_age_days <= 30 else 0.0},
            {"key": "internet_kex", "title": "Internet-facing key exchange uses hybrid or PQC",
             "detail": "Share of internet-facing key-exchange endpoints on ML-KEM or hybrid ML-KEM.",
             "score": pct(lambda r: r["exposure"] == "internet" and r["usage"] == "key_exchange", pqc_ok)},
            {"key": "hndl", "title": "Long-lived sensitive data is quantum-safe",
             "detail": "Share of assets with sensitivity 4-5 and retention of 7+ years whose whole protection chain is quantum-safe.",
             "score": pct(lambda r: r["data_sensitivity"] >= 4 and r["retention_years"] >= 7, lambda r: r["quantum_safe"])},
            {"key": "signatures", "title": "Signatures and trust anchors use ML-DSA / SLH-DSA",
             "detail": "Share of signing assets (certificate authorities, code signing, SSO) on PQC or hybrid signatures.",
             "score": pct(lambda r: r["usage"] == "signature", pqc_ok)},
            {"key": "legacy", "title": "No legacy algorithms (3DES, SHA-1)",
             "detail": "Share of symmetric and hashing assets not using classically weak algorithms.",
             "score": pct(lambda r: r["usage"] in ("data_encryption", "hashing"),
                          lambda r: r["algorithm_status"] != "legacy-weak")},
            {"key": "agility", "title": "Crypto-agility exercised",
             "detail": "At least one validated migration with a stored rollback path.",
             "score": 100.0 if migrations_done > 0 else 0.0},
        ]
        scored = [i["score"] for i in items if i["score"] is not None]
        overall = round(sum(scored) / len(scored), 1) if scored else 0.0
        return clean({"overall": overall, "items": items,
                      "note": "Indicative readiness score built from checks aligned with NIST post-quantum "
                              "transition guidance (FIPS 203/204/205). It is not a certification."})
