"""P7: a data path is only as quantum-safe as its weakest hop."""
from __future__ import annotations

import networkx as nx

from conftest import login
from qmigrate.engine import paths as P
from qmigrate.engine.graph import build_graph


def asset(i, alg, sens=4, ret=5, st="load_balancer"):
    return {"asset_id": i, "algorithm": alg, "data_sensitivity": sens, "retention_years": ret, "service_type": st,
            "usage": "key_exchange"}


def tiny():
    """lb -> gw -> db -> (backup), db uses key. The load balancer is already hybrid."""
    assets = [asset("lb", "X25519+ML-KEM-768"), asset("gw", "ECDHE-P256", st="api_gateway"),
              asset("db", "AES-256", sens=5, ret=10, st="database"), asset("key", "RSA-2048", st="kms_key"),
              asset("bkp", "AES-256", st="backup_vault")]
    edges = [{"source": "lb", "target": "gw", "relation": "routes_to"},
             {"source": "gw", "target": "db", "relation": "calls"},
             {"source": "db", "target": "key", "relation": "uses_key"},
             {"source": "bkp", "target": "db", "relation": "backs_up"}]
    state = {a["asset_id"]: a for a in assets}
    return P.PathModel(build_graph(assets, edges), state), state


def test_flow_graph_follows_the_data():
    m, _ = tiny()
    assert set(m.flow.edges) == {("lb", "gw"), ("gw", "db"), ("db", "bkp")}      # backup reversed, key not a hop
    assert m.paths == [["lb", "gw", "db", "bkp"]]


def test_weakest_hop_and_false_assurance():
    m, _ = tiny()
    ev = m.evaluate()
    assert ev["safe_paths"] == 0 and ev["harvestable_paths"] == 1
    assert "lb" in ev["false_assurance"]                 # hybrid on its own, but the path is readable later
    assert m.weakest_hop(m.paths[0], ev["_hs"]) in ("gw", "db")


def test_requirements_include_the_key_behind_a_hop():
    m, _ = tiny()
    ev = m.evaluate()
    assert m.requirements(m.paths[0], ev["_hs"]) == {"gw", "key"}   # db is AES-256 but relies on the RSA key


def test_path_first_closes_the_path_within_budget():
    m, state = tiny()
    plan = m.plan_path_first(2)
    assert {x["asset_id"] for x in plan} == {"gw", "key"}
    after = m.evaluate(m.apply({x["asset_id"]: x["target"] for x in plan}))
    assert after["safe_paths"] == 1 and after["false_assurance"] == []
    assert m.plan_path_first(1) == []                    # one migration cannot close it


def test_cycles_do_not_loop_forever():
    f = nx.DiGraph([("a", "b"), ("b", "c"), ("c", "b")])
    paths, _ = P.enumerate_paths(f)
    assert paths and all(len(p) == len(set(p)) for p in paths)


def test_hop_model_matches_the_platform_flag(client):
    """The cheap hop model must agree with the estate's own quantum-safe flag on every asset."""
    login(client, "analyst@demofinance.example")
    rows = {a["asset_id"]: a for a in client.get("/api/assets").json()}
    r = client.get("/api/paths").json()
    assert r["has_paths"] and r["now"]["paths"] > 10
    for p in r["paths"][:50]:
        for h in p["hops"]:
            assert h["safe"] == rows[h["asset_id"]]["quantum_safe"]
    w1 = next(c for c in r["comparison"] if c["budget"] == r["wave1_size"])
    assert w1["path_first"]["safe_paths"] >= w1["per_asset"]["safe_paths"]
    assert len(r["path_first_wave"]) <= r["wave1_size"]


def test_viewer_can_read_paths_and_each_company_sees_its_own(client):
    login(client, "viewer@demofinance.example")
    fin = client.get("/api/paths")
    assert fin.status_code == 200
    login(client, "admin@demohealth.example")
    health = client.get("/api/paths").json()
    fin = fin.json()
    assert (fin["now"], fin["paths"][0]["hops"]) != (health["now"], health["paths"][0]["hops"])


def test_pdf_report_has_the_paths_section(client):
    import io
    login(client, "analyst@demofinance.example")
    r = client.get("/api/report.pdf")
    assert r.status_code == 200
    try:
        from pypdf import PdfReader
    except ImportError:
        return
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "safe end to end" in text
