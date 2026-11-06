"""Safety checks for running Q-MigrateAI on a shared server.

1. Discovery never connects into the server's own network (SSRF): domains and certificate
   "CA Issuers" URLs that resolve to private, loopback or link-local addresses are refused.
2. With CLOUD_CREDENTIALS=role the cloud connectors never use the server's own cloud login.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from qmigrate.realdata import collector as col
from qmigrate.server.connectors.base import ConnectorNotReady
from qmigrate.server.connectors.clouds import make_connector

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ SSRF guard
def test_private_addresses_are_refused(monkeypatch):
    monkeypatch.delenv("ALLOW_PRIVATE_TARGETS", raising=False)
    with pytest.raises(col.UnsafeTarget):
        col.public_address("localhost")


def test_a_public_name_pointing_inside_is_refused(monkeypatch):
    """A real-looking domain whose DNS answer is the cloud metadata address must not be contacted."""
    monkeypatch.delenv("ALLOW_PRIVATE_TARGETS", raising=False)
    monkeypatch.setattr(col.socket, "getaddrinfo",
                        lambda host, port, **kw: [(2, 1, 6, "", ("169.254.169.254", port))])
    with pytest.raises(col.UnsafeTarget):
        col.public_address("innocent-looking.example.com")
    m = col.measure("innocent-looking.example.com", timeout=1)
    assert m["tls"] is None and m["pq"] is None
    assert m["errors"] and m["errors"][0].startswith("refused")


def test_public_address_is_returned_for_the_connection(monkeypatch):
    monkeypatch.setattr(col.socket, "getaddrinfo",
                        lambda host, port, **kw: [(2, 1, 6, "", ("93.184.216.34", port))])
    assert col.public_address("example.com") == "93.184.216.34"


def test_lab_mode_allows_private_targets(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_TARGETS", "1")
    assert col.public_address("localhost") in ("127.0.0.1", "::1")


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/ca.der",
    "http://127.0.0.1/ca.der",
    "http://169.254.169.254/latest/meta-data/",
    "http://localhost/ca.der",
    "http://example.com:8080/ca.der",
    "http://[::1]/ca.der",
])
def test_unsafe_ca_issuer_urls_are_not_fetched(url, monkeypatch):
    monkeypatch.delenv("ALLOW_PRIVATE_TARGETS", raising=False)
    assert col.aia_url_allowed(url) is False


def test_public_ca_issuer_url_is_allowed(monkeypatch):
    monkeypatch.setattr(col.socket, "getaddrinfo",
                        lambda host, port, **kw: [(2, 1, 6, "", ("93.184.216.34", port))])
    assert col.aia_url_allowed("http://crt.example-ca.com/intermediate.der") is True


# ------------------------------------------------------------------ cloud logins on a shared server
def test_role_mode_switches_off_azure_and_gcp(monkeypatch):
    monkeypatch.setenv("CLOUD_CREDENTIALS", "role")
    for provider, cfg in (("azure", {"subscription_id": "x"}), ("gcp", {"project_id": "x"})):
        with pytest.raises(ConnectorNotReady):
            make_connector(provider, cfg, "inprocess")


def test_role_mode_requires_a_customer_role_for_aws(monkeypatch):
    monkeypatch.setenv("CLOUD_CREDENTIALS", "role")
    with pytest.raises(ConnectorNotReady):
        make_connector("aws", {"regions": "eu-west-3", "external_id": "qm-abc"}, "inprocess")
    with pytest.raises(ConnectorNotReady):
        make_connector("aws", {"role_arn": "arn:aws:iam::123456789012:role/R"}, "inprocess")   # no external id


def test_role_mode_never_uses_the_server_profile(monkeypatch):
    monkeypatch.setenv("CLOUD_CREDENTIALS", "role")
    c = make_connector("aws", {"role_arn": "arn:aws:iam::123456789012:role/R", "external_id": "qm-abc",
                               "profile": "server-admin"}, "inprocess")
    assert "profile" not in c.config
    assert c.config["external_id"] == "qm-abc"


def test_local_mode_keeps_the_laptop_login(monkeypatch):
    monkeypatch.setenv("CLOUD_CREDENTIALS", "local")
    c = make_connector("aws", {"regions": "eu-west-3", "profile": "default"}, "inprocess")
    assert c.config["profile"] == "default"


def test_role_mode_marks_providers_in_the_catalogue():
    code = ("import json; from qmigrate.server.connectors.clouds import PROVIDERS as P; "
            "print(json.dumps({k: v['status'] for k, v in P.items()} | "
            "{'aws_fields': [f['key'] for f in P['aws']['fields']]}))")
    env = {**os.environ, "CLOUD_CREDENTIALS": "role", "PYTHONPATH": os.pathsep.join([str(ROOT), *sys.path])}
    out = json.loads(subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                                    check=True, cwd=str(ROOT)).stdout)
    assert out["azure"] == "laptop_only" and out["gcp"] == "laptop_only"
    assert out["aws"] == "available" and "profile" not in out["aws_fields"]


# ------------------------------------------------------------------ honest labels in the API
def test_health_and_models_say_where_data_comes_from(client):
    from conftest import login
    assert client.get("/api/health").json()["data_source"] == "simulator"
    login(client, "analyst@demofinance.example")
    assert client.get("/api/models").json()["label_source"] == "simulator"
