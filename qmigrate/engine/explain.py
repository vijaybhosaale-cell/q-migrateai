"""Plain-language explanations of risk scores.

Two layers:
  * `why()`  - one sentence built from the rule formula's own contributions, e.g.
               "High risk because it uses RSA-2048, which a quantum computer can break, its data must
               stay secret for 10 years, and 5 other systems depend on it."
               The formula is additive, so these reasons are exact: the factors named are the ones that
               add the most points.
  * `ai_note()` - what the neural network looked at (occlusion attributions from models.local_attribution),
               mapped to the same six factors, and whether it agrees with the formula. When the two
               disagree the note says which signal causes the difference.

`faithfulness()` and `agreement()` are the measurements used in the thesis evaluation
(qmigrate.research.evaluate): do the named reasons really drive the model, and do the AI and the
formula point at the same reasons.
"""
from __future__ import annotations

import numpy as np

from qmigrate.engine import models, risk
from qmigrate.engine.catalog import ALGORITHMS, USAGE_TEXT

# Each model input belongs to one of the formula's six factors.
FEATURE_FACTOR = {
    "crypto_exposure": "crypto_exposure", "quantum_vulnerable": "crypto_exposure",
    "inherited_exposure": "crypto_exposure", "succ_qv_frac": "crypto_exposure",
    "neighbor_mean_exposure": "crypto_exposure",
    "usage_key_exchange": "crypto_exposure", "usage_key_wrapping": "crypto_exposure",
    "usage_signature": "crypto_exposure", "usage_data_encryption": "crypto_exposure",
    "usage_hashing": "crypto_exposure",
    "data_sensitivity": "data_sensitivity", "retention": "retention",
    "external_exposure": "external_exposure", "business_criticality": "business_criticality",
    "dependency_impact": "dependency_impact", "pagerank": "dependency_impact", "betweenness": "dependency_impact",
    "in_degree": "dependency_impact", "out_degree": "dependency_impact",
}
HIGH, LOW = 0.6, 0.25


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def raising_phrase(factor: str, r: dict) -> str:
    alg = ALGORITHMS[r["algorithm"]]
    if factor == "crypto_exposure":
        if alg["quantum_vulnerable"]:
            return f"it uses {r['algorithm']} for {USAGE_TEXT[r['usage']]}, which a quantum computer can break"
        if r.get("inherited_from") and r.get("inherited_exposure", 0) >= 0.85:
            return f"its data is protected by {r['inherited_from']}, which a quantum computer can break"
        return f"it uses {r['algorithm']}, which is already weak"
    return {
        "data_sensitivity": f"it holds sensitivity {r['data_sensitivity']}/5 data",
        "retention": f"its data must stay secret for {r['retention_years']:g} years",
        "external_exposure": "it is reachable from the internet" if r["exposure"] == "internet" else "it is open to partner networks",
        "dependency_impact": (f"{r['dependents']} other systems depend on it" if r["dependents"] != 1
                              else "another system depends on it"),
        "business_criticality": f"it is business-critical ({r['business_criticality']}/5)",
    }[factor]


def lowering_phrase(factor: str, r: dict) -> str:
    return {
        "crypto_exposure": f"it uses {r['algorithm']}, which is quantum-safe",
        "data_sensitivity": f"its data is only sensitivity {r['data_sensitivity']}/5",
        "retention": (f"its data only needs to stay secret for {r['retention_years']:g} years"
                      if r["retention_years"] >= 1 else "its data does not need to stay secret for long"),
        "external_exposure": "it is not reachable from the internet",
        "dependency_impact": "no other system depends on it" if r["dependents"] == 0 else "few systems depend on it",
        "business_criticality": f"it is not business-critical ({r['business_criticality']}/5)",
    }[factor]


def factors(r: dict) -> dict:
    """Formula contributions, sorted, split into factors that raise and lower the score."""
    contrib = risk.contributions(r["components"])
    up = sorted((c for c in contrib if c["value"] >= HIGH), key=lambda c: -c["points"])
    down = sorted((c for c in contrib if c["value"] <= LOW), key=lambda c: -c["weight"])
    return {"raising": [c["factor"] for c in up], "lowering": [c["factor"] for c in down], "contributions": contrib}


def why(r: dict, cls: str | None = None) -> str:
    cls = cls or r["ai_class"]
    f = factors(r)
    raising = f["raising"]
    inherited = (not ALGORITHMS[r["algorithm"]]["quantum_vulnerable"] and r.get("inherited_from")
                 and r.get("inherited_exposure", 0) >= 0.85)
    if inherited and "crypto_exposure" not in raising:
        raising = ["crypto_exposure"] + raising        # its own cipher is fine, but the key protecting it is not
    up = [raising_phrase(k, r) for k in raising[:3]]
    down = [lowering_phrase(k, r) for k in f["lowering"] if not (inherited and k == "crypto_exposure")][:2]
    if cls in ("High", "Critical"):
        return f"{cls} risk because {_join(up)}." if up else f"{cls} risk: several factors are moderately high."
    if up and down:
        return f"{cls} risk: {_join(up)}, but {_join(down)}."
    if down:
        return f"{cls} risk because {_join(down)}."
    return f"{cls} risk: no single factor stands out." if not up else f"{cls} risk: {_join(up)}."


def ai_factors(attributions: list[dict], top: int = 3) -> list[str]:
    """Rule factors the AI leaned on most (positive occlusion impact), most important first."""
    out = []
    for a in sorted(attributions, key=lambda a: -a["impact"]):
        if a["impact"] <= 0:
            break
        k = FEATURE_FACTOR[a["feature"]]
        if k not in out:
            out.append(k)
        if len(out) == top:
            break
    return out


def ai_note(r: dict, attributions: list[dict]) -> str:
    signals = [a["label"].lower() for a in sorted(attributions, key=lambda a: -a["impact"]) if a["impact"] > 0][:2]
    sig = _join(signals) if signals else "no single input"
    if r["ai_class"] == r["rule_class"]:
        return f"The AI model and the formula agree ({r['ai_class']}). The AI's strongest signals were {sig}."
    direction = "higher" if risk.CLASSES.index(r["ai_class"]) > risk.CLASSES.index(r["rule_class"]) else "lower"
    return (f"The AI model rates it {r['ai_class']}, {direction} than the formula ({r['rule_class']}). "
            f"The difference comes mainly from {sig}, which the formula does not weigh the same way.")


def explanation(r: dict, attributions: list[dict]) -> dict:
    f = factors(r)
    return {"summary": why(r), "ai_note": ai_note(r, attributions),
            "formula_factors": f["raising"][:3], "ai_factors": ai_factors(attributions),
            "formula_class": r["rule_class"], "ai_class": r["ai_class"]}


# ------------------------------------------------------------------ evaluation
def agreement(rule_top: list[str], ai_top: list[str]) -> float:
    """Jaccard overlap of the factors named by the formula and by the AI."""
    a, b = set(rule_top), set(ai_top)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def faithfulness(model, x: np.ndarray, baseline: np.ndarray, k: int = 3, seed: int = 0, random_draws: int = 20) -> dict:
    """Deletion test. For each asset, reset the k inputs the explanation names to their training
    average and measure the drop in the predicted class's probability; compare with resetting k
    random inputs. A faithful explanation causes a much larger drop than random."""
    rng = np.random.default_rng(seed)
    n_feat = x.shape[1]
    proba = model.predict_proba(x)
    cls = proba.argmax(axis=1)
    explained, randoms, flips_e, flips_r = [], [], 0, 0
    for i in range(len(x)):
        attr = models.local_attribution(model, x[i], baseline, top=n_feat)
        names = models.ASSET_FEATURES + models.GRAPH_FEATURES
        top = [names.index(a["feature"]) for a in attr[:k]]
        xe = x[i].copy()
        xe[top] = baseline[top]
        pe = model.predict_proba(xe[None, :])[0]
        explained.append(proba[i, cls[i]] - pe[cls[i]])
        flips_e += int(pe.argmax() != cls[i])
        xr = np.repeat(x[i][None, :], random_draws, axis=0)
        for j in range(random_draws):
            idx = rng.choice(n_feat, size=k, replace=False)
            xr[j, idx] = baseline[idx]
        pr = model.predict_proba(xr)
        randoms.append(float(np.mean(proba[i, cls[i]] - pr[:, cls[i]])))
        flips_r += float(np.mean(pr.argmax(axis=1) != cls[i]))
    n = max(len(x), 1)
    e, r = float(np.mean(explained)), float(np.mean(randoms))
    return {"k": k, "assets": len(x), "explained_drop": round(e, 3), "random_drop": round(r, 3),
            "ratio": round(e / r, 2) if r > 1e-9 else None,
            "explained_flip_rate": round(flips_e / n, 3), "random_flip_rate": round(flips_r / n, 3)}
