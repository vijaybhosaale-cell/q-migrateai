"""Cryptographic algorithm catalogue shared by the simulator and the AI engine.

`exposure` (0-1) is how exposed an algorithm is to a cryptographically
relevant quantum computer (Shor's algorithm breaks RSA / ECC / DH) or to
known classical weakness (3DES, SHA-1). Symmetric AES-256 and SHA-2 hashes
are treated as quantum-safe; Grover's algorithm only halves their strength.

Post-quantum algorithms are the NIST standards published in August 2024:
FIPS 203 (ML-KEM), FIPS 204 (ML-DSA) and FIPS 205 (SLH-DSA).
"""
from __future__ import annotations

ALGORITHMS: dict[str, dict] = {
    # Quantum-vulnerable public-key cryptography
    "RSA-2048": {"family": "public-key", "quantum_vulnerable": True, "exposure": 1.00, "status": "vulnerable", "key_bits": 2048},
    "RSA-3072": {"family": "public-key", "quantum_vulnerable": True, "exposure": 0.92, "status": "vulnerable", "key_bits": 3072},
    "RSA-4096": {"family": "public-key", "quantum_vulnerable": True, "exposure": 0.88, "status": "vulnerable", "key_bits": 4096},
    "DH-2048": {"family": "public-key", "quantum_vulnerable": True, "exposure": 1.00, "status": "vulnerable", "key_bits": 2048},
    "ECDHE-P256": {"family": "public-key", "quantum_vulnerable": True, "exposure": 0.95, "status": "vulnerable", "key_bits": 256},
    "ECDSA-P256": {"family": "public-key", "quantum_vulnerable": True, "exposure": 0.95, "status": "vulnerable", "key_bits": 256},
    "ECDSA-P384": {"family": "public-key", "quantum_vulnerable": True, "exposure": 0.90, "status": "vulnerable", "key_bits": 384},
    "X25519": {"family": "public-key", "quantum_vulnerable": True, "exposure": 0.93, "status": "vulnerable", "key_bits": 255},
    "Ed25519": {"family": "public-key", "quantum_vulnerable": True, "exposure": 0.93, "status": "vulnerable", "key_bits": 255},
    # Classically weak / legacy
    "3DES": {"family": "symmetric", "quantum_vulnerable": False, "exposure": 0.80, "status": "legacy-weak", "key_bits": 168},
    "SHA-1": {"family": "hash", "quantum_vulnerable": False, "exposure": 0.70, "status": "legacy-weak", "key_bits": 160},
    "AES-128": {"family": "symmetric", "quantum_vulnerable": False, "exposure": 0.35, "status": "review", "key_bits": 128},
    # Quantum-safe today
    "AES-256": {"family": "symmetric", "quantum_vulnerable": False, "exposure": 0.10, "status": "compatible", "key_bits": 256, "standard": "FIPS 197"},
    "AES-256-GCM": {"family": "symmetric", "quantum_vulnerable": False, "exposure": 0.10, "status": "compatible", "key_bits": 256, "standard": "FIPS 197 + SP 800-38D"},
    "SHA-256": {"family": "hash", "quantum_vulnerable": False, "exposure": 0.12, "status": "compatible", "key_bits": 256, "standard": "FIPS 180-4"},
    "SHA-384": {"family": "hash", "quantum_vulnerable": False, "exposure": 0.08, "status": "compatible", "key_bits": 384, "standard": "FIPS 180-4"},
    # Post-quantum and hybrid (NIST FIPS 203 / 204 / 205)
    "ML-KEM-768": {"family": "pqc-kem", "quantum_vulnerable": False, "exposure": 0.05, "status": "pqc", "key_bits": 768, "standard": "FIPS 203"},
    "ML-KEM-1024": {"family": "pqc-kem", "quantum_vulnerable": False, "exposure": 0.04, "status": "pqc", "key_bits": 1024, "standard": "FIPS 203"},
    "X25519+ML-KEM-768": {"family": "hybrid-kem", "quantum_vulnerable": False, "exposure": 0.08, "status": "hybrid", "key_bits": 768, "standard": "FIPS 203 (hybrid with X25519)"},
    "ML-DSA-65": {"family": "pqc-signature", "quantum_vulnerable": False, "exposure": 0.05, "status": "pqc", "key_bits": 0, "standard": "FIPS 204"},
    "ML-DSA-87": {"family": "pqc-signature", "quantum_vulnerable": False, "exposure": 0.04, "status": "pqc", "key_bits": 0, "standard": "FIPS 204"},
    "ECDSA-P256+ML-DSA-65": {"family": "hybrid-signature", "quantum_vulnerable": False, "exposure": 0.08, "status": "hybrid", "key_bits": 0, "standard": "FIPS 204 (hybrid with ECDSA)"},
    "SLH-DSA-SHA2-128s": {"family": "pqc-signature", "quantum_vulnerable": False, "exposure": 0.04, "status": "pqc", "key_bits": 0, "standard": "FIPS 205"},
}

SAFE_STATUSES = {"compatible", "pqc", "hybrid"}

# Published parameter sizes in bytes (FIPS 203 / 204 / 205), used by the PQC lab.
PQC_FACTS: dict[str, dict] = {
    "ML-KEM-768": {"standard": "FIPS 203", "nist_category": 3, "public_key_bytes": 1184, "ciphertext_bytes": 1088, "kind": "kem"},
    "X25519+ML-KEM-768": {"standard": "FIPS 203 + X25519", "nist_category": 3, "public_key_bytes": 1184 + 32, "ciphertext_bytes": 1088 + 32, "kind": "kem"},
    "ML-KEM-1024": {"standard": "FIPS 203", "nist_category": 5, "public_key_bytes": 1568, "ciphertext_bytes": 1568, "kind": "kem"},
    "ML-DSA-65": {"standard": "FIPS 204", "nist_category": 3, "public_key_bytes": 1952, "signature_bytes": 3309, "kind": "signature"},
    "ML-DSA-87": {"standard": "FIPS 204", "nist_category": 5, "public_key_bytes": 2592, "signature_bytes": 4627, "kind": "signature"},
    "ECDSA-P256+ML-DSA-65": {"standard": "FIPS 204 + ECDSA P-256", "nist_category": 3, "public_key_bytes": 1952 + 65, "signature_bytes": 3309 + 72, "kind": "signature"},
    "SLH-DSA-SHA2-128s": {"standard": "FIPS 205", "nist_category": 1, "public_key_bytes": 32, "signature_bytes": 7856, "kind": "signature"},
}

# Classical sizes for side-by-side comparison in the PQC lab.
CLASSICAL_FACTS: dict[str, dict] = {
    "RSA-2048": {"public_key_bytes": 256, "ciphertext_bytes": 256, "signature_bytes": 256},
    "RSA-3072": {"public_key_bytes": 384, "ciphertext_bytes": 384, "signature_bytes": 384},
    "RSA-4096": {"public_key_bytes": 512, "ciphertext_bytes": 512, "signature_bytes": 512},
    "DH-2048": {"public_key_bytes": 256, "ciphertext_bytes": 256},
    "ECDHE-P256": {"public_key_bytes": 65, "ciphertext_bytes": 65},
    "ECDSA-P256": {"public_key_bytes": 65, "signature_bytes": 72},
    "ECDSA-P384": {"public_key_bytes": 97, "signature_bytes": 104},
    "X25519": {"public_key_bytes": 32, "ciphertext_bytes": 32},
    "Ed25519": {"public_key_bytes": 32, "signature_bytes": 64},
}

USAGES = ["key_exchange", "key_wrapping", "signature", "data_encryption", "hashing"]
USAGE_TEXT = {
    "key_exchange": "key exchange",
    "key_wrapping": "key wrapping",
    "signature": "digital signatures",
    "data_encryption": "data encryption",
    "hashing": "hashing",
}

SERVICE_LABELS = {
    "load_balancer": "Load balancer (TLS)",
    "api_gateway": "API gateway",
    "payment_service": "Payment service",
    "mobile_backend": "Mobile backend",
    "message_queue": "Message queue",
    "database": "Database",
    "object_storage": "Object storage",
    "backup_vault": "Backup vault",
    "kms_key": "KMS key",
    "certificate_authority": "Certificate authority",
    "iam_sso": "IAM / SSO",
    "code_signing": "Code signing",
    "container_registry": "Container registry",
    "vpn_gateway": "VPN gateway",
    "logging_pipeline": "Logging pipeline",
    "tls_certificate": "TLS certificate",
}

# Relative migration effort (0-100) by service type, used by the planner.
MIGRATION_EFFORT = {
    "load_balancer": 25, "api_gateway": 30, "payment_service": 75, "mobile_backend": 45,
    "message_queue": 35, "database": 70, "object_storage": 35, "backup_vault": 45,
    "kms_key": 40, "certificate_authority": 80, "iam_sso": 50, "code_signing": 60,
    "container_registry": 30, "vpn_gateway": 55, "logging_pipeline": 20, "tls_certificate": 20,
}


def algorithm(name: str) -> dict:
    return ALGORITHMS[name]


def is_quantum_vulnerable(name: str) -> bool:
    return bool(ALGORITHMS[name]["quantum_vulnerable"])


# Target algorithms the PQC lab offers for each usage; the first is the recommended default.
TARGETS_BY_USAGE: dict[str, list[str]] = {
    "key_exchange": ["X25519+ML-KEM-768", "ML-KEM-768", "ML-KEM-1024"],
    "key_wrapping": ["X25519+ML-KEM-768", "ML-KEM-768", "ML-KEM-1024"],
    "signature": ["ECDSA-P256+ML-DSA-65", "ML-DSA-65", "ML-DSA-87", "SLH-DSA-SHA2-128s"],
    "data_encryption": ["AES-256-GCM", "AES-256"],
    "hashing": ["SHA-384", "SHA-256"],
}
