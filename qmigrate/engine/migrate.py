"""Migration recommendations and (simulated) validation checks.

What "migration" means here: the asset keeps running where it is; only its
cryptographic policy changes, e.g. TLS key exchange RSA-2048 ->
X25519+ML-KEM-768 (hybrid). The checks below are simulated policy checks,
not a live TLS handshake; a real liboqs/OpenSSL handshake is Phase 2.
"""
from __future__ import annotations

from qmigrate.engine.catalog import ALGORITHMS, PQC_FACTS, TARGETS_BY_USAGE

TLS_RECORD_LIMIT = 16384  # bytes in one TLS record


def recommend(asset: dict) -> dict | None:
    """Return the target algorithm for an asset, or None if no change is needed."""
    alg = ALGORITHMS[asset["algorithm"]]
    if alg["status"] in ("pqc", "hybrid", "compatible"):
        return None
    usage, service = asset["usage"], asset["service_type"]
    if usage in ("key_exchange", "key_wrapping"):
        target = "X25519+ML-KEM-768"
        reason = ("Hybrid key establishment: keeps classical X25519 and adds ML-KEM-768 (FIPS 203), "
                  "so the session stays secure even if one of the two is broken.")
    elif usage == "signature" and service == "code_signing":
        target = "SLH-DSA-SHA2-128s"
        reason = ("Long-lived code signatures: SLH-DSA (FIPS 205) is hash-based and very conservative; "
                  "its large signatures matter little for software releases.")
    elif usage == "signature":
        target = "ECDSA-P256+ML-DSA-65"
        reason = ("Hybrid signatures: ECDSA plus ML-DSA-65 (FIPS 204) keep existing verifiers working "
                  "while adding quantum resistance.")
    elif usage == "data_encryption":
        target = "AES-256-GCM"
        reason = ("Symmetric encryption only needs a longer key: AES-256 keeps a large security margin "
                  "against Grover's algorithm.")
    else:
        target = "SHA-384"
        reason = "SHA-1 is already broken classically; SHA-384 gives a wide margin against quantum search."
    return {"target": target, "standard": ALGORITHMS[target].get("standard", ""), "reason": reason}


def allowed_targets(asset: dict) -> list[str]:
    """Target algorithms that fit the asset's usage; the recommended one first."""
    options = list(TARGETS_BY_USAGE[asset["usage"]])
    rec = recommend(asset)
    if rec and rec["target"] in options:
        options.remove(rec["target"])
        options.insert(0, rec["target"])
    return options


def validation_checks(asset: dict, target: str, dependents: list[dict]) -> list[dict]:
    """Simulated pre-rollout checks shown in the PQC lab."""
    info = ALGORITHMS[target]
    facts = PQC_FACTS.get(target)
    hybrid = info["status"] == "hybrid"
    fits = target in TARGETS_BY_USAGE[asset["usage"]]
    checks = [{
        "check": "Fits the asset's usage",
        "result": "PASS" if fits else "FAIL",
        "detail": f"{target} is suitable for {asset['usage'].replace('_', ' ')}" if fits
        else f"{target} cannot be used for {asset['usage'].replace('_', ' ')}",
    }, {
        "check": "NIST-standardised algorithm",
        "result": "PASS" if info.get("standard") else "FAIL",
        "detail": info.get("standard") or "not on the approved list",
    }]
    if facts:
        checks.append({"check": "Security level", "result": "PASS",
                       "detail": f"NIST category {facts['nist_category']}"})
    else:
        checks.append({"check": "Security level", "result": "PASS",
                       "detail": f"{info['key_bits']}-bit symmetric / hash strength"})

    legacy = [d["asset_id"] for d in dependents if not d["clients_support_pqc"]]
    if not asset["clients_support_pqc"]:
        legacy.append(asset["asset_id"])
    if facts is None:
        checks.append({"check": "Client compatibility", "result": "PASS",
                       "detail": "Symmetric change, invisible to clients"})
    elif hybrid:
        checks.append({"check": "Client compatibility", "result": "PASS",
                       "detail": f"{len(legacy)} legacy client group(s) fall back to the classical half of the hybrid"})
    else:
        checks.append({"check": "Client compatibility", "result": "WARN" if legacy else "PASS",
                       "detail": f"{len(legacy)} legacy client group(s) must be upgraded first" if legacy
                       else "All clients support post-quantum algorithms"})

    if facts and facts["kind"] == "kem":
        extra = facts["public_key_bytes"] + facts["ciphertext_bytes"]
        checks.append({"check": "Handshake size", "result": "PASS" if extra < TLS_RECORD_LIMIT else "WARN",
                       "detail": f"+{extra:,} bytes per handshake (key share + ciphertext)"})
    elif facts:
        sig = facts["signature_bytes"]
        checks.append({"check": "Signature size", "result": "PASS" if sig < 5000 else "WARN",
                       "detail": f"{sig:,} bytes per signature" + (" - larger certificate chains" if sig >= 5000 else "")})

    checks.append({"check": "Crypto-agility rollback", "result": "PASS",
                   "detail": f"Previous policy {asset['algorithm']} stored; one call rolls back"})
    for c in checks:
        c["simulated"] = True
    return checks
