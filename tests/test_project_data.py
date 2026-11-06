"""Project data view: rows per project, migration status, corrections that survive rediscovery, downloads."""
from __future__ import annotations

import csv
import io
import json

from conftest import login

FIN = "admin@demofinance.example"
FIN_CISO = "ciso@demofinance.example"
FIN_VIEWER = "viewer@demofinance.example"
HEALTH = "admin@demohealth.example"


def first_project(client) -> dict:
    r = client.get("/api/projects")
    assert r.status_code == 200, r.text
    projects = r.json()["projects"]
    assert projects and projects[0]["assets"] > 0
    return projects[0]


def test_project_list_and_data(client):
    login(client, FIN_CISO)
    p = first_project(client)
    d = client.get(f"/api/projects/{p['id']}/data").json()
    s = d["summary"]
    assert s["assets"] == len(d["rows"]) == p["assets"]
    assert s["migrated"] + s["needs_migration"] + s["safe"] == s["assets"]
    assert s["used_in_analysis"] == s["assets"] and d["analysis_ready"] is True
    assert sum(t["assets"] for t in d["targets"]) == s["assets"]
    row = d["rows"][0]
    for key in ("asset_id", "target", "algorithm_discovered", "algorithm_current", "status", "risk_class",
                "data_sensitivity", "retention_years", "used_in_analysis", "corrections"):
        assert key in row
    assert {g["field"] for g in d["field_guide"]} >= {"algorithm_discovered", "status", "used_in_analysis"}


def test_migrated_rows_show_as_migrated(client):
    login(client, FIN_CISO)
    p = first_project(client)
    d = client.get(f"/api/projects/{p['id']}/data").json()
    top = client.get("/api/plan").json()["queue"][0]
    todo = next(r for r in d["rows"] if r["asset_id"] == top["asset_id"])
    assert todo["status"] == "needs_migration"
    target = top["target"]
    r = client.post("/api/lab/migrate", json={"asset_id": todo["asset_id"], "target": target})
    assert r.status_code == 200, r.text
    d2 = client.get(f"/api/projects/{p['id']}/data").json()
    row = next(x for x in d2["rows"] if x["asset_id"] == todo["asset_id"])
    assert row["status"] == "migrated" and row["algorithm_current"] == target
    assert row["migrated_at"] and row["migrated_by"] == FIN_CISO
    assert d2["summary"]["migrated"] == d["summary"]["migrated"] + 1
    client.post("/api/lab/rollback", json={"asset_id": todo["asset_id"]})


def test_corrections_validate_audit_and_survive_rediscovery(client):
    login(client, FIN_CISO)
    p = first_project(client)
    d = client.get(f"/api/projects/{p['id']}/data").json()
    row = d["rows"][3]
    aid = row["asset_id"]
    new_sens = 1 if row["data_sensitivity"] != 1 else 2
    url = f"/api/projects/{p['id']}/assets/{aid}"

    assert client.patch(url, json={"changes": {"data_sensitivity": 9}}).status_code == 400
    assert client.patch(url, json={"changes": {"algorithm_current": "RSA-2048"}}).status_code == 400
    assert client.patch(url, json={"changes": {"exposure": "moon"}}).status_code == 400

    r = client.patch(url, json={"changes": {"data_sensitivity": new_sens, "retention_years": 12}, "note": "checked by IT"})
    assert r.status_code == 200, r.text
    assert set(r.json()["changed"]) == {"data_sensitivity", "retention_years", "note"}
    got = next(x for x in client.get(f"/api/projects/{p['id']}/data").json()["rows"] if x["asset_id"] == aid)
    assert got["data_sensitivity"] == new_sens and got["retention_years"] == 12 and got["note"] == "checked by IT"
    assert got["corrections"]["data_sensitivity"]["original"] == row["data_sensitivity"]
    assert got["corrections"]["data_sensitivity"]["by"] == FIN_CISO
    # the risk engine sees the corrected value
    asset = next(a for a in client.get("/api/assets").json() if a["asset_id"] == aid)
    assert asset["data_sensitivity"] == new_sens

    login(client, FIN)
    assert any(a["action"] == "data.corrected" and a["target"] == aid for a in client.get("/api/audit").json())

    # discovery runs again: the correction is kept
    platform = client.app.state.platform
    tid = client.get("/api/auth/me").json()["tenant"]["id"]
    platform.start_discovery(tid, None, p["id"], wait=True)
    login(client, FIN_CISO)
    again = next(x for x in client.get(f"/api/projects/{p['id']}/data").json()["rows"] if x["asset_id"] == aid)
    assert again["data_sensitivity"] == new_sens and again["note"] == "checked by IT"

    # back to the measured value
    r = client.patch(url, json={"revert": ["data_sensitivity", "retention_years"]})
    assert r.status_code == 200
    back = next(x for x in client.get(f"/api/projects/{p['id']}/data").json()["rows"] if x["asset_id"] == aid)
    assert back["data_sensitivity"] == row["data_sensitivity"] and not back["corrections"]


def test_viewer_reads_but_cannot_correct(client):
    login(client, FIN_VIEWER)
    p = first_project(client)
    body = client.get("/api/projects").json()
    assert body["can_edit"] is False
    aid = client.get(f"/api/projects/{p['id']}/data").json()["rows"][0]["asset_id"]
    assert client.patch(f"/api/projects/{p['id']}/assets/{aid}", json={"note": "x"}).status_code == 403
    assert client.get(f"/api/projects/{p['id']}/export?format=csv").status_code == 200


def test_other_company_cannot_see_project(client):
    login(client, FIN_CISO)
    p = first_project(client)
    login(client, HEALTH)
    assert client.get(f"/api/projects/{p['id']}/data").status_code == 404
    assert client.get(f"/api/projects/{p['id']}/export?format=json").status_code == 404


def test_downloads(client):
    login(client, FIN_CISO)
    p = first_project(client)
    n = p["assets"]
    r = client.get(f"/api/projects/{p['id']}/export?format=csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and ".csv" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][0] == "Asset" and "Status" in rows[0] and len(rows) == n + 1

    r = client.get(f"/api/projects/{p['id']}/export?format=json")
    data = json.loads(r.content)
    assert data["format"] == "Q-MigrateAI project data v1" and len(data["rows"]) == n

    r = client.get(f"/api/projects/{p['id']}/export?format=xlsx")
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Summary", "Data", "Field guide"]
    assert wb["Data"].max_row == n + 1

    assert client.get(f"/api/projects/{p['id']}/export?format=exe").status_code == 400
    login(client, FIN)
    assert any(a["action"] == "data.exported" for a in client.get("/api/audit").json())


def test_public_website_evidence_and_not_reached(client, monkeypatch):
    """A project with typed domains keeps what was measured per site, and lists the sites it could not reach."""
    from qmigrate.server.connectors import public_web

    def fake_inventory(self, run_index=0):
        ev_ep = {"pq_probe": {"pq": True, "group": "X25519MLKEM768", "tls13": True, "note": "server accepted"},
                 "tls_version": "TLSv1.3", "cipher": "TLS_AES_128_GCM_SHA256", "ip": "203.0.113.7",
                 "hosting": "Cloudflare (global)", "measured_at": "2026-11-05T10:00:00+00:00"}
        ev_cert = {"subject": "CN=chatgpt.com", "issuer": "CN=WE1,O=Google Trust Services,C=US",
                   "not_after": "2027-01-01", "key": "ECDSA-P256", "chain_length": 3}
        base = {"cloud": "Cloudflare", "region": "global", "application": "chatgpt.com", "owner_team": "OpenAI",
                "exposure": "internet", "data_sensitivity": 3, "business_criticality": 4, "analyst_label": "High"}
        return {"assets": [
            {**base, "asset_id": "TLS-chatgpt.com", "service_type": "load_balancer", "usage": "key_exchange",
             "protocol": "TLS 1.3", "algorithm": "X25519+ML-KEM-768", "retention_years": 3,
             "clients_support_pqc": True, "evidence": ev_ep},
            {**base, "asset_id": "CERT-chatgpt.com", "service_type": "tls_certificate", "usage": "signature",
             "protocol": "X.509 (TLS)", "algorithm": "ECDSA-P256", "retention_years": 0.2,
             "clients_support_pqc": False, "evidence": ev_cert}],
            "edges": [{"source": "TLS-chatgpt.com", "target": "CERT-chatgpt.com", "relation": "trusts_cert"}],
            "meta": {"source": "custom", "domains": 2, "reached": 1,
                     "failed": [{"domain": "unreachable.example", "errors": ["tls: timeout"]}]}}

    monkeypatch.setattr(public_web.PublicWebConnector, "discover", fake_inventory)
    login(client, FIN)
    tid = client.get("/api/auth/me").json()["tenant"]["id"]
    r = client.post("/api/connections", json={"provider": "public", "display_name": "My websites",
                                              "config": {"source": "custom", "domains": "chatgpt.com, unreachable.example"}})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    client.app.state.platform.start_discovery(tid, None, cid, wait=True)

    d = client.get(f"/api/projects/{cid}/data").json()
    assert d["project"]["targets"] == "chatgpt.com, unreachable.example"
    by_id = {x["asset_id"]: x for x in d["rows"]}
    ep, cert = by_id["TLS-chatgpt.com"], by_id["CERT-chatgpt.com"]
    assert ep["status"] == "safe" and ep["pq_group"] == "X25519MLKEM768" and ep["tls_version"] == "TLSv1.3"
    assert ep["ip"] == "203.0.113.7" and ep["used_in_analysis"]
    assert cert["status"] == "needs_migration" and "Google Trust Services" in cert["cert_issuer"]
    assert cert["cert_expires"] == "2027-01-01"
    assert d["summary"]["not_reached"] == 1 and d["not_reached"][0]["domain"] == "unreachable.example"
    assert d["targets"][0]["target"] == "chatgpt.com" and d["targets"][0]["assets"] == 2


def test_page_is_served(client):
    r = client.get("/project-data/")
    assert r.status_code == 200 and "Project data" in r.text
    assert client.get("/project-data/data.js").status_code == 200
