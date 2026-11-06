"""Rule-based post-quantum risk score from the project blueprint.

Risk = 100 x (0.25 CryptoExposure + 0.20 DataSensitivity + 0.15 Retention
              + 0.15 ExternalExposure + 0.15 DependencyImpact
              + 0.10 BusinessCriticality)

Every factor is scaled to 0-1, so the score runs from 0 to 100.
"""
from __future__ import annotations

from qmigrate.engine.catalog import ALGORITHMS

WEIGHTS = {
    "crypto_exposure": 0.25,
    "data_sensitivity": 0.20,
    "retention": 0.15,
    "external_exposure": 0.15,
    "dependency_impact": 0.15,
    "business_criticality": 0.10,
}

FACTOR_LABELS = {
    "crypto_exposure": "Crypto exposure",
    "data_sensitivity": "Data sensitivity",
    "retention": "Data retention",
    "external_exposure": "External exposure",
    "dependency_impact": "Dependency impact",
    "business_criticality": "Business criticality",
}

EXTERNAL = {"internet": 1.0, "partner": 0.6, "internal": 0.2}
CLASSES = ["Low", "Medium", "High", "Critical"]
CLASS_MIDPOINT = {"Low": 20.0, "Medium": 45.0, "High": 65.0, "Critical": 85.0}


def components(asset: dict, structural: dict) -> dict[str, float]:
    return {
        "crypto_exposure": ALGORITHMS[asset["algorithm"]]["exposure"],
        "data_sensitivity": asset["data_sensitivity"] / 5,
        "retention": min(asset["retention_years"] / 20, 1.0),
        "external_exposure": EXTERNAL[asset["exposure"]],
        "dependency_impact": structural["dependency_impact"],
        "business_criticality": asset["business_criticality"] / 5,
    }


def score(comp: dict[str, float], weights: dict[str, float] = WEIGHTS) -> float:
    return round(100 * sum(weights[k] * comp[k] for k in weights), 1)


def contributions(comp: dict[str, float], weights: dict[str, float] = WEIGHTS) -> list[dict]:
    return [
        {
            "factor": k,
            "label": FACTOR_LABELS[k],
            "value": round(comp[k], 3),
            "weight": weights[k],
            "points": round(100 * weights[k] * comp[k], 1),
        }
        for k in weights
    ]


def calibrate_thresholds(scores: list[float], labels: list[str]) -> list[float]:
    """Pick 3 cut-offs so the rule-based classes have the same proportions as
    the analyst labels in the training data (fair baseline)."""
    ordered = sorted(scores)
    n = len(ordered)
    cuts, cumulative = [], 0
    for cls in CLASSES[:-1]:
        cumulative += sum(1 for l in labels if l == cls)
        idx = min(max(cumulative, 0), n - 1)
        cuts.append(round(ordered[idx], 2))
    return cuts


def classify(value: float, thresholds: list[float]) -> str:
    return CLASSES[sum(value >= t for t in thresholds)]
