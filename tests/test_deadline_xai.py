"""Quantum deadlines (Mosca) and plain-language explanations."""
from __future__ import annotations

import numpy as np
import pytest

from qmigrate.engine import deadline as dl
from qmigrate.engine import explain as xai

NOW = 2026.8


def row(**kw):
    base = {"asset_id": "TLS-bank.example", "algorithm": "X25519", "usage": "key_exchange", "service_type": "load_balancer",
            "quantum_exposed": True, "retention_years": 10, "dependents": 0, "clients_support_pqc": True,
            "inherited_from": None, "inherited_exposure": 0.0, "data_sensitivity": 5, "exposure": "internet",
            "business_criticality": 4, "ai_class": "High", "rule_class": "High",
            "components": {"crypto_exposure": 0.93, "data_sensitivity": 1.0, "retention": 0.5, "external_exposure": 1.0,
                           "dependency_impact": 0.0, "business_criticality": 0.8}}
    base.update(kw)
    return base


def test_mosca_deadline_for_a_bank_tls_endpoint():
    r = row()
    d = dl.deadline_for(r, {r["asset_id"]: r}, "expected", now=NOW)
    # X = 10 years of secrecy, CRQC 2038 -> must finish by 2028; Y = 0.5 + 2.5*25/100 = 1.1 years
    assert d["finish_by"] == 2028 and d["migration_years"] == 1.1 and d["start_by"] == 2026
    # X + Y = 11.1 years is just under Z = 11.2 years: not yet at risk, but work must start within 12 months
    assert d["status"] == "urgent" and not d["harvest_risk"] and d["driver"] == "mosca"
    assert "upgrade by 2028" in dl.sentence(d, r)


def test_health_data_kept_20_years_is_already_overdue():
    r = row(retention_years=20)
    d = dl.deadline_for(r, {r["asset_id"]: r}, "expected", now=NOW)
    assert d["status"] == "late" and d["harvest_risk"]
    assert "overdue" in dl.sentence(d, r)


def test_short_lived_certificate_is_capped_by_nist_2035():
    r = row(asset_id="CERT-x", algorithm="ECDSA-P256", usage="signature", service_type="tls_certificate",
            retention_years=0.3, clients_support_pqc=False)
    d = dl.deadline_for(r, {"CERT-x": r}, "expected", now=NOW)
    assert d["finish_by"] == 2035 and d["driver"] == "nist" and d["status"] == "planned"
    assert not d["harvest_risk"]


def test_inherited_exposure_points_at_the_weak_key():
    key = row(asset_id="KMS-1", algorithm="RSA-2048", usage="key_wrapping", service_type="kms_key", dependents=3)
    db = row(asset_id="DB-1", algorithm="AES-256", usage="data_encryption", service_type="database",
             inherited_from="KMS-1", inherited_exposure=1.0, retention_years=7)
    d = dl.deadline_for(db, {"KMS-1": key, "DB-1": db}, "expected", now=NOW)
    assert d["fix_asset"] == "KMS-1"
    assert "KMS-1" in dl.sentence(d, db)
    assert "protected by KMS-1" in xai.why({**db, "components": {**db["components"], "crypto_exposure": 0.1}})


def test_safe_and_legacy_assets():
    safe = row(algorithm="AES-256", quantum_exposed=False)
    assert dl.deadline_for(safe, {safe["asset_id"]: safe}, now=NOW)["status"] == "safe"
    weak = row(algorithm="3DES", quantum_exposed=False)
    assert dl.deadline_for(weak, {weak["asset_id"]: weak}, now=NOW)["status"] == "classical"


def test_earlier_quantum_computer_means_more_late_assets():
    rs = {f"A{i}": row(asset_id=f"A{i}", retention_years=y) for i, y in enumerate([1, 3, 5, 8, 10, 15])}
    late = {s: sum(dl.deadline_for(r, rs, s, now=NOW)["status"] == "late" for r in rs.values()) for s in dl.SCENARIOS}
    assert late["cautious"] >= late["expected"] >= late["late"]
    assert late["cautious"] > late["late"]


def test_why_sentence_names_the_biggest_factors():
    text = xai.why(row(dependents=5, components={**row()["components"], "dependency_impact": 0.9}))
    assert text.startswith("High risk because it uses X25519")
    low = xai.why(row(algorithm="AES-256", ai_class="Low", exposure="internal",
                      components={"crypto_exposure": 0.1, "data_sensitivity": 0.4, "retention": 0.1,
                                  "external_exposure": 0.2, "dependency_impact": 0.0, "business_criticality": 0.4}))
    assert low.startswith("Low risk because") and "quantum-safe" in low


def test_ai_note_explains_a_disagreement():
    attr = [{"feature": "inherited_exposure", "label": "Exposure inherited from its key / certificate", "impact": 0.4},
            {"feature": "retention", "label": "Data retention period", "impact": 0.1}]
    note = xai.ai_note(row(ai_class="Critical", rule_class="Medium"), attr)
    assert "higher than the formula" in note and "inherited" in note
    assert xai.ai_factors(attr) == ["crypto_exposure", "retention"]
    assert xai.agreement(["crypto_exposure", "retention"], ["retention"]) == pytest.approx(0.5)


def test_faithfulness_beats_random_on_a_simple_model():
    from sklearn.linear_model import LogisticRegression

    from qmigrate.engine import models
    n = len(models.ASSET_FEATURES) + len(models.GRAPH_FEATURES)
    rng = np.random.default_rng(0)
    x = rng.random((200, n))
    y = (x[:, 0] + x[:, 2] > 1).astype(int) + (x[:, 0] > 0.8).astype(int)
    model = LogisticRegression(max_iter=500).fit(x, y)
    f = xai.faithfulness(model, x[:40], x.mean(axis=0), k=3)
    assert f["explained_drop"] > f["random_drop"]
