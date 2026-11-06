"""Synthetic multi-cloud crypto inventory generator (Laptop 1).

Builds a reproducible estate of applications spread across AWS, Azure and
GCP: load balancers, API gateways, backends, databases, KMS keys,
certificate authorities and so on, plus the dependencies between them.

Every asset also gets an `analyst_label` (Low / Medium / High / Critical).
This simulates a security team's historical risk assessments, which the AI
engine learns from. The hidden rule behind those labels includes two effects
a simple per-asset formula does not see:

* inherited exposure: an asset encrypted with AES-256 is still at risk if
  the KMS key or certificate protecting it uses RSA/ECC;
* harvest-now-decrypt-later (HNDL): sensitive data kept for many years is
  worth stealing today and decrypting once quantum computers exist.

All data is synthetic. No real organisation, system or person is modelled.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

import networkx as nx

from qmigrate.engine.catalog import ALGORITHMS

CLASSES = ["Low", "Medium", "High", "Critical"]

CLOUDS = {
    "AWS": ["us-east-1", "eu-west-3", "ap-south-1"],
    "Azure": ["westeurope", "centralindia", "eastus"],
    "GCP": ["europe-west1", "asia-south1", "us-central1"],
}
CLOUD_WEIGHTS = {"AWS": 0.40, "Azure": 0.35, "GCP": 0.25}

SHORT = {
    "load_balancer": "LB", "api_gateway": "APIGW", "payment_service": "PAY",
    "mobile_backend": "MOB", "message_queue": "MQ", "database": "DB",
    "object_storage": "OBJ", "backup_vault": "BKP", "kms_key": "KMS",
    "certificate_authority": "CA", "iam_sso": "IAM", "code_signing": "SIGN",
    "container_registry": "REG", "vpn_gateway": "VPN", "logging_pipeline": "LOG",
}

# usage, algorithm mix, exposure mix, sensitivity range, retention range (years),
# criticality range, share of clients that already support PQC, protocol.
SERVICE_TYPES = {
    "load_balancer": dict(usage="key_exchange", protocol="TLS 1.2/1.3",
        algs={"RSA-2048": .45, "ECDHE-P256": .30, "X25519": .15, "X25519+ML-KEM-768": .10},
        exposure={"internet": .9, "partner": .1}, sens=(2, 4), ret=(0, 3), crit=(3, 5), pqc_clients=.7),
    "api_gateway": dict(usage="key_exchange", protocol="TLS 1.2/1.3",
        algs={"RSA-2048": .45, "ECDHE-P256": .30, "X25519": .15, "X25519+ML-KEM-768": .10},
        exposure={"internet": .75, "partner": .20, "internal": .05}, sens=(3, 5), ret=(1, 7), crit=(4, 5), pqc_clients=.65),
    "payment_service": dict(usage="key_exchange", protocol="mTLS",
        algs={"RSA-2048": .50, "ECDHE-P256": .35, "X25519+ML-KEM-768": .15},
        exposure={"partner": .6, "internet": .3, "internal": .1}, sens=(5, 5), ret=(7, 15), crit=(5, 5), pqc_clients=.4),
    "mobile_backend": dict(usage="key_exchange", protocol="TLS 1.3",
        algs={"RSA-2048": .35, "ECDHE-P256": .40, "X25519": .25},
        exposure={"internet": 1.0}, sens=(3, 4), ret=(1, 5), crit=(3, 4), pqc_clients=.5),
    "message_queue": dict(usage="key_exchange", protocol="TLS 1.2",
        algs={"RSA-2048": .40, "ECDHE-P256": .40, "X25519": .20},
        exposure={"internal": 1.0}, sens=(2, 4), ret=(0, 2), crit=(3, 4), pqc_clients=.8),
    "database": dict(usage="data_encryption", protocol="Envelope encryption",
        algs={"AES-256": .60, "AES-128": .28, "3DES": .12},
        exposure={"internal": .9, "partner": .1}, sens=(3, 5), ret=(5, 20), crit=(4, 5), pqc_clients=.9),
    "object_storage": dict(usage="data_encryption", protocol="Server-side encryption",
        algs={"AES-256": .72, "AES-128": .28},
        exposure={"internal": .7, "internet": .3}, sens=(1, 5), ret=(3, 25), crit=(2, 4), pqc_clients=.9),
    "backup_vault": dict(usage="data_encryption", protocol="Envelope encryption",
        algs={"AES-256": .60, "AES-128": .25, "3DES": .15},
        exposure={"internal": 1.0}, sens=(4, 5), ret=(10, 25), crit=(3, 4), pqc_clients=.9),
    "kms_key": dict(usage="key_wrapping", protocol="KMS key wrap",
        algs={"RSA-2048": .40, "RSA-4096": .15, "ECDHE-P256": .10, "AES-256": .35},
        exposure={"internal": 1.0}, sens=(5, 5), ret=(10, 25), crit=(5, 5), pqc_clients=.6),
    "certificate_authority": dict(usage="signature", protocol="X.509 PKI",
        algs={"RSA-2048": .40, "RSA-4096": .30, "ECDSA-P256": .30},
        exposure={"internal": 1.0}, sens=(4, 5), ret=(10, 20), crit=(5, 5), pqc_clients=.5),
    "iam_sso": dict(usage="signature", protocol="SAML / JWT",
        algs={"RSA-2048": .60, "ECDSA-P256": .30, "Ed25519": .10},
        exposure={"internet": .7, "internal": .3}, sens=(4, 5), ret=(1, 5), crit=(5, 5), pqc_clients=.5),
    "code_signing": dict(usage="signature", protocol="Code signature",
        algs={"RSA-3072": .50, "ECDSA-P256": .30, "Ed25519": .20},
        exposure={"internal": 1.0}, sens=(3, 4), ret=(10, 25), crit=(4, 5), pqc_clients=.6),
    "container_registry": dict(usage="signature", protocol="Image signature",
        algs={"RSA-2048": .30, "ECDSA-P256": .50, "Ed25519": .20},
        exposure={"internal": .8, "internet": .2}, sens=(2, 3), ret=(1, 5), crit=(3, 4), pqc_clients=.7),
    "vpn_gateway": dict(usage="key_exchange", protocol="IPsec IKEv2",
        algs={"DH-2048": .30, "RSA-2048": .30, "ECDHE-P256": .30, "X25519+ML-KEM-768": .10},
        exposure={"partner": .6, "internet": .4}, sens=(3, 5), ret=(0, 3), crit=(4, 5), pqc_clients=.4),
    "logging_pipeline": dict(usage="hashing", protocol="Log integrity",
        algs={"SHA-1": .30, "SHA-256": .70},
        exposure={"internal": 1.0}, sens=(2, 3), ret=(1, 7), crit=(2, 3), pqc_clients=.9),
}

SHARED_PER_CLOUD = {
    "kms_key": 4, "certificate_authority": 2, "iam_sso": 1, "code_signing": 1,
    "container_registry": 1, "vpn_gateway": 2, "logging_pipeline": 1,
}

APPLICATIONS = [
    "Payments", "Customer Portal", "Mobile Banking", "Billing", "CRM", "HR",
    "Analytics", "Supply Chain", "Partner API", "Telemetry", "Loyalty", "Claims",
    "Trading", "Notifications", "Identity Hub", "Data Lake",
]
TEAMS = ["Platform", "Payments", "Digital", "Data", "Security", "Enterprise IT"]

PROTECTIVE = {"uses_key", "trusts_cert", "validates_token", "verifies_signature"}
EXTERNAL = {"internet": 1.0, "partner": 0.6, "internal": 0.2}


def _pick(rng: random.Random, weights: dict) -> str:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


PROFILES = {
    "generic": {
        "label": "Generic enterprise",
        "applications": APPLICATIONS,
        "cloud_weights": CLOUD_WEIGHTS,
        "teams": TEAMS,
        "overrides": {},
    },
    "bank": {
        "label": "Retail bank",
        "applications": [
            "Payments", "Online Banking", "Mobile Banking", "Cards", "Trading", "Loans", "KYC",
            "Fraud Analytics", "Treasury", "Partner API", "Customer Portal", "Statements",
            "ATM Network", "Notifications", "Data Lake", "Identity Hub",
        ],
        "cloud_weights": {"AWS": 0.50, "Azure": 0.35, "GCP": 0.15},
        "teams": ["Payments", "Digital Channels", "Core Banking", "Data", "Security", "Infrastructure"],
        "overrides": {"payment_service": {"sens": (5, 5), "ret": (10, 20)}},
    },
    "hospital": {
        "label": "Hospital group",
        "applications": [
            "Patient Portal", "Health Records", "Lab Results", "Imaging Archive", "Pharmacy", "Billing",
            "Appointments", "Telemedicine", "Research Data", "Staff Identity", "Insurance Claims",
            "Device Gateway", "Notifications", "Analytics", "Partner API", "Records Archive",
        ],
        "cloud_weights": {"AWS": 0.30, "Azure": 0.50, "GCP": 0.20},
        "teams": ["Clinical IT", "Digital Health", "Data", "Security", "Infrastructure", "Finance IT"],
        "overrides": {
            "database": {"sens": (4, 5), "ret": (15, 30)},
            "backup_vault": {"ret": (20, 30)},
            "object_storage": {"sens": (3, 5), "ret": (10, 30)},
        },
    },
}


def _profile_services(profile: str) -> dict:
    services = {k: dict(v) for k, v in SERVICE_TYPES.items()}
    for service_type, changes in PROFILES[profile]["overrides"].items():
        services[service_type].update(changes)
    return services


class _Builder:
    def __init__(self, seed: int, profile: str = "generic"):
        self.rng = random.Random(seed)
        self.services = _profile_services(profile)
        self.cloud_weights = PROFILES[profile]["cloud_weights"]
        self.teams = PROFILES[profile]["teams"]
        self.assets: list[dict] = []
        self.edges: list[dict] = []
        self.counters: dict[tuple, int] = defaultdict(int)
        self.shared: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    def add_asset(self, service_type: str, cloud: str, application: str, team: str) -> str:
        spec = self.services[service_type]
        rng = self.rng
        self.counters[(cloud, service_type)] += 1
        asset_id = f"{cloud.upper()}-{SHORT[service_type]}-{self.counters[(cloud, service_type)]:03d}"
        algorithm = _pick(rng, spec["algs"])
        self.assets.append({
            "asset_id": asset_id,
            "cloud": cloud,
            "region": rng.choice(CLOUDS[cloud]),
            "application": application,
            "owner_team": team,
            "service_type": service_type,
            "usage": spec["usage"],
            "protocol": spec["protocol"],
            "algorithm": algorithm,
            "key_bits": ALGORITHMS[algorithm]["key_bits"],
            "exposure": _pick(rng, spec["exposure"]),
            "data_sensitivity": rng.randint(*spec["sens"]),
            "retention_years": rng.randint(*spec["ret"]),
            "business_criticality": rng.randint(*spec["crit"]),
            "clients_support_pqc": rng.random() < spec["pqc_clients"],
        })
        return asset_id

    def add_edge(self, source: str, target: str, relation: str) -> None:
        if source != target:
            self.edges.append({"source": source, "target": target, "relation": relation})

    def shared_asset(self, cloud: str, service_type: str, cross_cloud: float = 0.0) -> str:
        if cross_cloud and self.rng.random() < cross_cloud:
            cloud = self.rng.choice([c for c in CLOUDS if c != cloud])
        return self.rng.choice(self.shared[cloud][service_type])


def _build_shared(b: _Builder) -> None:
    for cloud in CLOUDS:
        for service_type, count in SHARED_PER_CLOUD.items():
            for _ in range(count):
                aid = b.add_asset(service_type, cloud, "Shared Platform", "Platform")
                b.shared[cloud][service_type].append(aid)
    for cloud in CLOUDS:
        s = b.shared[cloud]
        for ca in s["certificate_authority"]:
            b.add_edge(ca, b.rng.choice(s["kms_key"]), "uses_key")
        for iam in s["iam_sso"]:
            b.add_edge(iam, b.rng.choice(s["kms_key"]), "uses_key")
            b.add_edge(iam, b.rng.choice(s["certificate_authority"]), "trusts_cert")
        for sign in s["code_signing"]:
            b.add_edge(sign, b.rng.choice(s["kms_key"]), "uses_key")
        for reg in s["container_registry"]:
            b.add_edge(reg, b.rng.choice(s["code_signing"]), "verifies_signature")
        for vpn in s["vpn_gateway"]:
            b.add_edge(vpn, b.rng.choice(s["certificate_authority"]), "trusts_cert")
        for log in s["logging_pipeline"]:
            b.add_edge(log, b.rng.choice(s["kms_key"]), "uses_key")


def _build_application(b: _Builder, name: str) -> None:
    rng = b.rng
    cloud = _pick(rng, b.cloud_weights)
    team = rng.choice(b.teams)
    lb = b.add_asset("load_balancer", cloud, name, team)
    gw = b.add_asset("api_gateway", cloud, name, team)
    b.add_edge(lb, gw, "routes_to")
    b.add_edge(lb, b.shared_asset(cloud, "certificate_authority", 0.1), "trusts_cert")
    b.add_edge(gw, b.shared_asset(cloud, "certificate_authority", 0.1), "trusts_cert")
    b.add_edge(gw, b.shared_asset(cloud, "iam_sso", 0.2), "validates_token")

    backend_types = rng.sample(["payment_service", "mobile_backend", "message_queue"], k=rng.randint(1, 3))
    backends = [b.add_asset(t, cloud, name, team) for t in backend_types]
    for bk in backends:
        b.add_edge(gw, bk, "calls")
        b.add_edge(bk, b.shared_asset(cloud, "container_registry"), "pulls_image")
        b.add_edge(bk, b.shared_asset(cloud, "logging_pipeline"), "sends_logs")

    queue = next((bk for bk, t in zip(backends, backend_types) if t == "message_queue"), None)
    if queue:
        for bk, t in zip(backends, backend_types):
            if t != "message_queue":
                b.add_edge(bk, queue, "publishes_to")
    for bk, t in zip(backends, backend_types):
        if t == "payment_service" and rng.random() < 0.7:
            b.add_edge(b.shared_asset(cloud, "vpn_gateway"), bk, "tunnels_to")

    kms = b.shared_asset(cloud, "kms_key", 0.2)
    db = None
    if rng.random() < 0.85:
        db = b.add_asset("database", cloud, name, team)
        b.add_edge(db, kms, "uses_key")
        for bk in backends:
            b.add_edge(bk, db, "calls")
    if rng.random() < 0.60:
        obj = b.add_asset("object_storage", cloud, name, team)
        b.add_edge(obj, kms, "uses_key")
        b.add_edge(backends[0], obj, "calls")
    if db and rng.random() < 0.50:
        bkp = b.add_asset("backup_vault", cloud, name, team)
        b.add_edge(bkp, b.shared_asset(cloud, "kms_key", 0.2), "uses_key")
        b.add_edge(bkp, db, "backs_up")


def _analyst_labels(assets: list[dict], edges: list[dict], rng: random.Random) -> None:
    graph = nx.DiGraph()
    graph.add_nodes_from(a["asset_id"] for a in assets)
    for e in edges:
        graph.add_edge(e["source"], e["target"], relation=e["relation"])
    by_id = {a["asset_id"]: a for a in assets}
    dependents = {n: len(nx.ancestors(graph, n)) for n in graph.nodes}
    max_dep = max(dependents.values()) or 1

    scores = []
    for a in assets:
        alg = ALGORITHMS[a["algorithm"]]
        own = alg["exposure"]
        protective = [t for t in graph.successors(a["asset_id"])
                      if graph.edges[a["asset_id"], t]["relation"] in PROTECTIVE]
        inherited = max((ALGORITHMS[by_id[t]["algorithm"]]["exposure"] for t in protective), default=0.0)
        effective = max(own, 0.85 * inherited)
        ds = a["data_sensitivity"] / 5
        ret = min(a["retention_years"] / 20, 1.0)
        quantum_path = alg["quantum_vulnerable"] or inherited >= 0.85
        hndl = effective * ds * ret if quantum_path else 0.0
        dep = math.log1p(dependents[a["asset_id"]]) / math.log1p(max_dep)
        score = 100 * (0.28 * effective + 0.17 * ds + 0.10 * ret + 0.13 * EXTERNAL[a["exposure"]]
                       + 0.15 * dep + 0.07 * a["business_criticality"] / 5) + 25 * hndl + rng.gauss(0, 4)
        scores.append(score)

    ranked = sorted(scores)
    n = len(ranked)
    cuts = [ranked[int(n * q)] for q in (0.35, 0.65, 0.87)]
    for a, s in zip(assets, scores):
        a["analyst_label"] = CLASSES[sum(s >= c for c in cuts)]


def generate(seed: int = 42, n_assets: int = 400, profile: str = "generic", drift: int = 0) -> dict:
    """Return {'assets': [...], 'edges': [...], 'seed': seed}. Same arguments -> same data.

    profile: 'generic', 'bank' or 'hospital' (changes application names, cloud mix and data retention).
    drift:   number of later discovery rounds to simulate; each round adds one new application
             (load balancer, API gateway, backends...), so a re-scan finds new assets.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}")
    apps = PROFILES[profile]["applications"]
    b = _Builder(seed, profile)
    _build_shared(b)
    i = 0
    while len(b.assets) + 7 <= n_assets:
        base = apps[i % len(apps)]
        name = base if i < len(apps) else f"{base} {i // len(apps) + 1}"
        _build_application(b, name)
        i += 1
    for step in range(1, max(0, drift) + 1):
        b.rng = random.Random(seed * 7919 + step)
        _build_application(b, f"New service {step}")
    # remove accidental duplicate edges, keep first relation
    seen, edges = set(), []
    for e in b.edges:
        key = (e["source"], e["target"])
        if key not in seen:
            seen.add(key)
            edges.append(e)
    _analyst_labels(b.assets, edges, random.Random(seed + 1))
    return {"assets": b.assets, "edges": edges, "seed": seed, "profile": profile, "drift": drift}
