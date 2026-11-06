"""Helpers shared by the AWS, Azure and Google Cloud connectors.

Each connector reads cloud metadata (read-only) and calls `Inventory.add()` / `Inventory.link()`;
`Inventory.result()` returns the platform's standard {"assets", "edges"} dict.

What the cloud APIs cannot tell us (how sensitive the data is, how long it must be kept, how critical
the system is) comes from resource tags when present, otherwise from the defaults below:

    tag keys (case-insensitive): DataClassification / Sensitivity  (1-5, or public|internal|confidential|restricted)
                                 RetentionYears / Retention          (number of years)
                                 BusinessCriticality / Criticality   (1-5)
"""
from __future__ import annotations

import re

from qmigrate.engine.catalog import ALGORITHMS, SERVICE_LABELS

# service_type: (usage, protocol, sensitivity, retention years, criticality, clients_support_pqc)
DEFAULTS = {
    "kms_key": ("key_wrapping", "KMS key wrap", 5, 10, 5, True),
    "tls_certificate": ("signature", "X.509 (TLS)", 4, 1, 4, False),
    "load_balancer": ("key_exchange", "TLS 1.2/1.3", 3, 1, 4, True),
    "database": ("data_encryption", "Encryption at rest", 4, 7, 4, True),
    "object_storage": ("data_encryption", "Server-side encryption", 3, 5, 3, True),
    "api_gateway": ("key_exchange", "TLS 1.2/1.3", 3, 1, 4, True),
}
LEVELS = {"public": 1, "internal": 2, "confidential": 4, "restricted": 5, "secret": 5, "low": 2, "medium": 3, "high": 4}


def _norm(tags: dict | None) -> dict:
    return {re.sub(r"[^a-z]", "", str(k).lower()): str(v) for k, v in (tags or {}).items()}


def _level(value: str | None) -> int | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v.isdigit():
        return max(1, min(int(v), 5))
    return LEVELS.get(v)


def _years(value: str | None) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", value or "")
    return float(m.group(1)) if m else None


def short(text: str, n: int = 40) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-")[:n] or "unknown"


class Inventory:
    def __init__(self, cloud: str):
        self.cloud = cloud
        self.assets: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.aliases: dict[str, str] = {}          # provider resource id/ARN -> asset_id
        self.skipped: list[str] = []

    def add(self, asset_id: str, service_type: str, algorithm: str, *, region: str, application: str,
            owner: str = "", exposure: str = "internal", tags: dict | None = None, aliases=(), usage: str | None = None,
            protocol: str | None = None, retention_years: float | None = None) -> str:
        if algorithm not in ALGORITHMS or service_type not in SERVICE_LABELS:
            self.skipped.append(f"{asset_id}: {algorithm}")
            return ""
        d_usage, d_proto, d_sens, d_ret, d_crit, d_pqc = DEFAULTS.get(service_type, DEFAULTS["database"])
        t = _norm(tags)
        sens = _level(t.get("dataclassification") or t.get("sensitivity") or t.get("classification")) or d_sens
        ret = _years(t.get("retentionyears") or t.get("retention") or t.get("retentionperiod"))
        crit = _level(t.get("businesscriticality") or t.get("criticality"))
        self.assets[asset_id] = {
            "asset_id": asset_id, "cloud": self.cloud, "region": region or "global", "application": application[:60],
            "owner_team": (t.get("owner") or t.get("team") or owner or "unknown")[:60], "service_type": service_type,
            "usage": usage or d_usage, "protocol": protocol or d_proto, "algorithm": algorithm, "exposure": exposure,
            "data_sensitivity": sens, "retention_years": ret if ret is not None else (retention_years if retention_years is not None else d_ret),
            "business_criticality": crit or d_crit, "clients_support_pqc": d_pqc,
        }
        for a in (asset_id, *aliases):
            if a:
                self.aliases[str(a)] = asset_id
        return asset_id

    def resolve(self, ref: str | None) -> str | None:
        if not ref:
            return None
        if ref in self.aliases:
            return self.aliases[ref]
        for key, aid in self.aliases.items():          # e.g. a KMS key referenced by its ARN or its bare id
            if key and len(key) >= 8 and len(ref) >= 8 and (ref.endswith(key) or key.endswith(ref)):
                return aid
        return None

    def link(self, source: str | None, target_ref: str | None, relation: str) -> None:
        target = self.resolve(target_ref) if target_ref not in self.assets else target_ref
        if source and target and source in self.assets and target in self.assets and source != target:
            self.edges.append({"source": source, "target": target, "relation": relation})

    def result(self) -> dict:
        from qmigrate.realdata.collector import label_assets
        edges = [dict(t) for t in {tuple(sorted(e.items())) for e in self.edges}]
        label_assets(self.assets, edges)
        return {"assets": sorted(self.assets.values(), key=lambda a: a["asset_id"]),
                "edges": sorted(edges, key=lambda e: (e["source"], e["target"])),
                "meta": {"skipped": self.skipped}}


def cert_algorithm_from_pem(pem: str) -> tuple[str | None, float | None]:
    """Key algorithm and years left of a PEM certificate (public data only)."""
    import datetime as dt

    from cryptography import x509

    from qmigrate.realdata.collector import _not_after, key_algorithm
    try:
        c = x509.load_pem_x509_certificate(pem.encode() if isinstance(pem, str) else pem)
    except ValueError:
        return None, None
    years = max((_not_after(c) - dt.datetime.now(dt.timezone.utc)).days / 365.25, 0.0)
    return key_algorithm(c), round(years, 1)


def missing_package(name: str, pip_name: str) -> RuntimeError:
    return RuntimeError(f"The {name} connector needs the Python package '{pip_name}'. "
                        f"Run: .venv\\Scripts\\python -m pip install {pip_name}   (or reinstall requirements.txt)")
