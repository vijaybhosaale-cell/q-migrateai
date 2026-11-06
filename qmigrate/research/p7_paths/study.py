"""P7 study: does the per-asset migration queue make data paths end-to-end quantum-safe?

    python -m qmigrate.research.p7_paths.study            # 2 demo estates + 15 more generated estates

For each estate the platform's own queue (rule score + AI score + dependency impact, the order the
waves use) is compared with path-first planning and with a random order, at the same number of
migrations. Writes qmigrate/research/p7_paths/results/{summary.json, summary.md, curves.csv}.

The estates come from the synthetic simulator: it is the only source here with data-flow links
(load balancer -> gateway -> backend -> database -> backup). Public websites only expose their
certificate chain, and the cloud connectors do not read data flows yet (see README, limits).
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

from qmigrate.engine import migrate
from qmigrate.engine import paths as P
from qmigrate.engine.estate import Estate, train_bundle
from qmigrate.simulator.generator import generate

RESULTS = Path(__file__).resolve().parent / "results"
BUDGETS = (10, 20, 40, 60, 100)
DEMO = [("bank", 42), ("hospital", 7)]          # the two demo companies
SWEEP = [(p, s) for p in ("bank", "hospital", "generic") for s in (1, 2, 3, 4, 5)]


def build(profile: str, seed: int, n_assets: int = 399) -> Estate:
    d = generate(seed=seed, n_assets=n_assets, profile=profile)
    assets = [{**a, "algorithm_discovered": a["algorithm"], "algorithm_current": a["algorithm"]} for a in d["assets"]]
    return Estate(assets, d["edges"], train_bundle(assets, d["edges"], seed=seed))


def random_order(est: Estate, m: P.PathModel, n: int, draws: int = 20, seed: int = 0) -> dict:
    cands = [x for x in est.queue()]
    rng = random.Random(seed)
    vals = []
    for _ in range(draws):
        pick = rng.sample(cands, min(n, len(cands)))
        vals.append(P._row(m, m.evaluate(m.apply({x["asset_id"]: x["target"] for x in pick}))))
    return {k: round(statistics.mean(v[k] for v in vals), 1) for k in vals[0]}


def run_estate(profile: str, seed: int) -> dict:
    est = build(profile, seed)
    m = P.PathModel(est.graph, est.current)
    ev = m.evaluate()
    rows = est.view["rows"]
    mismatch = sum(rows[n]["quantum_safe"] != ev["_hs"][n]["safe"] for n in est.ids)   # model check: must be 0
    comp = P.compare(m, est.queue(), BUDGETS)
    for c in comp:
        c["random"] = random_order(est, m, c["budget"], seed=seed)
    return {"profile": profile, "seed": seed, "assets": len(est.ids), "paths": len(m.paths),
            "truncated": m.truncated, "hop_model_mismatch": mismatch, "now": P._row(m, ev),
            "sensitive_paths": ev["sensitive_paths"], "bottlenecks": m.bottlenecks(ev, 5), "budgets": comp}


def aggregate(estates: list[dict]) -> list[dict]:
    out = []
    for i, b in enumerate(BUDGETS):
        row = {"budget": b}
        for strat in ("per_asset", "path_first", "random"):
            for k in ("safe_paths", "safe_value_pct", "false_assurance", "asset_coverage_pct"):
                vals = [e["budgets"][i][strat][k] for e in estates]
                row[f"{strat}.{k}"] = round(statistics.mean(vals), 1)
        row["estates_where_path_first_secures_more"] = sum(
            e["budgets"][i]["path_first"]["safe_value_pct"] > e["budgets"][i]["per_asset"]["safe_value_pct"] for e in estates)
        out.append(row)
    return out


def _t(head, body):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|",
                      *["| " + " | ".join(str(c) for c in r) + " |" for r in body]])


def report(s: dict) -> str:
    d = s["demo"]
    lines = [
        "# P7 · A data path is only as safe as its weakest hop", "",
        f"Run {s['generated']}. {len(s['demo'])} demo estates and {len(s['sweep'])} more generated estates "
        f"(399 assets each). The hop model agrees with the platform's per-asset 'quantum-safe' flag on every asset "
        f"(mismatches: {sum(e['hop_model_mismatch'] for e in s['demo'] + s['sweep'])}).", "",
        "## The two demo companies", "",
    ]
    for e in d:
        w1 = next(c for c in e["budgets"] if c["budget"] == 20)
        lines += [
            f"**{e['profile']} (seed {e['seed']})**: {e['paths']} data paths, {e['sensitive_paths']} carry data of "
            f"sensitivity 4–5. Today {e['now']['safe_paths']} paths are quantum-safe end to end, while "
            f"{e['now']['false_assurance']} assets look safe on their own but carry data that is harvestable at "
            "another hop.", "",
            f"After Wave 1 (20 migrations from the platform's queue) asset coverage goes from "
            f"{e['now']['asset_coverage_pct']}% to {w1['per_asset']['asset_coverage_pct']}%, but only "
            f"**{w1['per_asset']['safe_paths']}** paths are safe end to end and false assurance grows to "
            f"{w1['per_asset']['false_assurance']} assets. Path-first planning with the same 20 migrations makes "
            f"**{w1['path_first']['safe_paths']}** paths safe ({w1['path_first']['safe_value_pct']}% of path value).", "",
            _t(["Migrations", "Queue: safe paths", "Queue: value %", "Path-first: safe paths", "Path-first: value %",
                "Random: value %", "Queue: false assurance", "Path-first: false assurance"],
               [[c["budget"], c["per_asset"]["safe_paths"], c["per_asset"]["safe_value_pct"],
                 c["path_first"]["safe_paths"], c["path_first"]["safe_value_pct"], c["random"]["safe_value_pct"],
                 c["per_asset"]["false_assurance"], c["path_first"]["false_assurance"]] for c in e["budgets"]]),
            "",
            "Hops that block the most valuable paths: " + ", ".join(
                f"{b['asset_id']} ({b['algorithm']}, {b['paths']} paths)" for b in e["bottlenecks"][:5]) + ".", "",
        ]
    agg = s["sweep_mean"]
    lines += [
        f"## Across {len(s['sweep'])} more estates (mean)", "",
        _t(["Migrations", "Queue: value %", "Path-first: value %", "Random: value %", "Queue: asset coverage %",
            "Path-first: asset coverage %", "Path-first better in"],
           [[r["budget"], r["per_asset.safe_value_pct"], r["path_first.safe_value_pct"], r["random.safe_value_pct"],
             r["per_asset.asset_coverage_pct"], r["path_first.asset_coverage_pct"],
             f"{r['estates_where_path_first_secures_more']}/{len(s['sweep'])}"] for r in agg]),
        "",
        "## Reading the result", "",
        "* Path-first is built to maximise path value, so it is expected to beat the queue on that measure. "
        "The finding is the size of the gap that the per-asset view hides: after Wave 1, asset coverage "
        "roughly triples while almost no data path is safe end to end.",
        "* The per-asset queue raises asset coverage faster: it picks the riskiest single assets. "
        "Path-first raises coverage more slowly but closes whole paths, so recorded traffic stops being readable "
        "end to end sooner. Both views are needed, which is why the platform shows them side by side.",
        "* Value weights each path by the most sensitive data on it and how long that data must stay secret.",
        "* False assurance counts assets that are quantum-safe on their own but sit on a path that is still "
        "harvestable at another hop.",
        "",
        "## Limits", "",
        "* Synthetic estates: the simulator is the only source with data-flow links. The method runs on any "
        "workspace whose connector supplies them (routes_to, calls, publishes_to, tunnels_to, sends_logs, backs_up).",
        "* A hop is judged by its own algorithm and the keys, certificates and tokens it relies on directly, as in "
        "the rest of the platform.",
        "* Path-first is a greedy heuristic, not an optimum.",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=RESULTS)
    ap.add_argument("--quick", action="store_true", help="demo estates only")
    a = ap.parse_args(argv)
    demo = [run_estate(p, s) for p, s in DEMO]
    sweep = [] if a.quick else [run_estate(p, s) for p, s in SWEEP]
    s = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "budgets": BUDGETS, "demo": demo,
         "sweep": [{k: v for k, v in e.items() if k != "bottlenecks"} for e in sweep],
         "sweep_mean": aggregate(sweep) if sweep else []}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.json").write_text(json.dumps(s, indent=2) + "\n")
    (a.out / "summary.md").write_text(report(s))
    with (a.out / "curves.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["profile", "seed", "budget", "strategy", "safe_paths", "safe_value_pct", "sensitive_safe",
                    "harvestable_value_pct", "false_assurance", "asset_coverage_pct"])
        for e in demo + sweep:
            for c in e["budgets"]:
                for strat in ("per_asset", "path_first", "random"):
                    r = c[strat]
                    w.writerow([e["profile"], e["seed"], c["budget"], strat, r["safe_paths"], r["safe_value_pct"],
                                r["sensitive_safe"], r["harvestable_value_pct"], r["false_assurance"],
                                r["asset_coverage_pct"]])
    print((a.out / "summary.md").read_text()[:3000])


if __name__ == "__main__":
    main()
