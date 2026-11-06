"""Real-data connector, tested offline against local TLS servers (no internet needed).

* a Python `ssl` server (system OpenSSL, classical only) must answer the post-quantum offer with a
  request for a classical group;
* a pyOpenSSL server (the OpenSSL bundled with `cryptography`, 3.5+) must accept X25519MLKEM768;
* the whole platform must discover, train and plan on an inventory built by the collector.
"""
from __future__ import annotations

import datetime as dt
import socket
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from conftest import login, make_settings
from qmigrate.realdata import collector as col


def _cert(cn, issuer_cn, pub, signer, ca, org="Test Lab (synthetic)"):
    now = dt.datetime.now(dt.timezone.utc)
    b = (x509.CertificateBuilder()
         .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn), x509.NameAttribute(NameOID.ORGANIZATION_NAME, org)]))
         .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_cn), x509.NameAttribute(NameOID.ORGANIZATION_NAME, org)]))
         .public_key(pub).serial_number(x509.random_serial_number())
         .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=3650 if ca else 90))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(pub), critical=False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signer.public_key()), critical=False))
    if ca:
        b = b.add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
    else:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
    return b.sign(signer, hashes.SHA256())


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    d = tmp_path_factory.mktemp("tls")
    ca_key = ec.generate_private_key(ec.SECP384R1())
    ca = _cert("Test Root CA", "Test Root CA", ca_key.public_key(), ca_key, True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = _cert("localhost", "Test Root CA", key.public_key(), ca_key, False)
    pem = serialization.Encoding.PEM
    (d / "chain.pem").write_bytes(leaf.public_bytes(pem) + ca.public_bytes(pem))
    (d / "ca.pem").write_bytes(ca.public_bytes(pem))
    (d / "key.pem").write_bytes(key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return {"dir": d, "leaf": leaf, "ca": ca}


def _serve(handler):
    srv = socket.create_server(("127.0.0.1", 0))

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            try:
                handler(conn)
            except Exception:  # noqa: BLE001
                pass
            finally:
                conn.close()
    threading.Thread(target=loop, daemon=True).start()
    return srv


@pytest.fixture(scope="module")
def classical_server(lab):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(lab["dir"] / "chain.pem", lab["dir"] / "key.pem")

    def h(conn):
        with ctx.wrap_socket(conn, server_side=True) as s:
            s.recv(1)
    srv = _serve(h)
    yield srv.getsockname()[1]
    srv.close()


@pytest.fixture(scope="module")
def pq_server(lab):
    SSL = pytest.importorskip("OpenSSL.SSL")
    from cryptography.hazmat.backends.openssl import backend
    major, minor = (int(x) for x in backend.openssl_version_text().split()[1].split(".")[:2])
    if (major, minor) < (3, 5):
        pytest.skip("needs the OpenSSL 3.5+ bundled with recent cryptography wheels")
    ctx = SSL.Context(SSL.TLS_SERVER_METHOD)
    ctx.use_certificate_chain_file(str(lab["dir"] / "chain.pem"))
    ctx.use_privatekey_file(str(lab["dir"] / "key.pem"))

    def h(conn):
        s = SSL.Connection(ctx, conn)
        s.set_accept_state()
        s.do_handshake()
    srv = _serve(h)
    yield srv.getsockname()[1]
    srv.close()


def test_client_hello_and_classical_server(classical_server):
    hello = col.client_hello("example.com")
    assert hello[:3] == b"\x16\x03\x01" and b"example.com" in hello and col.MLKEM768_PUBLIC_KEY in hello
    r = col.pq_probe("localhost", classical_server)
    assert r["tls13"] and not r["pq"] and r["group"] == "x25519"


def test_post_quantum_server_detected(pq_server):
    r = col.pq_probe("localhost", pq_server)
    assert r["pq"] and r["group"] == "X25519MLKEM768"


class _Hosting:
    sources = {"AWS": True}

    def lookup(self, ip):
        return ("AWS", "eu-west-3")


def _measured(lab, n: int, pq_every: int = 3) -> list[dict]:
    out = []
    for i in range(n):
        out.append({"domain": f"site{i}.example", "errors": [],
                    "pq": {"pq": i % pq_every == 0, "group": "X25519MLKEM768" if i % pq_every == 0 else "secp256r1", "tls13": True},
                    "tls": {"ip": "192.0.2.1", "version": "TLSv1.3", "cipher": "TLS_AES_128_GCM_SHA256",
                            "chain": [lab["leaf"], lab["ca"]]}})
    out.append({"domain": "down.example", "errors": ["tls: timeout"], "pq": None, "tls": None})
    return out


def test_build_inventory(lab):
    from qmigrate.engine.catalog import ALGORITHMS, SERVICE_LABELS
    from qmigrate.realdata.domain_lists import SECTORS
    inv = col.build_inventory(_measured(lab, 30), SECTORS["finance"], {}, _Hosting())
    by_id = {a["asset_id"]: a for a in inv["assets"]}
    assert len(by_id) == 61                       # 30 endpoints + 30 certificates + 1 shared CA
    assert by_id["TLS-site0.example"]["algorithm"] == "X25519+ML-KEM-768"
    assert by_id["TLS-site1.example"]["algorithm"] == "ECDHE-P256"
    assert by_id["CERT-site1.example"]["algorithm"] == "RSA-2048"
    assert by_id["CA-Test-Root-CA"]["algorithm"] == "ECDSA-P384" and by_id["CA-Test-Root-CA"]["cloud"] == "Public PKI"
    assert by_id["TLS-site1.example"]["cloud"] == "AWS"
    assert {"source": "CERT-site1.example", "target": "CA-Test-Root-CA", "relation": "verifies_signature"} in inv["edges"]
    for a in inv["assets"]:
        assert a["algorithm"] in ALGORITHMS and a["service_type"] in SERVICE_LABELS
    labels = {a["analyst_label"] for a in inv["assets"]}
    assert labels == {"Low", "Medium", "High", "Critical"}
    assert by_id["TLS-site0.example"]["analyst_label"] == "Low"     # already post-quantum


def test_tranco_and_custom_targets():
    domains, sector = col.targets_for({"source": "custom", "domains": "https://Bank.example/x, bad, a.org"})
    assert [d for d, _ in domains] == ["bank.example", "a.org"] and sector["sensitivity"] == 4
    domains, _ = col.targets_for({"source": "health", "top": 10})
    assert len(domains) == 10 and domains[0][0] == "nhs.uk"


def test_platform_runs_on_real_inventory(lab, tmp_path, monkeypatch):
    """Discovery -> training -> plan -> migration on a collector inventory, through the API."""
    from fastapi.testclient import TestClient

    from qmigrate.realdata.domain_lists import SECTORS
    from qmigrate.server.app import create_app
    inv = col.build_inventory(_measured(lab, 40), SECTORS["finance"], {}, _Hosting())
    monkeypatch.setattr(col, "collect", lambda config, **kw: inv)
    s, _ = make_settings(tmp_path, "sqlite")
    s.data_source = "public"
    with TestClient(create_app(s, seed_in_background=False), headers={"X-QM-Request": "1"}) as c:
        c.app_settings = s
        login(c, "ciso@demofinance.example")
        conns = c.get("/api/connections").json()
        assert conns["connections"][0]["provider"] == "public"
        assert conns["connections"][0]["config"]["source"] == "finance"
        assets = c.get("/api/assets").json()
        rows = assets["items"] if isinstance(assets, dict) and "items" in assets else assets
        assert len(rows) == 81
        assert c.get("/api/plan").status_code == 200
        me = c.get("/api/auth/me").json()
        assert me["tenant"]["is_demo"] is False
