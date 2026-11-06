"""Thesis evaluation: quantum deadlines and explanations versus the rule-based baseline.

Run it on the PC after the platform has measured the real websites at least once (start_demo.bat):

    .venv\\Scripts\\python -m qmigrate.research.evaluate

It reads every workspace in the local database (Demo Finance Co. = real bank and payment sites,
Demo Health Group = real hospital and health sites, plus any cloud accounts you connected), and
writes data/research/evaluation_<date>.md and .json. Nothing is changed in the database.

What it measures
  A. Quantum deadline (Mosca) versus the rule baseline
     * how many assets are late / urgent / soon / planned, under three expert CRQC scenarios
     * of the assets whose migration should start within 12 months, how many the rule baseline
       would rank lower (Low or Medium class, or outside its top-N), and how many fall outside Wave 1
     * Spearman correlation between the rule score and the urgency (years left before work must start)
  B. Explanations
     * faithfulness (deletion test): resetting the 3 inputs the explanation names should change the
       AI's prediction far more than resetting 3 random inputs
     * agreement: overlap between the factors the formula names and the factors the AI relied on
     * class agreement between the AI and the formula, and how often the explanation has to explain
       a disagreement
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from qmigrate.config import DATA_DIR, Settings
from qmigrate.engine import deadline as dl
from qmigrate.engine import explain as xai
from qmigrate.engine import models
from qmigrate.engine.estate import Estate, clean


def evaluate_estate(est: Estate, scenario: str = dl.DEFAULT_SCENARIO, k: int = 3) -> dict:
    rows = est.view["rows"]
    dls = est.deadlines(scenario)
    queue = {x["asset_id"]: x for x in est.queue()}

    # ---------------- A. deadlines versus the rule baseline
    exposed = [n for n in est.ids if dls[n]["status"] in ("late", "urgent", "soon", "planned")]
    urgent = [n for n in exposed if dls[n]["status"] in ("late", "urgent")]
    by_rule = sorted(est.ids, key=lambda n: -rows[n]["rule_score"])
    top_n = set(by_rule[:len(urgent)])
    rule_low = [n for n in urgent if rows[n]["rule_class"] in ("Low", "Medium")]
    ai_low = [n for n in urgent if rows[n]["ai_class"] in ("Low", "Medium")]
    outside_w1 = [n for n in urgent if queue.get(n, {}).get("wave") != "Wave 1"]
    rho = None
    if len(exposed) >= 3:
        r = spearmanr([rows[n]["rule_score"] for n in exposed], [-dls[n]["years_left"] for n in exposed])
        rho = None if np.isnan(r.statistic) else round(float(r.statistic), 3)
    deadlines = {
        "scenario": scenario,
        "counts": dl.summarize(dls)["counts"],
        "by_scenario": {s: dl.summarize(est.deadlines(s))["counts"] for s in dl.SCENARIOS},
        "harvest_risk": dl.summarize(dls)["harvest_risk"],
        "urgent_assets": len(urgent),
        "urgent_rule_low_or_medium": len(rule_low),
        "urgent_ai_low_or_medium": len(ai_low),
        "urgent_in_rule_top_n": len(set(urgent) & top_n),
        "urgent_outside_wave1": len(outside_w1),
        "spearman_rule_score_vs_urgency": rho,
        "examples_missed_by_rule": [
            {"asset_id": n, "algorithm": rows[n]["algorithm"], "rule_class": rows[n]["rule_class"],
             "rule_score": rows[n]["rule_score"], "start_by": dls[n]["start_by"], "finish_by": dls[n]["finish_by"],
             "sentence": dl.sentence(dls[n], rows[n])}
            for n in sorted(rule_low, key=lambda n: dls[n]["years_left"])[:5]],
    }

    # ---------------- B. explanations
    model = est.bundle["models"][models.PRIMARY]
    x = est.view["features"]["graph"]
    test_idx = [i for i, n in enumerate(est.ids) if rows[n]["split"] == "test"] or list(range(len(est.ids)))
    faith = xai.faithfulness(model, x[test_idx], est.bundle["baseline"], k=k)
    jacc, jacc_agree, jacc_disagree, generic = [], [], [], 0
    for i, n in enumerate(est.ids):
        r = rows[n]
        attr = models.local_attribution(model, x[i], est.bundle["baseline"], top=len(x[i]))
        f_rule = xai.factors(r)["raising"][:3]
        f_ai = xai.ai_factors(attr)
        j = xai.agreement(f_rule, f_ai)
        jacc.append(j)
        (jacc_agree if r["ai_class"] == r["rule_class"] else jacc_disagree).append(j)
        generic += "no single factor" in xai.why(r) or "moderately high" in xai.why(r)
    same = sum(rows[n]["ai_class"] == rows[n]["rule_class"] for n in est.ids)
    res = est.bundle["results"]
    explanations = {
        "faithfulness": faith,
        "factor_agreement_jaccard": round(float(np.mean(jacc)), 3),
        "factor_agreement_when_classes_agree": round(float(np.mean(jacc_agree)), 3) if jacc_agree else None,
        "factor_agreement_when_classes_differ": round(float(np.mean(jacc_disagree)), 3) if jacc_disagree else None,
        "class_agreement_ai_vs_rule": round(same / len(est.ids), 3),
        "disagreements_explained": len(est.ids) - same,
        "generic_sentences": generic,
        "macro_f1_rule": res["rule_based"].get("macro_f1"),
        "macro_f1_ai": res[models.PRIMARY].get("macro_f1"),
    }
    return clean({"assets": len(est.ids), "deadlines": deadlines, "explanations": explanations})


def _estates(settings: Settings):
    from qmigrate.server.db import Database
    from qmigrate.server.services import Platform
    platform = Platform(settings, Database(settings.database_url, settings.database_admin_url))
    with platform.db.session(admin=True) as c:
        tenants = c.all("SELECT id, name FROM tenants ORDER BY created_at")
    for t in tenants:
        est = platform.estate(t["id"])
        if est is not None:
            yield t["name"], est


def to_markdown(results: dict) -> str:
    out = [f"# Q-MigrateAI evaluation, {results['date']}", "",
           f"Scenario for deadlines: **{dl.SCENARIOS[results['scenario']]['label']}**. "
           "Data: the workspaces in the local database (real public websites and any connected cloud accounts).", ""]
    for name, r in results["workspaces"].items():
        d, e = r["deadlines"], r["explanations"]
        c = d["counts"]
        out += [f"## {name} ({r['assets']} assets)", "",
                "### A. Quantum deadline versus the rule baseline", "",
                "| Scenario | Late | Urgent (<1 y) | Soon (<3 y) | Planned | Replace now (classical) | Quantum-safe |",
                "|---|---|---|---|---|---|---|"]
        for s, cc in d["by_scenario"].items():
            out.append(f"| {dl.SCENARIOS[s]['label']} | {cc['late']} | {cc['urgent']} | {cc['soon']} | {cc['planned']} | "
                       f"{cc['classical']} | {cc['safe']} |")
        out += ["",
                f"* Assets whose migration must start within 12 months: **{d['urgent_assets']}** "
                f"({c['late']} already late). {d['harvest_risk']} carry data exposed to harvest-now-decrypt-later.",
                f"* The rule baseline puts **{d['urgent_rule_low_or_medium']}** of them in Low or Medium; the AI model "
                f"{d['urgent_ai_low_or_medium']}.",
                f"* Only {d['urgent_in_rule_top_n']} of {d['urgent_assets']} appear in the rule baseline's top {d['urgent_assets']}; "
                f"{d['urgent_outside_wave1']} fall outside Wave 1 of the current queue.",
                f"* Spearman correlation between rule score and urgency: **{d['spearman_rule_score_vs_urgency']}** "
                "(1 = the risk score already orders assets by deadline).", ""]
        if d["examples_missed_by_rule"]:
            out += ["Examples the rule baseline under-rates:", ""]
            out += [f"* `{x['asset_id']}` ({x['algorithm']}, rule {x['rule_class']} {x['rule_score']}): {x['sentence']}"
                    for x in d["examples_missed_by_rule"]]
            out.append("")
        f = e["faithfulness"]
        out += ["### B. Explanations", "",
                "| Measure | Value |", "|---|---|",
                f"| Probability drop when the 3 explained inputs are removed | {f['explained_drop']} |",
                f"| Probability drop when 3 random inputs are removed | {f['random_drop']} |",
                f"| Faithfulness ratio (explained / random) | {f['ratio']} |",
                f"| Prediction changes: explained vs random | {f['explained_flip_rate']} vs {f['random_flip_rate']} |",
                f"| Factor overlap AI vs formula (Jaccard, 0-1) | {e['factor_agreement_jaccard']} |",
                f"| ... when AI and formula give the same class | {e['factor_agreement_when_classes_agree']} |",
                f"| ... when they give different classes | {e['factor_agreement_when_classes_differ']} |",
                f"| Same class, AI vs formula | {e['class_agreement_ai_vs_rule']} |",
                f"| Disagreements the explanation describes | {e['disagreements_explained']} |",
                f"| Macro-F1 formula / AI (test split) | {e['macro_f1_rule']} / {e['macro_f1_ai']} |", ""]
    out += ["## How to read this", "",
            "* A deadline is late when `CRQC year - data secrecy years - migration years` is already in the past "
            "(Mosca's theorem), capped by NIST IR 8547's 2035 cut-off for RSA and ECC.",
            "* A low Spearman value or many urgent assets in Low/Medium means a risk score alone does not tell you "
            "*when* to act: the deadline adds information the baseline lacks.",
            "* A faithfulness ratio well above 1 means the reasons shown to the user really drive the model.",
            "* Labels come from the platform's published rubric, not from human analysts, so F1 compares the models "
            "with that rubric. The deadline result does not depend on those labels.", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--scenario", default=dl.DEFAULT_SCENARIO, choices=list(dl.SCENARIOS))
    p.add_argument("--out", default=str(DATA_DIR / "research"))
    args = p.parse_args(argv)
    results = {"date": date.today().isoformat(), "scenario": args.scenario, "workspaces": {}}
    for name, est in _estates(Settings()):
        print(f"evaluating {name} ({len(est.ids)} assets) ...")
        results["workspaces"][name] = evaluate_estate(est, args.scenario)
    if not results["workspaces"]:
        print("No workspace has data yet. Start the platform once (start_demo.bat) so it measures the websites.")
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"evaluation_{results['date']}"
    stem.with_suffix(".json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    stem.with_suffix(".md").write_text(to_markdown(results), encoding="utf-8")
    print(f"written {stem}.md and {stem}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
