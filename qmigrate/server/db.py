"""Database access for PostgreSQL (production) and SQLite (laptop demo).

Every tenant table carries tenant_id. In PostgreSQL, row-level security (RLS)
policies make the database itself refuse rows of another tenant: each
transaction sets `app.tenant_id`, and a policy compares it with the row.
SQLite has no RLS, so there isolation relies on the application's WHERE
clauses only (the same queries run in both).

SQL in this project is written once with `?` placeholders; they are turned
into `%s` for PostgreSQL. Do not use a literal `?` or `%` inside SQL text.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

log = logging.getLogger("qmigrate.db")

TENANT_TABLES = [
    "users", "tenant_settings", "cloud_connections", "discovery_runs", "assets", "dependencies",
    "model_runs", "migrations", "audit_log", "alerts", "notification_outbox", "config_checks",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    data_region TEXT NOT NULL DEFAULT 'EU',
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    totp_secret TEXT,
    totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    totp_last_step INTEGER NOT NULL DEFAULT 0,
    gdpr_consent_at TEXT,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_users_tenant ON users(tenant_id);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    mfa_pending BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT
);
CREATE TABLE IF NOT EXISTS tenant_settings (
    tenant_id TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    alert_email TEXT,
    slack_webhook TEXT,
    monitor_interval_hours INTEGER NOT NULL DEFAULT 24,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS cloud_connections (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    display_name TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_sync_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_conn_tenant ON cloud_connections(tenant_id);
CREATE TABLE IF NOT EXISTS discovery_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    connection_id TEXT,
    status TEXT NOT NULL,
    phase TEXT,
    triggered_by TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    assets_found INTEGER,
    new_assets INTEGER,
    new_vulnerable INTEGER,
    message TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_tenant ON discovery_runs(tenant_id, started_at);
CREATE TABLE IF NOT EXISTS assets (
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL,
    connection_id TEXT,
    cloud TEXT NOT NULL,
    region TEXT,
    application TEXT,
    owner_team TEXT,
    service_type TEXT NOT NULL,
    usage TEXT NOT NULL,
    protocol TEXT,
    algorithm_discovered TEXT NOT NULL,
    algorithm_current TEXT NOT NULL,
    exposure TEXT NOT NULL,
    data_sensitivity INTEGER NOT NULL,
    retention_years INTEGER NOT NULL,
    business_criticality INTEGER NOT NULL,
    clients_support_pqc BOOLEAN NOT NULL DEFAULT FALSE,
    analyst_label TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (tenant_id, asset_id)
);
CREATE TABLE IF NOT EXISTS dependencies (
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    relation TEXT NOT NULL,
    PRIMARY KEY (tenant_id, source, target)
);
CREATE TABLE IF NOT EXISTS model_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    seed INTEGER NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    metrics TEXT,
    positions TEXT,
    bundle {BLOB} NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_models_tenant ON model_runs(tenant_id);
CREATE TABLE IF NOT EXISTS migrations (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL,
    action TEXT NOT NULL,
    from_alg TEXT,
    to_alg TEXT,
    standard TEXT,
    wave TEXT,
    user_id TEXT,
    user_email TEXT,
    created_at TEXT NOT NULL,
    rule_before REAL,
    rule_after REAL,
    ai_before REAL,
    ai_after REAL,
    class_before TEXT,
    class_after TEXT,
    checks TEXT
);
CREATE INDEX IF NOT EXISTS ix_migr_tenant ON migrations(tenant_id, created_at);
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id TEXT,
    user_email TEXT,
    action TEXT NOT NULL,
    target TEXT,
    details TEXT,
    ip TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_tenant ON audit_log(tenant_id, created_at);
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    asset_id TEXT,
    created_at TEXT NOT NULL,
    read_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_alerts_tenant ON alerts(tenant_id, created_at);
CREATE TABLE IF NOT EXISTS config_checks (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_email TEXT,
    files TEXT NOT NULL,
    summary TEXT NOT NULL,
    findings TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cfg_tenant ON config_checks(tenant_id, created_at);
CREATE TABLE IF NOT EXISTS notification_outbox (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    target TEXT,
    subject TEXT,
    body TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);
"""

PG_SECURITY = """
CREATE OR REPLACE FUNCTION qm_user_by_email(p_email TEXT)
RETURNS TABLE (id TEXT, tenant_id TEXT, email TEXT, name TEXT, password_hash TEXT, role TEXT,
               totp_secret TEXT, totp_enabled BOOLEAN, totp_last_step INTEGER)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $fn$
  SELECT u.id, u.tenant_id, u.email, u.name, u.password_hash, u.role, u.totp_secret, u.totp_enabled, u.totp_last_step
  FROM users u WHERE lower(u.email) = lower(p_email)
$fn$;
"""

# Columns added after the first release. init_schema adds them to an existing database, so a laptop
# that already ran the demo keeps its data.
ADDED_COLUMNS = [
    ("assets", "evidence", "TEXT"),        # what discovery measured for this asset (JSON)
    ("assets", "corrections", "TEXT"),     # fields a user corrected: {field: {"value", "original", "by", "at"}}
    ("assets", "note", "TEXT"),            # free-text note from a user
    ("cloud_connections", "last_meta", "TEXT"),   # last discovery summary (websites reached / not reached)
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


class Conn:
    """A thin wrapper around one transaction, returning rows as dicts."""

    def __init__(self, raw, dialect: str):
        self.raw = raw
        self.dialect = dialect

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "postgres" else sql

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        cur = self.raw.execute(self._sql(sql), tuple(params))
        return cur.rowcount

    def executemany(self, sql: str, seq: list) -> None:
        if not seq:
            return
        if self.dialect == "postgres":
            with self.raw.cursor() as cur:
                cur.executemany(self._sql(sql), [tuple(p) for p in seq])
        else:
            self.raw.executemany(sql, [tuple(p) for p in seq])

    def all(self, sql: str, params: tuple | list = ()) -> list[dict]:
        cur = self.raw.execute(self._sql(sql), tuple(params))
        if cur.description is None:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: tuple | list = ()) -> Any:
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None


class Database:
    def __init__(self, url: str, admin_url: str = ""):
        self.url = url
        self.admin_url = admin_url
        if url.startswith("sqlite"):
            self.dialect = "sqlite"
            self.path = Path(url.split("sqlite:///", 1)[1])
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._lock = threading.RLock()
        elif url.startswith(("postgres://", "postgresql://")):
            self.dialect = "postgres"
            import psycopg  # noqa: F401  (fail early if missing)
        else:
            raise ValueError("DATABASE_URL must start with sqlite:/// or postgresql://")
        self.rls_enforced = False

    # ----------------------------------------------------------- connections
    def _connect(self, admin: bool = False):
        if self.dialect == "sqlite":
            raw = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            raw.execute("PRAGMA foreign_keys = ON")
            raw.execute("PRAGMA journal_mode = WAL")
            return raw
        import psycopg
        return psycopg.connect(self.admin_url if (admin and self.admin_url) else self.url)

    @contextmanager
    def session(self, tenant_id: str | None = None, admin: bool = False) -> Iterator[Conn]:
        """One transaction. With tenant_id, PostgreSQL RLS only shows that tenant's rows."""
        raw = self._connect(admin)
        try:
            conn = Conn(raw, self.dialect)
            if self.dialect == "postgres":
                conn.execute("SELECT set_config('app.tenant_id', ?, true)", (tenant_id or "",))
            yield conn
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            raw.close()

    # ---------------------------------------------------------------- schema
    def init_schema(self) -> None:
        blob = "BYTEA" if self.dialect == "postgres" else "BLOB"
        ddl = SCHEMA.replace("{BLOB}", blob)
        if self.dialect == "sqlite":
            raw = self._connect()
            try:
                raw.executescript(ddl)
                for table, col, kind in ADDED_COLUMNS:
                    have = {r[1] for r in raw.execute(f"PRAGMA table_info({table})").fetchall()}
                    if col not in have:
                        raw.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
                raw.commit()
            finally:
                raw.close()
            return
        import psycopg
        from psycopg import sql
        with psycopg.connect(self.admin_url or self.url, autocommit=True) as raw:
            for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
                raw.execute(stmt)
            for table, col, kind in ADDED_COLUMNS:
                raw.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {kind}")
            raw.execute(PG_SECURITY)
            for table in TENANT_TABLES:
                raw.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
                raw.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
                raw.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
                raw.execute(
                    f"CREATE POLICY tenant_isolation ON {table} "
                    f"USING (tenant_id = current_setting('app.tenant_id', true)) "
                    f"WITH CHECK (tenant_id = current_setting('app.tenant_id', true))")
            app_user = urlparse(self.url).username
            if self.admin_url and app_user:
                app_password = urlparse(self.url).password or ""
                exists = raw.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_user,)).fetchone()
                if not exists:
                    raw.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(app_user), sql.Literal(app_password)))
                raw.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(app_user)))
                raw.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(
                    sql.Identifier(app_user)))
                raw.execute(sql.SQL("GRANT EXECUTE ON FUNCTION qm_user_by_email(TEXT) TO {}").format(
                    sql.Identifier(app_user)))
        with psycopg.connect(self.url) as raw:
            row = raw.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user").fetchone()
            self.rls_enforced = not (row[0] or row[1])
        if not self.rls_enforced:
            log.warning("PostgreSQL row-level security is NOT enforced: the app connects as a superuser. "
                        "Set DATABASE_ADMIN_URL and a non-superuser DATABASE_URL (see .env.example).")

    # --------------------------------------------------------------- helpers
    def user_by_email(self, conn: Conn, email: str) -> dict | None:
        """Login lookup across tenants (in PostgreSQL via a SECURITY DEFINER function)."""
        if self.dialect == "postgres":
            return conn.one("SELECT * FROM qm_user_by_email(?)", (email,))
        return conn.one("SELECT id, tenant_id, email, name, password_hash, role, totp_secret, totp_enabled, "
                        "totp_last_step FROM users WHERE lower(email) = lower(?)", (email,))
