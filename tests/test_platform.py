"""End-to-end API tests. They run once on SQLite and once on PostgreSQL (if QM_TEST_PG is set)."""
from __future__ import annotations

import http.server
import json
import threading
import time

import pytest

from conftest import login
from qmigrate.server.security import totp_code, totp_now_step

FIN = "admin@demofinance.example"
FIN_CISO = "ciso@demofinance.example"
FIN_ANALYST = "analyst@demofinance.example"
FIN_VIEWER = "viewer@demofinance.example"
HEALTH = "admin@demohealth.example"


def wait_for_run(client, timeout=120):
    for _ in range(timeout):
        runs = client.get("/api/discovery/runs").json()
        if runs and runs[0]["status"] != "running":
            return runs[0]
        time.sleep(1)
    raise AssertionError("discovery did not finish")


def test_health_and_public_config(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    if client.backend == "postgres":
        assert h["rls_enforced"] is True, "the app must connect as a non-superuser so RLS applies"
    assert h["demo_data"] == "ready"
    cfg = client.get("/api/public/config").json()
    assert cfg["allow_signup"] and len(cfg["demo_accounts"]) == 2


def test_refuses_placeholder_secrets(tmp_path):
    from fastapi.testclient import TestClient

    from conftest import make_settings
    from qmigrate.server.app import create_app
    s, _ = make_settings(tmp_path, "sqlite")
    s.secret_key = "change-me-to-a-long-random-value"
    with pytest.raises(RuntimeError, match="change-me"):
        with TestClient(create_app(s, seed_in_background=False)):
            pass


def test_security_headers_and_csrf(client):
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": FIN, "password": "x"}, headers={"X-QM-Request": ""})
    assert r.status_code == 403


def test_login_failure_and_rate_limit(client):
    client.cookies.clear()
    for _ in range(8):
        r = client.post("/api/auth/login", json={"email": "nobody@nowhere.example", "password": "wrong"})
        assert r.status_code in (401, 429)
    r = client.post("/api/auth/login", json={"email": "nobody@nowhere.example", "password": "wrong"})
    assert r.status_code == 429
    client.app.state.platform.rate.hits.clear()


def test_requires_login(client):
    client.cookies.clear()
    assert client.get("/api/overview").status_code == 401
    assert client.get("/api/assets").status_code == 401


def test_overview_and_core_pages(client):
    login(client, FIN)
    ov = client.get("/api/overview").json()
    assert ov["has_data"] and ov["now"]["total_assets"] > 100
    assert 0 <= ov["readiness"]["overall"] <= 100 and len(ov["top_queue"]) == 5
    assets = client.get("/api/assets").json()
    assert len(assets) == ov["now"]["total_assets"]
    g = client.get("/api/graph").json()
    assert len(g["nodes"]) == len(assets) and g["edges"]
    m = client.get("/api/models").json()
    assert [x["key"] for x in m["models"]] == ["rule_based", "rf_asset", "mlp_asset", "mlp_graph", "gnn_sign"]
    assert all(len(x["confusion"]) == 4 for x in m["models"])
    plan = client.get("/api/plan").json()
    assert [w["name"] for w in plan["waves"]] == ["Wave 1", "Wave 2", "Wave 3"]
    curve = client.get("/api/whatif?max_n=25").json()
    assert curve[0]["n"] == 0 and curve[-1]["quantum_exposed"] <= curve[0]["quantum_exposed"]
    top = ov["top_queue"][0]["asset_id"]
    x = client.get(f"/api/assets/{top}/explain").json()
    assert x["reasons"] and x["ai"]["attributions"] and x["targets"]
    deps = client.get(f"/api/graph/dependents/{top}").json()
    assert set(deps["direct"]) <= set(deps["all"])


def test_tenant_isolation_api(client):
    login(client, HEALTH)
    health_ids = {a["asset_id"] for a in client.get("/api/assets").json()}
    login(client, FIN)
    fin_assets = client.get("/api/assets").json()
    fin_ids = {a["asset_id"] for a in fin_assets}
    assert client.get("/api/auth/me").json()["tenant"]["name"] == "Demo Finance Co."
    only_health = sorted(health_ids - fin_ids)
    assert only_health, "the two demo estates should differ"
    assert client.get(f"/api/assets/{only_health[0]}/explain").status_code == 404
    assert client.post("/api/lab/migrate", json={"asset_id": only_health[0], "target": "X25519+ML-KEM-768"}).status_code == 404
    # Shared IDs exist in both tenants but must show each tenant's own data
    login(client, HEALTH)
    alerts = client.get("/api/alerts").json()["alerts"]
    assert all(a.get("tenant_id") in (None, client.get("/api/auth/me").json()["tenant"]["id"]) for a in alerts)


def test_rls_enforced_in_postgres(client):
    if client.backend != "postgres":
        pytest.skip("RLS exists only in PostgreSQL")
    db = client.app.state.platform.db
    with db.session() as c:  # no tenant set
        assert c.scalar("SELECT COUNT(*) AS n FROM assets") == 0
        assert c.scalar("SELECT COUNT(*) AS n FROM users") == 0
        tenants = c.all("SELECT id, name FROM tenants ORDER BY name")
    fin = next(t["id"] for t in tenants if t["name"] == "Demo Finance Co.")
    other = next(t["id"] for t in tenants if t["name"] == "Demo Health Group")
    with db.session(fin) as c:
        # even a query WITHOUT a tenant filter only sees this tenant's rows
        rows = c.all("SELECT DISTINCT tenant_id FROM assets")
        assert [r["tenant_id"] for r in rows] == [fin]
        with pytest.raises(Exception):
            c.execute("INSERT INTO alerts (id, tenant_id, severity, title, created_at) VALUES ('x', ?, 'info', 't', 'now')",
                      (other,))


def test_roles(client):
    login(client, FIN_VIEWER)
    assert client.get("/api/overview").status_code == 200
    assert client.post("/api/lab/migrate", json={"asset_id": "AWS-KMS-001", "target": "X25519+ML-KEM-768"}).status_code == 403
    assert client.post("/api/discovery/run", json={}).status_code == 403
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/audit").status_code == 403
    login(client, FIN_ANALYST)
    top = client.get("/api/plan").json()["queue"][0]
    assert client.post("/api/lab/validate", json={"asset_id": top["asset_id"], "target": top["target"]}).status_code == 200
    assert client.post("/api/lab/migrate", json={"asset_id": top["asset_id"], "target": top["target"]}).status_code == 403
    assert client.get("/api/gdpr/export").status_code == 403
    login(client, FIN_CISO)
    assert client.get("/api/audit").status_code == 200
    assert client.get("/api/users").status_code == 403


def test_lab_validate_migrate_rollback(client):
    login(client, FIN_CISO)
    client.post("/api/migrations/reset")
    top = client.get("/api/plan").json()["queue"][0]
    lab = client.get(f"/api/lab/{top['asset_id']}").json()
    assert lab["targets"][0]["algorithm"] == top["target"] and not lab["can_rollback"]
    bad = client.post("/api/lab/validate", json={"asset_id": top["asset_id"], "target": "AES-256-GCM"}).json()
    if top["target"] != "AES-256-GCM":
        assert bad["valid"] is False
        assert client.post("/api/lab/migrate", json={"asset_id": top["asset_id"], "target": "AES-256-GCM"}).status_code == 400
    ok = client.post("/api/lab/validate", json={"asset_id": top["asset_id"], "target": top["target"]}).json()
    assert ok["valid"] and ok["kpis_after"]["quantum_exposed"] <= ok["kpis_before"]["quantum_exposed"]
    before = client.get("/api/overview").json()["now"]
    m = client.post("/api/lab/migrate", json={"asset_id": top["asset_id"], "target": top["target"]})
    assert m.status_code == 200
    after = client.get("/api/overview").json()["now"]
    assert after["quantum_exposed"] <= before["quantum_exposed"]
    assert client.get(f"/api/lab/{top['asset_id']}").json()["can_rollback"]
    rb = client.post("/api/lab/rollback", json={"asset_id": top["asset_id"]})
    assert rb.status_code == 200 and rb.json()["to"] == top["algorithm"]
    assert client.get("/api/overview").json()["now"]["quantum_exposed"] == before["quantum_exposed"]
    hist = client.get("/api/migrations").json()
    assert [h["action"] for h in hist[:2]] == ["rollback", "migrate"]


def test_wave_migration_and_report(client):
    login(client, FIN_CISO)
    client.post("/api/migrations/reset")
    before = client.get("/api/overview").json()["now"]
    res = client.post("/api/migrations/wave", json={"wave": "Wave 1"}).json()
    assert len(res["steps"]) == 20
    exposed = [s["kpis"]["quantum_exposed"] for s in res["steps"]]
    assert exposed == sorted(exposed, reverse=True), "exposure only goes down during a wave"
    assert res["steps"][-1]["kpis"]["quantum_exposed"] < before["quantum_exposed"]
    now = client.get("/api/overview").json()["now"]
    assert now["quantum_exposed"] == res["steps"][-1]["kpis"]["quantum_exposed"]
    rep = client.get("/api/report").json()
    assert rep["report"]["before"]["quantum_exposed"] == before["quantum_exposed"]
    assert any(c["directly_migrated"] for c in rep["report"]["changes"])
    pdf = client.get("/api/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-" and len(pdf.content) > 5000
    assert any(i["key"] == "agility" and i["score"] == 100 for i in client.get("/api/readiness").json()["items"])
    client.post("/api/migrations/reset")
    assert client.get("/api/overview").json()["now"]["quantum_exposed"] == before["quantum_exposed"]


def test_assistant(client):
    login(client, FIN_VIEWER)
    top = client.get("/api/plan").json()["queue"][0]["asset_id"]
    a = client.post("/api/assistant", json={"message": f"Why is {top} critical?"}).json()
    assert top in a["answer"] and a["references"] == [top]
    assert "Migrate these first" in client.post("/api/assistant", json={"message": "What should we migrate first?"}).json()["answer"]
    w = client.post("/api/assistant", json={"message": "What if we migrate the top 10?"}).json()["answer"]
    assert "top 10" in w and "→" in w
    assert "FIPS 203" in client.post("/api/assistant", json={"message": "what is ML-KEM?"}).json()["answer"]
    assert "could not find" in client.post("/api/assistant", json={"message": "Why is XYZ-ABC-999 risky?"}).json()["answer"]


def test_rediscovery_creates_alerts_and_slack_delivery(client):
    received = []

    class Hook(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    platform = client.app.state.platform
    platform.slack_prefix = "http://127.0.0.1"
    try:
        login(client, FIN)
        url = f"http://127.0.0.1:{srv.server_port}/hook"
        assert client.put("/api/settings", json={"alert_email": FIN, "slack_webhook": url,
                                                 "monitor_interval_hours": 24}).status_code == 200
        before = len(client.get("/api/alerts").json()["alerts"])
        assets_before = client.get("/api/overview").json()["now"]["total_assets"]
        assert client.post("/api/discovery/run", json={}).status_code == 200
        run = wait_for_run(client)
        assert run["status"] == "completed" and run["new_assets"] > 0
        assert client.get("/api/overview").json()["now"]["total_assets"] == assets_before + run["new_assets"]
        alerts = client.get("/api/alerts").json()
        assert len(alerts["alerts"]) - before == run["new_vulnerable"] > 0
        assert received and "quantum-vulnerable" in received[0]["text"]
        email = [d for d in alerts["deliveries"] if d["channel"] == "email"][0]
        assert email["status"] == "skipped" and "SMTP" in email["error"]
        assert client.post("/api/alerts/read-all").status_code == 200
        assert client.get("/api/overview").json()["unread_alerts"] == 0
    finally:
        platform.slack_prefix = "https://hooks.slack.com/"
        srv.shutdown()


def test_monitor_tick_runs_due_discovery(client):
    platform = client.app.state.platform
    login(client, HEALTH)
    tid = client.get("/api/auth/me").json()["tenant"]["id"]
    with platform.db.session(tid) as c:
        c.execute("UPDATE discovery_runs SET finished_at = '2020-01-01T00:00:00+00:00' WHERE tenant_id = ?", (tid,))
    started = platform.monitor_tick()
    assert tid in started
    run = wait_for_run(client)
    assert run["triggered_by"] == "monitor" and run["status"] == "completed"


def test_connections_page(client, monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent")
    login(client, FIN)
    data = client.get("/api/connections").json()
    assert set(data["providers"]) == {"public", "simulator", "aws", "azure", "gcp"}
    assert data["external_id"].startswith("qm-")
    r = client.post("/api/connections", json={"provider": "aws", "display_name": "Prod AWS",
                                              "config": {"role_arn": "arn:aws:iam::123456789012:role/QMigrateReadOnly",
                                                         "evil": "x"}}).json()
    assert r["status"] == "connected"
    t = client.post(f"/api/connections/{r['id']}/test").json()      # no AWS login on the test machine
    assert t["ok"] is False and "aws configure" in t["message"]
    run = client.post("/api/discovery/run", json={"connection_id": r["id"]}).json()
    assert run["run_id"]
    failed = wait_for_run(client)
    assert failed["status"] == "failed" and "Discovery failed" in failed["message"]
    conn = [c for c in client.get("/api/connections").json()["connections"] if c["id"] == r["id"]][0]
    assert "evil" not in conn["config"] and conn["config"]["external_id"] == data["external_id"]
    assert client.delete(f"/api/connections/{r['id']}").status_code == 200


def test_two_factor_login(client):
    login(client, FIN_ANALYST)
    setup = client.post("/api/auth/2fa/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    assert client.post("/api/auth/2fa/enable", json={"code": "000000"}).status_code == 400
    code = totp_code(setup["secret"], totp_now_step())
    assert client.post("/api/auth/2fa/enable", json={"code": code}).status_code == 200
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": FIN_ANALYST, "password": client.app_settings.demo_password})
    assert r.json() == {"mfa_required": True}
    assert client.get("/api/overview").status_code == 401
    assert client.post("/api/auth/login/2fa", json={"code": code}).status_code == 401, "a used code must not be replayed"
    nxt = totp_code(setup["secret"], totp_now_step() + 1)
    assert client.post("/api/auth/login/2fa", json={"code": nxt}).status_code == 200
    assert client.get("/api/auth/me").json()["user"]["totp_enabled"] is True
    with client.app.state.platform.db.session() as c:
        raw = c.one("SELECT totp_secret FROM users WHERE lower(email) = lower(?)", (FIN_ANALYST,)) if client.backend == "sqlite" else None
    if raw:
        assert setup["secret"] not in raw["totp_secret"], "TOTP secrets are stored encrypted"


def test_users_admin(client):
    login(client, FIN)
    r = client.post("/api/users", json={"email": "new.analyst@demofinance.example", "name": "New Analyst", "role": "analyst"})
    assert r.status_code == 200
    temp = r.json()["temporary_password"]
    users = client.get("/api/users").json()
    new = next(u for u in users if u["email"] == "new.analyst@demofinance.example")
    assert client.patch(f"/api/users/{new['id']}", json={"role": "viewer"}).status_code == 200
    me = client.get("/api/auth/me").json()["user"]
    assert client.patch(f"/api/users/{me['id']}", json={"role": "viewer"}).status_code == 400
    login(client, "new.analyst@demofinance.example", temp)
    assert client.get("/api/auth/me").json()["user"]["role"] == "viewer"
    assert client.post("/api/auth/password", json={"current": temp, "new": "short"}).status_code == 400
    assert client.post("/api/auth/password", json={"current": temp, "new": "BetterPassw0rd!"}).status_code == 200
    login(client, FIN)
    assert client.delete(f"/api/users/{new['id']}").status_code == 200


def test_signup_validation_and_gdpr_export_delete(client):
    client.cookies.clear()
    base = {"company": "Temp Co", "name": "Tia Temp", "email": "tia@tempco.example", "password": "TempPassw0rd!"}
    assert client.post("/api/auth/signup", json={**base, "consent": False}).status_code == 400
    assert client.post("/api/auth/signup", json={**base, "password": "weak", "consent": True}).status_code == 400
    assert client.post("/api/auth/signup", json={**base, "email": FIN, "consent": True}).status_code == 400
    r = client.post("/api/auth/signup", json={**base, "consent": True})
    assert r.status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["tenant"]["name"] == "Temp Co" and me["user"]["role"] == "admin"
    assert client.get("/api/overview").json()["has_data"] is False
    assert client.post("/api/discovery/run", json={}).status_code == 200
    assert wait_for_run(client)["status"] == "completed"
    assert client.get("/api/overview").json()["has_data"] is True
    exp = client.get("/api/gdpr/export")
    assert exp.status_code == 200 and "attachment" in exp.headers["content-disposition"]
    data = exp.json()
    assert data["company"]["name"] == "Temp Co" and data["assets"]
    assert all("password_hash" not in u and "totp_secret" not in u for u in data["users"])
    assert client.post("/api/gdpr/delete", json={"confirm": "wrong"}).status_code == 400
    assert client.post("/api/gdpr/delete", json={"confirm": "Temp Co"}).status_code == 200
    assert client.get("/api/overview").status_code == 401
    r = client.post("/api/auth/login", json={"email": "tia@tempco.example", "password": "TempPassw0rd!"})
    assert r.status_code == 401
    login(client, FIN)
    assert client.get("/api/overview").json()["has_data"] is True


def test_retrain_with_new_seed(client):
    login(client, FIN_ANALYST if False else FIN)
    m = client.post("/api/models/retrain", json={"seed": 7}).json()
    assert m["seed"] == 7 and len(m["models"]) == 5


def test_microsoft_login_placeholder(client):
    r = client.get("/api/auth/microsoft")
    assert r.status_code == 501 and "Microsoft" in r.json()["detail"]


def test_quantum_deadlines_and_explanations_api(client):
    login(client, FIN)
    d = client.get("/api/deadlines").json()
    assert d["scenario"] == "expected" and set(d["by_scenario"]) == {"cautious", "expected", "late"}
    assert d["items"] and all(i["status"] != "safe" for i in d["items"])
    assert d["by_scenario"]["cautious"]["counts"]["late"] >= d["by_scenario"]["late"]["counts"]["late"]
    assert client.get("/api/deadlines?scenario=nope").status_code == 400
    assets = client.get("/api/assets").json()
    assert all(a["why"].split()[0] in ("Low", "Medium", "High", "Critical") for a in assets)
    assert all("status" in a["deadline"] for a in assets)
    exposed = next(i["asset_id"] for i in d["items"] if i["finish_by"])
    x = client.get(f"/api/assets/{exposed}/explain").json()
    assert x["why"]["summary"] == x["reasons"][0] and x["why"]["ai_note"] == x["reasons"][1]
    assert x["deadline"]["sentence"].startswith("Quantum deadline") and x["deadline"]["sentence"] in x["reasons"]
    q = client.get("/api/plan").json()["queue"]
    assert all("deadline_status" in i for i in q)
    rep = client.get("/api/report").json()["report"]
    assert "counts" in rep["deadlines"]


def test_research_evaluation_runs_on_a_workspace(client):
    from qmigrate.research.evaluate import evaluate_estate, to_markdown
    login(client, FIN)
    est = client.app.state.platform.require_estate(client.get("/api/auth/me").json()["tenant"]["id"])
    res = evaluate_estate(est)
    assert res["explanations"]["faithfulness"]["explained_drop"] > res["explanations"]["faithfulness"]["random_drop"]
    assert "Quantum deadline versus the rule baseline" in to_markdown({"date": "t", "scenario": "expected",
                                                                       "workspaces": {"Finance": res}})
