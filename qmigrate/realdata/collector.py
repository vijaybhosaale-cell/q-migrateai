"""Collect a real cryptographic inventory from public websites.

For each domain, using only public information and ordinary connections (what a browser does):

1. Post-quantum check: one TLS 1.3 ClientHello that offers the hybrid group X25519MLKEM768
   (FIPS 203 ML-KEM-768 + X25519). The server's first reply says whether it accepts it, or which
   classical group (X25519, P-256...) it wants instead. The connection is closed right after.
2. Normal HTTPS handshake (Python ssl): TLS version, cipher and the certificate chain it sends.
3. Certificates: key algorithm and size, issuer, expiry; issuers missing from the chain are fetched from
   the public "CA Issuers" URL written inside the certificate.
4. Hosting: the site's IP address is matched against the IP ranges that AWS, Google Cloud, Azure and
   Cloudflare publish, so each site is placed in the cloud that really hosts it.

No credentials, no private keys, no scanning of ports or paths.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import io
import json
import logging
import os
import re
import socket
import ssl
import struct
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import networkx as nx
import requests
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID, NameOID

from qmigrate.realdata.domain_lists import SECTORS
from qmigrate.realdata.mlkem_key import MLKEM768_PUBLIC_KEY

log = logging.getLogger("qmigrate.realdata")

UA = {"User-Agent": "Q-MigrateAI research prototype (read-only TLS inventory)"}
TRANCO_URL = "https://tranco-list.eu/top-1m.csv.zip"
AWS_RANGES = "https://ip-ranges.amazonaws.com/ip-ranges.json"
GCP_RANGES = "https://www.gstatic.com/ipranges/cloud.json"
CLOUDFLARE_RANGES = "https://www.cloudflare.com/ips-v4"
AZURE_PAGE = "https://www.microsoft.com/en-us/download/details.aspx?id=56519"
MAX_DOMAINS = 300

GROUPS = {0x11EC: "X25519MLKEM768", 0x001D: "x25519", 0x0017: "secp256r1", 0x0018: "secp384r1",
          0x0019: "secp521r1", 0x0100: "ffdhe2048", 0x0101: "ffdhe3072", 0x6399: "X25519Kyber768Draft00"}
KEX_ALGORITHM = {"X25519MLKEM768": "X25519+ML-KEM-768", "X25519Kyber768Draft00": "X25519+ML-KEM-768",
                 "x25519": "X25519", "secp256r1": "ECDHE-P256", "secp384r1": "ECDHE-P256", "secp521r1": "ECDHE-P256",
                 "ffdhe2048": "DH-2048", "ffdhe3072": "DH-2048"}
HRR_RANDOM = bytes.fromhex("CF21AD74E59A6111BE1D8C021E65B891C2A211167ABB8C5E079E09E2C8A8339C")


def cache_dir() -> Path:
    from qmigrate.config import DATA_DIR
    d = DATA_DIR / "realdata_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


# =================================================================== post-quantum probe
def _ext(kind: int, body: bytes) -> bytes:
    return struct.pack("!HH", kind, len(body)) + body


def client_hello(host: str) -> bytes:
    """TLS 1.3 ClientHello offering X25519MLKEM768 first (with a key share) and classical groups after it."""
    x25519_pub = X25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    share = MLKEM768_PUBLIC_KEY + x25519_pub          # X25519MLKEM768: ML-KEM part first, then X25519
    name = host.encode("idna")
    groups = [0x11EC, 0x001D, 0x0017, 0x0018, 0x0019, 0x0100]
    sigs = [0x0403, 0x0503, 0x0603, 0x0804, 0x0805, 0x0806, 0x0401, 0x0501, 0x0601, 0x0807]
    exts = b"".join([
        _ext(0x0000, struct.pack("!HBH", len(name) + 3, 0, len(name)) + name),
        _ext(0x000A, struct.pack("!H", 2 * len(groups)) + b"".join(struct.pack("!H", g) for g in groups)),
        _ext(0x000D, struct.pack("!H", 2 * len(sigs)) + b"".join(struct.pack("!H", s) for s in sigs)),
        _ext(0x002B, b"\x02\x03\x04"),
        _ext(0x002D, b"\x01\x01"),
        _ext(0x0033, struct.pack("!H", len(share) + 4) + struct.pack("!HH", 0x11EC, len(share)) + share),
    ])
    ciphers = b"\x13\x01\x13\x02\x13\x03"
    body = (b"\x03\x03" + os.urandom(32) + b"\x20" + os.urandom(32) + struct.pack("!H", len(ciphers)) + ciphers
            + b"\x01\x00" + struct.pack("!H", len(exts)) + exts)
    hs = b"\x01" + struct.pack("!I", len(body))[1:] + body
    return b"\x16\x03\x01" + struct.pack("!H", len(hs)) + hs


def _recv(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
    return buf


def parse_server_hello(data: bytes) -> dict:
    """Parse the body of a ServerHello / HelloRetryRequest handshake message."""
    p = 2
    random = data[p:p + 32]
    p += 32
    p += 1 + data[p]                      # session id
    p += 2 + 1                            # cipher suite, compression
    end = p + 2 + struct.unpack("!H", data[p:p + 2])[0]
    p += 2
    out = {"hrr": random == HRR_RANDOM, "tls13": False, "group": None}
    while p + 4 <= end:
        kind, length = struct.unpack("!HH", data[p:p + 4])
        val = data[p + 4:p + 4 + length]
        if kind == 0x002B and val[:2] == b"\x03\x04":
            out["tls13"] = True
        elif kind == 0x0033 and len(val) >= 2:
            code = struct.unpack("!H", val[:2])[0]
            out["group"] = GROUPS.get(code, f"0x{code:04x}")
        p += 4 + length
    return out


def pq_probe(host: str, port: int = 443, timeout: float = 8.0) -> dict:
    """Does the server accept X25519MLKEM768? If not, which classical group does it ask for?"""
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(client_hello(host))
        ctype, _, length = struct.unpack("!BHH", _recv(s, 5))
        payload = _recv(s, length)
    if ctype == 0x15:
        return {"pq": False, "group": None, "tls13": False, "note": "server refused TLS 1.3 offer (alert)"}
    if ctype != 0x16 or payload[0] != 0x02:
        return {"pq": False, "group": None, "tls13": False, "note": "unexpected reply"}
    hs_len = struct.unpack("!I", b"\x00" + payload[1:4])[0]
    sh = parse_server_hello(payload[4:4 + hs_len])
    return {"pq": sh["group"] == "X25519MLKEM768", "group": sh["group"], "tls13": sh["tls13"],
            "note": "server asked for a classical group instead" if sh["hrr"] else "server accepted the offered key share"}


# =================================================================== certificates
def _not_after(c: x509.Certificate) -> dt.datetime:
    v = getattr(c, "not_valid_after_utc", None)
    return v if v is not None else c.not_valid_after.replace(tzinfo=dt.timezone.utc)


def _name(c: x509.Certificate, oid=NameOID.COMMON_NAME, subject: bool = True) -> str:
    attrs = (c.subject if subject else c.issuer).get_attributes_for_oid(oid)
    return attrs[0].value if attrs else ""


def key_algorithm(c: x509.Certificate) -> str:
    pk = c.public_key()
    if isinstance(pk, rsa.RSAPublicKey):
        bits = pk.key_size
        return "RSA-4096" if bits >= 4096 else "RSA-3072" if bits >= 3072 else "RSA-2048"
    if isinstance(pk, ec.EllipticCurvePublicKey):
        return "ECDSA-P384" if pk.curve.key_size >= 384 else "ECDSA-P256"
    if isinstance(pk, ed25519.Ed25519PublicKey):
        return "Ed25519"
    return "RSA-2048"


def _is_ca(c: x509.Certificate) -> bool:
    try:
        return bool(c.extensions.get_extension_for_oid(ExtensionOID.BASIC_CONSTRAINTS).value.ca)
    except x509.ExtensionNotFound:
        return False


def _aia_issuer(c: x509.Certificate, timeout: float) -> x509.Certificate | None:
    try:
        aia = c.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    except x509.ExtensionNotFound:
        return None
    for d in aia:
        if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS:
            url = d.access_location.value
            if not url.startswith("http"):
                continue
            r = requests.get(url, timeout=timeout, headers=UA)
            r.raise_for_status()
            try:
                return x509.load_der_x509_certificate(r.content)
            except ValueError:
                try:
                    return x509.load_pem_x509_certificate(r.content)
                except ValueError:
                    return None
    return None


def tls_handshake(host: str, port: int = 443, timeout: float = 8.0) -> dict:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        ip = sock.getpeername()[0]
        with ctx.wrap_socket(sock, server_hostname=host) as s:
            version, cipher = s.version(), (s.cipher() or (None,))[0]
            ders = []
            if hasattr(s, "get_verified_chain"):          # Python 3.13+
                try:
                    for c in s.get_verified_chain():
                        ders.append(bytes(c) if isinstance(c, (bytes, bytearray)) else c.public_bytes(ssl._ssl.ENCODING_DER))
                except Exception:  # noqa: BLE001
                    ders = []
            if not ders:
                ders = [s.getpeercert(binary_form=True)]
    chain = [x509.load_der_x509_certificate(d) for d in ders if d]
    while len(chain) < 4 and chain[-1].issuer != chain[-1].subject:   # complete the chain from AIA (public URLs)
        try:
            issuer = _aia_issuer(chain[-1], timeout)
        except requests.RequestException:
            issuer = None
        if issuer is None or issuer in chain:
            break
        chain.append(issuer)
    return {"ip": ip, "version": version, "cipher": cipher, "chain": chain}


# =================================================================== hosting
class Hosting:
    """Which cloud hosts an IP address, from the providers' own published IP range lists."""

    def __init__(self, timeout: float = 20.0):
        self.nets: list[tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, str, str]] = []
        self.sources: dict[str, bool] = {}
        for name, loader in (("AWS", self._aws), ("GCP", self._gcp), ("Azure", self._azure), ("Cloudflare", self._cf)):
            try:
                rows = self._cached(name, loader, timeout)
                self.nets += [(ipaddress.ip_network(n), name, region) for n, region in rows]
                self.sources[name] = True
            except Exception as exc:  # noqa: BLE001
                log.warning("could not load %s IP ranges: %s", name, exc)
                self.sources[name] = False
        self.nets.sort(key=lambda t: -t[0].prefixlen)       # most specific first

    @staticmethod
    def _cached(name, loader, timeout):
        path = cache_dir() / f"ranges_{name.lower()}.json"
        if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
            return json.loads(path.read_text())
        rows = loader(timeout)
        path.write_text(json.dumps(rows))
        return rows

    @staticmethod
    def _aws(t):
        d = requests.get(AWS_RANGES, timeout=t, headers=UA).json()
        return [(p["ip_prefix"], p["region"]) for p in d["prefixes"]] + [(p["ipv6_prefix"], p["region"]) for p in d["ipv6_prefixes"]]

    @staticmethod
    def _gcp(t):
        d = requests.get(GCP_RANGES, timeout=t, headers=UA).json()
        return [(p.get("ipv4Prefix") or p.get("ipv6Prefix"), p.get("scope", "global")) for p in d["prefixes"]]

    @staticmethod
    def _azure(t):
        page = requests.get(AZURE_PAGE, timeout=t, headers=UA).text
        m = re.search(r"https://download\.microsoft\.com/[^\"']+ServiceTags_Public[^\"']+\.json", page)
        if not m:
            raise ValueError("Azure ServiceTags link not found")
        d = requests.get(m.group(0), timeout=t * 3, headers=UA).json()
        rows = []
        for v in d["values"]:
            if v["name"].startswith("AzureCloud."):
                region = v["name"].split(".", 1)[1]
                rows += [(p, region) for p in v["properties"]["addressPrefixes"]]
        return rows

    @staticmethod
    def _cf(t):
        text = requests.get(CLOUDFLARE_RANGES, timeout=t, headers=UA).text
        return [(line.strip(), "global") for line in text.splitlines() if line.strip()]

    def lookup(self, ip: str) -> tuple[str, str]:
        addr = ipaddress.ip_address(ip)
        for net, name, region in self.nets:
            if addr.version == net.version and addr in net:
                return name, region or "global"
        return "Other hosting", "unknown"


# =================================================================== domain lists
def tranco_top(n: int, timeout: float = 60.0) -> list[tuple[str, int]]:
    path = cache_dir() / "tranco_top.csv"
    if not path.exists() or time.time() - path.stat().st_mtime > 7 * 86400:
        r = requests.get(TRANCO_URL, timeout=timeout, headers=UA)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            text = z.read(z.namelist()[0]).decode()
        path.write_text("\n".join(text.splitlines()[:5000]))   # keep the top 5,000 only
    rows = []
    for line in path.read_text().splitlines()[:n]:
        rank, domain = line.split(",", 1)
        rows.append((domain.strip(), int(rank)))
    return rows


def clean_domain(d: str) -> str:
    d = d.strip().lower()
    d = re.sub(r"^[a-z]+://", "", d).split("/")[0].split(":")[0]
    return d if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", d) else ""


def targets_for(config: dict) -> tuple[list[tuple[str, int | None]], dict]:
    source = config.get("source", "finance")
    sector = SECTORS.get(source, SECTORS["custom"])
    top = max(5, min(int(config.get("top") or 50), MAX_DOMAINS))
    if source == "custom":
        names = [clean_domain(d) for d in re.split(r"[,\s;]+", str(config.get("domains", "")))]
        domains = [(d, None) for d in dict.fromkeys(n for n in names if n)][:top]
    elif source == "tranco":
        try:
            domains = tranco_top(top)
        except Exception as exc:  # noqa: BLE001
            log.warning("Tranco list download failed (%s); using the built-in popular sites", exc)
            domains = [(d, None) for d in sector["domains"][:top]]
    else:
        domains = [(d, None) for d in sector["domains"][:top]]
    return domains, sector


# =================================================================== assets
def _years_left(c: x509.Certificate) -> float:
    return round(max((_not_after(c) - dt.datetime.now(dt.timezone.utc)).days / 365.25, 0.0), 1)


def _slug(text: str, n: int = 32) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:n] or "unknown"


def _criticality(rank: int | None, default: int) -> int:
    if rank is None:
        return default
    return 5 if rank <= 100 else 4 if rank <= 1000 else 3


def measure(domain: str, timeout: float) -> dict:
    out = {"domain": domain, "errors": []}
    try:
        out["pq"] = pq_probe(domain, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        out["pq"] = None
        out["errors"].append(f"pq: {exc.__class__.__name__}")
    try:
        out["tls"] = tls_handshake(domain, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        out["tls"] = None
        out["errors"].append(f"tls: {exc.__class__.__name__}: {exc}"[:160])
    return out


def key_exchange(m: dict) -> tuple[str, str]:
    """(algorithm, protocol) of the site's key exchange."""
    pq, tls = m.get("pq") or {}, m["tls"]
    version = tls["version"] or ""
    protocol = "TLS 1.3" if version == "TLSv1.3" else "TLS 1.2" if version == "TLSv1.2" else version or "TLS"
    if pq.get("group") in KEX_ALGORITHM:
        return KEX_ALGORITHM[pq["group"]], protocol
    cipher = tls["cipher"] or ""
    if version == "TLSv1.3" or "ECDHE" in cipher:
        return ("X25519" if version == "TLSv1.3" else "ECDHE-P256"), protocol
    if cipher.startswith("DHE"):
        return "DH-2048", protocol
    return "RSA-2048", protocol                     # TLS 1.2 RSA key transport


def build_inventory(measured: list[dict], sector: dict, ranks: dict[str, int | None], hosting: Hosting) -> dict:
    assets: dict[str, dict] = {}
    edges: list[dict] = []
    for m in measured:
        if not m.get("tls"):
            continue
        d, tls = m["domain"], m["tls"]
        cloud, region = hosting.lookup(tls["ip"])
        leaf = tls["chain"][0]
        org = _name(leaf, NameOID.ORGANIZATION_NAME) or d
        alg, protocol = key_exchange(m)
        crit = _criticality(ranks.get(d), sector["criticality"])
        ep = f"TLS-{d}"
        assets[ep] = {"asset_id": ep, "cloud": cloud, "region": region, "application": d, "owner_team": org[:60],
                      "service_type": "load_balancer", "usage": "key_exchange", "protocol": protocol, "algorithm": alg,
                      "exposure": "internet", "data_sensitivity": sector["sensitivity"],
                      "retention_years": sector["retention"], "business_criticality": crit,
                      "clients_support_pqc": True,
                      "evidence": {"pq_probe": m.get("pq"), "tls_version": tls["version"], "cipher": tls["cipher"],
                                   "ip": tls["ip"], "hosting": f"{cloud} ({region})",
                                   "measured_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}}
        cert_id = f"CERT-{d}"
        assets[cert_id] = {"asset_id": cert_id, "cloud": cloud, "region": region, "application": d, "owner_team": org[:60],
                           "service_type": "tls_certificate", "usage": "signature", "protocol": "X.509 (TLS)",
                           "algorithm": key_algorithm(leaf), "exposure": "internet",
                           "data_sensitivity": sector["sensitivity"], "retention_years": _years_left(leaf),
                           "business_criticality": crit, "clients_support_pqc": False,
                           "evidence": {"subject": leaf.subject.rfc4514_string(), "issuer": leaf.issuer.rfc4514_string(),
                                        "not_after": _not_after(leaf).date().isoformat(),
                                        "key": key_algorithm(leaf), "chain_length": len(tls["chain"])}}
        edges.append({"source": ep, "target": cert_id, "relation": "trusts_cert"})
        prev = cert_id
        for c in tls["chain"][1:]:
            if not _is_ca(c):
                break
            cn = _name(c) or _name(c, NameOID.ORGANIZATION_NAME) or "CA"
            ca_id = f"CA-{_slug(cn)}"
            if ca_id not in assets:
                ca_org = _name(c, NameOID.ORGANIZATION_NAME) or cn
                assets[ca_id] = {"asset_id": ca_id, "cloud": "Public PKI", "region": "global", "application": cn[:60],
                                 "owner_team": ca_org[:60], "service_type": "certificate_authority", "usage": "signature",
                                 "protocol": "X.509 PKI", "algorithm": key_algorithm(c), "exposure": "partner",
                                 "data_sensitivity": 5, "retention_years": _years_left(c), "business_criticality": 5,
                                 "clients_support_pqc": False,
                                 "evidence": {"subject": c.subject.rfc4514_string(), "root": c.issuer == c.subject,
                                              "not_after": _not_after(c).date().isoformat()}}
            edges.append({"source": prev, "target": ca_id, "relation": "verifies_signature"})
            prev = ca_id
    edges = [dict(t) for t in {tuple(sorted(e.items())) for e in edges}]
    label_assets(assets, edges)
    # "evidence" keeps what was measured for each asset; the platform stores it for the project data view.
    return {"assets": sorted(assets.values(), key=lambda a: a["asset_id"]), "edges": sorted(edges, key=lambda e: (e["source"], e["target"]))}


# =================================================================== labels
LABEL_CUTS = (35.0, 55.0, 72.0)
CLASSES = ["Low", "Medium", "High", "Critical"]


def rubric_score(a: dict, dependents: int) -> float:
    """Migration-priority rubric used as the training label for real data (see docs/REAL_DATA.md)."""
    from qmigrate.engine.catalog import ALGORITHMS
    alg = ALGORITHMS[a["algorithm"]]
    s = 60.0 * alg["exposure"]
    if a["usage"] == "key_exchange" and alg["quantum_vulnerable"] and a["data_sensitivity"] >= 4 and a["retention_years"] >= 5:
        s += 20                                    # harvest now, decrypt later
    elif a["usage"] == "key_exchange" and alg["quantum_vulnerable"]:
        s += 8
    if a["usage"] == "signature" and alg["quantum_vulnerable"]:
        s += 6 * min(a["retention_years"], 10) / 10   # long-lived signing keys matter more
    s += 12 * min(dependents, 30) / 30             # how many sites rely on it
    s += 8 * (a["business_criticality"] - 1) / 4
    return round(min(s, 100.0), 1)


def label_assets(assets: dict[str, dict], edges: list[dict], force_balance: bool = False) -> None:
    g = nx.DiGraph()
    g.add_nodes_from(assets)
    g.add_edges_from((e["source"], e["target"]) for e in edges)
    scores = {n: rubric_score(a, len(nx.ancestors(g, n))) for n, a in assets.items()}
    labels = {n: CLASSES[sum(s >= c for c in LABEL_CUTS)] for n, s in scores.items()}
    counts = {c: sum(1 for v in labels.values() if v == c) for c in CLASSES}
    if force_balance or (len(assets) >= 20 and min(counts.values()) < 6):
        # A small or uniform estate: rank by the same rubric and split into four equal groups,
        # so the AI models always see all four classes.
        order = sorted(scores, key=lambda n: scores[n])
        for i, n in enumerate(order):
            labels[n] = CLASSES[min(4 * i // len(order), 3)]
    for n, a in assets.items():
        a["analyst_label"] = labels[n]


# =================================================================== entry point
def collect(config: dict, timeout: float = 8.0, workers: int = 12, progress=None) -> dict:
    domains, sector = targets_for(config)
    if not domains:
        raise ValueError("No domains to check. Add domains to the connection.")
    ranks = dict(domains)
    hosting = Hosting()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        measured = list(pool.map(lambda d: measure(d[0], timeout), domains))
    if progress:
        progress(measured)
    reached = [m for m in measured if m.get("tls")]
    if not reached:
        raise ConnectionError("No website could be reached. Check the internet connection, firewall or proxy.")
    inv = build_inventory(measured, sector, ranks, hosting)
    inv["meta"] = {"source": config.get("source"), "domains": len(domains), "reached": len(reached),
                   "failed": [{"domain": m["domain"], "errors": m["errors"]} for m in measured if not m.get("tls")],
                   "hosting_lists": hosting.sources,
                   "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    return inv
