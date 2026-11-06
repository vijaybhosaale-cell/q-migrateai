"""Test fixtures: one app per database backend (SQLite always, PostgreSQL when QM_TEST_PG is set).

QM_TEST_PG=postgresql://postgres@/postgres?host=/path/to/socket&port=5433  (a superuser URL)
The PostgreSQL tests create a fresh database, use the superuser only for the schema,
and connect the app as a non-superuser role so row-level security is really enforced.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")
# The API tests run offline on the synthetic simulator; real-data collection is tested in test_realdata.py.
os.environ.setdefault("ENABLE_SIMULATOR", "1")

from fastapi.testclient import TestClient  # noqa: E402

from qmigrate.config import Settings  # noqa: E402

DEMO_ASSETS = int(os.environ.get("QM_TEST_ASSETS", "160"))


def _pg_urls():
    base = os.environ.get("QM_TEST_PG")
    if not base:
        return None
    import psycopg
    name = "qm_test_" + uuid.uuid4().hex[:8]
    with psycopg.connect(base, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {name}")
        c.execute("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qm_app_test') THEN "
                  "CREATE ROLE qm_app_test LOGIN PASSWORD 'apppw'; END IF; END $$")
    admin = base.replace("/postgres?", f"/{name}?")
    app_url = admin.replace("postgres@", "qm_app_test:apppw@")
    return admin, app_url, name, base


def make_settings(tmp_path: Path, backend: str) -> tuple[Settings, callable]:
    s = Settings()
    s.secret_key = "test-secret-key-for-unit-tests-only"
    s.seed_demo = True
    s.demo_assets = DEMO_ASSETS
    s.monitor_enabled = False
    s.simulator_url = "inprocess"
    s.data_source = "simulator"
    s.serve_web = False
    s.smtp_host = ""
    cleanup = lambda: None  # noqa: E731
    if backend == "sqlite":
        s.database_url = f"sqlite:///{(tmp_path / 'qm.db').as_posix()}"
        s.database_admin_url = ""
    else:
        urls = _pg_urls()
        if urls is None:
            pytest.skip("set QM_TEST_PG to run PostgreSQL tests")
        admin, app_url, name, base = urls
        s.database_url, s.database_admin_url = app_url, admin

        def cleanup():
            import psycopg
            with psycopg.connect(base, autocommit=True) as c:
                c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    return s, cleanup


@pytest.fixture(scope="module", params=["sqlite", "postgres"])
def client(request, tmp_path_factory):
    from qmigrate.server.app import create_app
    settings, cleanup = make_settings(tmp_path_factory.mktemp(request.param), request.param)
    app = create_app(settings, seed_in_background=False)
    with TestClient(app, headers={"X-QM-Request": "1"}) as c:
        c.backend = request.param
        c.app_settings = settings
        yield c
    cleanup()


def login(client, email: str, password: str | None = None):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": email, "password": password or client.app_settings.demo_password})
    assert r.status_code == 200, r.text
    return r.json()
