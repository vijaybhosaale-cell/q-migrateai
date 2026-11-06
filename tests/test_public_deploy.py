"""Settings for a public server: the demo password is not shown, and the simulated Demo Lab is optional."""
from __future__ import annotations

from types import SimpleNamespace

from qmigrate.server.seed import DEMO_LAB, _specs


def test_public_server_hides_the_demo_password(client):
    s = client.app_settings
    assert client.get("/api/public/config").json()["demo_password"]          # laptop default: shown
    s.show_demo_logins = False
    try:
        cfg = client.get("/api/public/config").json()
        assert cfg["demo_password"] is None and cfg["demo_accounts"] == []
    finally:
        s.show_demo_logins = True


def test_demo_lab_only_next_to_real_data():
    real = SimpleNamespace(demo_lab=True, data_source="public")
    assert DEMO_LAB in _specs(real)                      # tests run with ENABLE_SIMULATOR=1
    assert DEMO_LAB not in _specs(SimpleNamespace(demo_lab=True, data_source="simulator"))
    assert DEMO_LAB not in _specs(SimpleNamespace(demo_lab=False, data_source="public"))
