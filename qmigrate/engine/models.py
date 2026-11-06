"""Machine-learning models that predict an asset's risk class.

Five approaches are compared on the same train/test split and with 5-fold
cross-validation (the core result for the research paper):

1. rule_based  - the blueprint's weighted formula, thresholds calibrated on
                 the training split (transparent baseline)
2. rf_asset    - Random Forest on the asset's own features
3. mlp_asset   - neural network (MLP 64-32) on the asset's own features
4. mlp_graph   - the same neural network plus graph features
                 (dependency impact, PageRank, inherited key/cert exposure ...)
5. gnn_sign    - graph neural network in the SIGN style: asset features are
                 averaged over 1- and 2-hop neighbours (message passing), then
                 fed to the MLP (Frasca et al., 2020, "SIGN: Scalable Inception
                 Graph Neural Networks").

`mlp_graph` is the primary model used for the migration queue and the
explanations, because its inputs have readable names.
"""
from __future__ import annotations

import warnings

import networkx as nx
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.inspection import permutation_importance
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from qmigrate.engine.catalog import ALGORITHMS, USAGES
from qmigrate.engine import risk

CLASSES = risk.CLASSES
HIDDEN = (64, 32)
EPOCHS = 200
PRIMARY = "mlp_graph"

ASSET_FEATURES = [
    "crypto_exposure", "quantum_vulnerable", "data_sensitivity", "retention",
    "external_exposure", "business_criticality",
] + [f"usage_{u}" for u in USAGES]

GRAPH_FEATURES = [
    "dependency_impact", "pagerank", "betweenness", "in_degree", "out_degree",
    "inherited_exposure", "succ_qv_frac", "neighbor_mean_exposure",
]

FEATURE_LABELS = {
    "crypto_exposure": "Own algorithm's quantum exposure",
    "quantum_vulnerable": "Uses RSA / ECC / DH",
    "data_sensitivity": "Data sensitivity",
    "retention": "Data retention period",
    "external_exposure": "Internet / partner exposure",
    "business_criticality": "Business criticality",
    "usage_key_exchange": "Used for key exchange",
    "usage_key_wrapping": "Used for key wrapping",
    "usage_signature": "Used for signatures",
    "usage_data_encryption": "Used for data encryption",
    "usage_hashing": "Used for hashing",
    "dependency_impact": "Number of dependent assets",
    "pagerank": "Graph importance (PageRank)",
    "betweenness": "Bridge position (betweenness)",
    "in_degree": "Direct dependents",
    "out_degree": "Direct dependencies",
    "inherited_exposure": "Exposure inherited from its key / certificate",
    "succ_qv_frac": "Share of dependencies using RSA / ECC",
    "neighbor_mean_exposure": "Average exposure of neighbours",
}

MODEL_INFO = {
    "rule_based": {"name": "Rule-based formula", "family": "Baseline", "inputs": "6 weighted factors from the blueprint"},
    "rf_asset": {"name": "Random Forest", "family": "Classical ML", "inputs": "Asset features (11)"},
    "mlp_asset": {"name": "Neural network (MLP)", "family": "Neural network", "inputs": "Asset features (11)"},
    "mlp_graph": {"name": "Neural network + graph features", "family": "Neural network", "inputs": "Asset (11) + graph (8) features"},
    "gnn_sign": {"name": "Graph neural network (SIGN)", "family": "Graph neural network", "inputs": "Asset features + 2-hop message passing (44)"},
}
MODEL_ORDER = list(MODEL_INFO)


# ---------------------------------------------------------------- features
def build_features(ids: list[str], assets: dict, comps: dict, structural: dict,
                   exposure: dict, prop: tuple[np.ndarray, np.ndarray]) -> dict[str, np.ndarray]:
    asset_rows, graph_rows = [], []
    for n in ids:
        a, c, s, e = assets[n], comps[n], structural[n], exposure[n]
        asset_rows.append([
            c["crypto_exposure"], float(ALGORITHMS[a["algorithm"]]["quantum_vulnerable"]),
            c["data_sensitivity"], c["retention"], c["external_exposure"], c["business_criticality"],
        ] + [1.0 if a["usage"] == u else 0.0 for u in USAGES])
        graph_rows.append([
            s["dependency_impact"], s["pagerank"], s["betweenness"], s["in_degree"], s["out_degree"],
            e["inherited_exposure"], e["succ_qv_frac"], e["neighbor_mean_exposure"],
        ])
    x_asset = np.asarray(asset_rows, dtype=float)
    x_graph = np.hstack([x_asset, np.asarray(graph_rows, dtype=float)])
    a_out, a_in = prop
    x_sign = np.hstack([x_asset, a_out @ x_asset, a_out @ (a_out @ x_asset), a_in @ x_asset])
    return {"asset": x_asset, "graph": x_graph, "sign": x_sign}


def propagation_matrices(graph: nx.DiGraph, ids: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Row-normalised adjacency with self-loops: A_out averages over what an
    asset depends on, A_in over what depends on it."""
    index = {n: i for i, n in enumerate(ids)}
    n = len(ids)
    a_out = np.eye(n)
    a_in = np.eye(n)
    for u, v in graph.edges:
        a_out[index[u], index[v]] = 1.0
        a_in[index[v], index[u]] = 1.0
    a_out /= a_out.sum(axis=1, keepdims=True)
    a_in /= a_in.sum(axis=1, keepdims=True)
    return a_out, a_in


FEATURE_SET = {"rf_asset": "asset", "mlp_asset": "asset", "mlp_graph": "graph", "gnn_sign": "sign"}


# ------------------------------------------------------------------ models
def _mlp(seed: int) -> MLPClassifier:
    return MLPClassifier(hidden_layer_sizes=HIDDEN, activation="relu", solver="adam", alpha=1e-3,
                         learning_rate_init=1e-3, batch_size=32, max_iter=EPOCHS, random_state=seed)


def _make(key: str, seed: int):
    if key == "rf_asset":
        return RandomForestClassifier(n_estimators=300, min_samples_leaf=2, random_state=seed, n_jobs=1)
    return Pipeline([("scale", StandardScaler()), ("mlp", _mlp(seed))])


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 3),
        "macro_f1": round(float(f1_score(y_true, y_pred, labels=[0, 1, 2, 3], average="macro", zero_division=0)), 3),
        "critical_recall": round(float(recall_score(y_true == 3, y_pred == 3, zero_division=0)), 3),
        "high_critical_recall": round(float(recall_score(y_true >= 2, y_pred >= 2, zero_division=0)), 3),
        "confusion": confusion_matrix(y_true, y_pred, labels=[0, 1, 2, 3]).astype(int).tolist(),
    }


def _train_with_curve(x: np.ndarray, y: np.ndarray, tr: np.ndarray, te: np.ndarray, seed: int):
    scaler = StandardScaler().fit(x[tr])
    x_tr, x_te = scaler.transform(x[tr]), scaler.transform(x[te])
    mlp = _mlp(seed)
    classes = np.arange(len(CLASSES))
    curve = {"epoch": [], "loss": [], "train_accuracy": [], "test_accuracy": []}
    for epoch in range(1, EPOCHS + 1):
        mlp.partial_fit(x_tr, y[tr], classes=classes)
        if epoch == 1 or epoch % 2 == 0:
            curve["epoch"].append(epoch)
            curve["loss"].append(round(float(mlp.loss_), 4))
            curve["train_accuracy"].append(round(float((mlp.predict(x_tr) == y[tr]).mean()), 4))
            curve["test_accuracy"].append(round(float((mlp.predict(x_te) == y[te]).mean()), 4))
    return Pipeline([("scale", scaler), ("mlp", mlp)]), curve


def train_all(features: dict[str, np.ndarray], rule_scores: np.ndarray, y: np.ndarray, seed: int) -> dict:
    idx = np.arange(len(y))
    tr, te = train_test_split(idx, test_size=0.3, stratify=y, random_state=seed)
    results: dict[str, dict] = {}
    fitted: dict = {}
    curve: dict = {}

    def rule_predict(train_idx, scores_idx):
        cuts = risk.calibrate_thresholds(rule_scores[train_idx].tolist(), [CLASSES[i] for i in y[train_idx]])
        preds = np.array([CLASSES.index(risk.classify(s, cuts)) for s in rule_scores[scores_idx]])
        return preds, cuts

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=ConvergenceWarning)
        pred, thresholds = rule_predict(tr, te)
        results["rule_based"] = _metrics(y[te], pred)

        for key, fset in FEATURE_SET.items():
            x = features[fset]
            if key == PRIMARY:
                model, curve = _train_with_curve(x, y, tr, te, seed)
            else:
                model = _make(key, seed).fit(x[tr], y[tr])
            fitted[key] = model
            results[key] = _metrics(y[te], model.predict(x[te]))

        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
        for key in MODEL_ORDER:
            scores = []
            for ftr, fte in skf.split(idx, y):
                if key == "rule_based":
                    pred, _ = rule_predict(ftr, fte)
                else:
                    x = features[FEATURE_SET[key]]
                    pred = _make(key, seed).fit(x[ftr], y[ftr]).predict(x[fte])
                scores.append(float(f1_score(y[fte], pred, labels=[0, 1, 2, 3], average="macro", zero_division=0)))
            results[key]["cv_macro_f1_mean"] = round(float(np.mean(scores)), 3)
            results[key]["cv_macro_f1_std"] = round(float(np.std(scores)), 3)
            results[key]["cv_folds"] = [round(s, 3) for s in scores]

    names_graph = ASSET_FEATURES + GRAPH_FEATURES
    perm = permutation_importance(fitted[PRIMARY], features["graph"][te], y[te], scoring="f1_macro",
                                  n_repeats=10, random_state=seed)
    importance = {
        "random_forest": sorted(
            [{"feature": f, "label": FEATURE_LABELS[f], "importance": round(float(v), 4)}
             for f, v in zip(ASSET_FEATURES, fitted["rf_asset"].feature_importances_)],
            key=lambda r: -r["importance"]),
        "neural_network": sorted(
            [{"feature": f, "label": FEATURE_LABELS[f], "importance": round(float(m), 4), "std": round(float(s), 4)}
             for f, m, s in zip(names_graph, perm.importances_mean, perm.importances_std)],
            key=lambda r: -r["importance"]),
    }

    return {
        "models": fitted,
        "thresholds": thresholds,
        "train_idx": tr,
        "test_idx": te,
        "results": results,
        "curve": curve,
        "importance": importance,
        "baseline": features["graph"][tr].mean(axis=0),
        "seed": seed,
    }


def local_attribution(model, x_row: np.ndarray, baseline: np.ndarray, top: int = 8) -> list[dict]:
    """Occlusion explanation: replace one feature at a time with its training
    average and measure how much the predicted class's probability drops."""
    names = ASSET_FEATURES + GRAPH_FEATURES
    proba = model.predict_proba(x_row[None, :])[0]
    cls = int(np.argmax(proba))
    occluded = np.repeat(x_row[None, :], len(names), axis=0)
    occluded[np.arange(len(names)), np.arange(len(names))] = baseline
    drop = proba[cls] - model.predict_proba(occluded)[:, cls]
    order = np.argsort(-np.abs(drop))[:top]
    return [
        {"feature": names[j], "label": FEATURE_LABELS[names[j]], "value": round(float(x_row[j]), 3),
         "impact": round(float(drop[j]), 3)}
        for j in order
    ]
