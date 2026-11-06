"""Config check (P8 in the platform): paste configuration, get what each TLS endpoint negotiates."""
from __future__ import annotations

from conftest import login

ANALYST = "analyst@demofinance.example"
VIEWER = "viewer@demofinance.example"
HEALTH = "admin@demohealth.example"
ADMIN = "admin@demofinance.example"

NGINX = "server {\n  listen 443 ssl;\n  ssl_ecdh_curve X25519:prime256v1:secp384r1;\n}\n"
ENVOY = ("transport_socket:\n  typed_config:\n    '@type': type.googleapis.com/envoy.extensions."
         "transport_sockets.tls.v3.DownstreamTlsContext\n")
HAPROXY_PQ = "global\n  ssl-default-bind-curves X25519MLKEM768:X25519:P-256\n"


def test_check_finds_pinned_lists_and_off_defaults(client):
    login(client, ANALYST)
    r = client.post("/api/config-check", json={"files": [
        {"name": "sites/nginx.conf", "text": NGINX}, {"name": "envoy.yaml", "text": ENVOY},
        {"name": "haproxy.cfg", "text": HAPROXY_PQ}]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["files"] == ["nginx.conf", "envoy.yaml", "haproxy.cfg"]       # no directories kept
    assert d["summary"]["verdict"] == "pq_off"
    by = {f["file"]: f for f in d["findings"]}
    assert by["nginx.conf"]["outcome"] == "off_pinned" and "X25519MLKEM768" in by["nginx.conf"]["advice"]
    assert by["envoy.yaml"]["outcome"] == "off_default" and by["envoy.yaml"]["default_source"].startswith("https://")
    assert by["haproxy.cfg"]["outcome"] == "on" and by["haproxy.cfg"]["min_openssl"] == "3.5"
    assert d["summary"]["breakage_risk"] == 1
    assert d["findings"][0]["outcome"] == "off_pinned"                     # worst first


def test_latest_check_and_study_are_listed(client):
    login(client, VIEWER)
    d = client.get("/api/config-check").json()
    assert d["checks"] and d["checks"][0]["findings"]
    assert d["study"]["repositories_scanned"] >= 30
    assert "envoy" in d["study"]["defaults"]


def test_viewer_cannot_run_a_check(client):
    login(client, VIEWER)
    assert client.post("/api/config-check", json={"files": [{"name": "a.conf", "text": NGINX}]}).status_code == 403


def test_limits(client):
    login(client, ANALYST)
    too_many = [{"name": f"{i}.conf", "text": "x"} for i in range(21)]
    assert client.post("/api/config-check", json={"files": too_many}).status_code == 422
    assert client.post("/api/config-check", json={"files": [{"name": "a", "text": "x" * 200_001}]}).status_code == 422
    big = [{"name": f"{i}.conf", "text": "x" * 199_000} for i in range(6)]
    assert client.post("/api/config-check", json={"files": big}).status_code == 400


def test_other_company_does_not_see_checks(client):
    login(client, HEALTH)
    assert client.get("/api/config-check").json()["checks"] == []


def test_check_is_audited_and_exported(client):
    login(client, ADMIN)
    assert any(a["action"] == "config.checked" for a in client.get("/api/audit").json())
    export = client.get("/api/gdpr/export").json()
    assert export["config_checks"] and "text" not in export["config_checks"][0]


def test_pdf_report_includes_the_latest_check(client):
    import io
    login(client, ANALYST)
    r = client.get("/api/report.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    try:
        from pypdf import PdfReader
    except ImportError:
        return
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "TLS configuration check" in text
