"""Settings, read once from environment variables (and an optional .env file).

Local demo (Windows laptop): nothing to set; SQLite is used and the simulator
runs in-process. Production (Docker Compose on a server): see .env.example.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("QM_DATA_DIR", ROOT / "data"))


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(ROOT / ".env")


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _secret_key() -> str:
    key = os.environ.get("SECRET_KEY", "").strip()
    if key:
        return key
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "secret.key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


class Settings:
    def __init__(self) -> None:
        self.database_url = os.environ.get("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'qmigrate.db').as_posix()}")
        # Optional: a PostgreSQL superuser URL used only to create the schema, the app role
        # and the row-level-security policies. When set, the app itself connects with
        # DATABASE_URL as a non-superuser, so PostgreSQL enforces tenant isolation.
        self.database_admin_url = os.environ.get("DATABASE_ADMIN_URL", "")
        self.simulator_url = os.environ.get("SIMULATOR_URL", "inprocess").rstrip("/")
        # "public" = real data from public websites (default); "simulator" = synthetic estates (needs ENABLE_SIMULATOR=1)
        self.data_source = os.environ.get("DATA_SOURCE", "public").strip().lower()
        self.secret_key = _secret_key()
        self.cookie_secure = _flag("COOKIE_SECURE", "0")
        # Only behind a reverse proxy we control (Caddy in Docker Compose) is X-Forwarded-For trusted.
        self.trust_proxy = _flag("TRUST_PROXY", "0")
        self.session_hours = int(os.environ.get("SESSION_HOURS", "12"))
        self.allow_signup = _flag("ALLOW_SIGNUP", "1")
        self.seed_demo = _flag("SEED_DEMO", "1")
        # A third demo company on the synthetic simulator ("Demo Lab"), for the pages that need data-flow links
        # (Data paths) next to the real-data companies. Needs ENABLE_SIMULATOR=1.
        self.demo_lab = _flag("DEMO_LAB", "0")
        # Show the demo logins and their password on the login page (laptop demo). Turn off on a public server:
        # the demo accounts still exist, but only people you give the password to can use them.
        self.show_demo_logins = _flag("SHOW_DEMO_LOGINS", "1")
        self.demo_password = os.environ.get("DEMO_PASSWORD", "QuantumDemo!2026")
        self.demo_assets = int(os.environ.get("DEMO_ASSETS", "400"))
        self.public_sites = int(os.environ.get("PUBLIC_SITES", "45"))   # websites per company for real data
        self.monitor_enabled = _flag("MONITOR_ENABLED", "1")
        self.monitor_check_minutes = int(os.environ.get("MONITOR_CHECK_MINUTES", "10"))
        self.smtp_host = os.environ.get("SMTP_HOST", "")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = os.environ.get("SMTP_USER", "")
        self.smtp_password = os.environ.get("SMTP_PASSWORD", "")
        self.smtp_from = os.environ.get("SMTP_FROM", "alerts@qmigrate.local")
        self.smtp_starttls = _flag("SMTP_STARTTLS", "1")
        # Render sets RENDER_EXTERNAL_URL to the service's public address.
        self.public_url = (os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
                           or "http://localhost:8002").rstrip("/")
        self.web_dir = Path(os.environ.get("WEB_DIR", ROOT / "web" / "dist"))
        self.serve_web = _flag("SERVE_WEB", "1")
        self.privacy_contact = os.environ.get("PRIVACY_CONTACT", "privacy@awhlle.com")


settings = Settings()
