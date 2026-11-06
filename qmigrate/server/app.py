"""Q-MigrateAI platform API (FastAPI). Run: uvicorn qmigrate.server.app:app --port 8002"""
from __future__ import annotations

import json
import logging
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from qmigrate.config import Settings, settings as default_settings
from qmigrate.engine import assistant
from qmigrate.engine.catalog import ALGORITHMS, CLASSICAL_FACTS, PQC_FACTS
from qmigrate.engine.estate import clean
from qmigrate.server import project_data, report_pdf
from qmigrate.server.connectors.clouds import PROVIDERS, make_connector
from qmigrate.server.db import Database, new_id, now_iso
from qmigrate.server.security import (hash_password, new_token, otpauth_uri, password_problem, temporary_password,
                                      token_hash, totp_new_secret, totp_verify, verify_password)
from qmigrate.server.seed import seed_demo
from qmigrate.server.services import PERMISSIONS, ROLES, Invalid, NotFound, Platform

log = logging.getLogger("qmigrate")
VERSION = "2.0.0"
SESSION_COOKIE, MFA_COOKIE = "qm_session", "qm_mfa"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ------------------------------------------------------------------ bodies
class SignupBody(BaseModel):
    company: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)
    consent: bool = False


class LoginBody(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


class CodeBody(BaseModel):
    code: str = Field(max_length=12)


class PasswordBody(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class UserBody(BaseModel):
    email: str = Field(max_length=200)
    name: str = Field(min_length=2, max_length=120)
    role: str


class RoleBody(BaseModel):
    role: str


class SettingsBody(BaseModel):
    alert_email: Optional[str] = Field(default=None, max_length=200)
    slack_webhook: Optional[str] = Field(default=None, max_length=500)
    monitor_interval_hours: int = Field(default=24, ge=0, le=720)


class ConnectionBody(BaseModel):
    provider: str
    display_name: str = Field(min_length=2, max_length=80)
    config: dict = {}


class RunBody(BaseModel):
    connection_id: Optional[str] = None


class LabBody(BaseModel):
    asset_id: str = Field(max_length=40)
    target: str = Field(default="", max_length=40)


class WaveBody(BaseModel):
    wave: str = "Wave 1"


class SeedBody(BaseModel):
    seed: int = Field(default=42, ge=1, le=99999)


class AskBody(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class CorrectionBody(BaseModel):
    changes: dict = {}
    note: Optional[str] = Field(default=None, max_length=1000)
    revert: list[str] = []


class DeleteBody(BaseModel):
    confirm: str = Field(max_length=200)


# ---------------------------------------------------------------- factory
def create_app(settings: Settings | None = None, *, seed_in_background: bool = True) -> FastAPI:
    s = settings or default_settings
    db = Database(s.database_url, s.database_admin_url)
    platform = Platform(s, db)

    seed_state = {"status": "on" if s.seed_demo else "off"}

    def run_seed() -> None:
        seed_state["status"] = "running"
        try:
            seed_demo(platform)
            seed_state["status"] = "ready"
        except Exception:  # noqa: BLE001
            log.exception("demo seeding failed")
            seed_state["status"] = "failed"

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        placeholders = [name for name, value in (("SECRET_KEY", s.secret_key), ("DATABASE_URL", s.database_url),
                                                  ("DATABASE_ADMIN_URL", s.database_admin_url), ("DEMO_PASSWORD", s.demo_password))
                        if "change-me" in value]
        if placeholders:
            raise RuntimeError("Edit .env first: replace the change-me values of " + ", ".join(placeholders))
        db.init_schema()
        if s.seed_demo:
            if seed_in_background:
                threading.Thread(target=run_seed, daemon=True).start()
            else:
                run_seed()
        platform.start_monitor()
        yield
        platform.stop()

    app = FastAPI(title="Q-MigrateAI Platform API", version=VERSION, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.platform = platform

    # ------------------------------------------------------- middleware
    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("x-qm-request") != "1":
                return JSONResponse({"detail": "Missing X-QM-Request header (CSRF protection)."}, status_code=403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(NotFound)
    async def _nf(_r, exc):
        return JSONResponse({"detail": str(exc) or "Not found."}, status_code=404)

    @app.exception_handler(Invalid)
    async def _inv(_r, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # ------------------------------------------------------- auth helpers
    def client_ip(request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for", "") if s.trust_proxy else ""
        return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")

    def set_cookie(response: Response, name: str, token: str, max_age: int) -> None:
        response.set_cookie(name, token, max_age=max_age, httponly=True, samesite="strict",
                            secure=s.cookie_secure, path="/")

    def open_session(response: Response, request: Request, user: dict, *, mfa_pending: bool = False) -> None:
        token, h = new_token()
        minutes = 5 if mfa_pending else s.session_hours * 60
        expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        with db.session(user["tenant_id"]) as c:
            c.execute("INSERT INTO sessions (token_hash, user_id, tenant_id, mfa_pending, created_at, expires_at, ip, user_agent) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (h, user["id"], user["tenant_id"], mfa_pending, now_iso(), expires.isoformat(timespec="seconds"),
                       client_ip(request), (request.headers.get("user-agent") or "")[:200]))
            if not mfa_pending:
                c.execute("UPDATE users SET last_login_at = ? WHERE tenant_id = ? AND id = ?",
                          (now_iso(), user["tenant_id"], user["id"]))
                platform.audit(c, user["tenant_id"], user, "user.login", user["email"], {}, client_ip(request))
        set_cookie(response, MFA_COOKIE if mfa_pending else SESSION_COOKIE, token, minutes * 60)

    def load_session(token: str | None, *, mfa: bool) -> dict | None:
        if not token:
            return None
        with db.session() as c:
            row = c.one("SELECT * FROM sessions WHERE token_hash = ?", (token_hash(token),))
        if not row or bool(row["mfa_pending"]) != mfa:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            with db.session() as c:
                c.execute("DELETE FROM sessions WHERE token_hash = ?", (row["token_hash"],))
            return None
        return row

    def current(request: Request) -> dict:
        sess = load_session(request.cookies.get(SESSION_COOKIE), mfa=False)
        if not sess:
            raise HTTPException(401, "Please log in.")
        with db.session(sess["tenant_id"]) as c:
            user = c.one("SELECT id, tenant_id, email, name, role, totp_enabled, must_change_password FROM users "
                         "WHERE tenant_id = ? AND id = ?", (sess["tenant_id"], sess["user_id"]))
        if not user:
            raise HTTPException(401, "Please log in.")
        user["totp_enabled"] = bool(user["totp_enabled"])
        return {"user": user, "tid": user["tenant_id"], "role": user["role"],
                "perms": PERMISSIONS[user["role"]], "ip": client_ip(request), "session": sess["token_hash"]}

    def need(perm: str):
        def dep(ctx: dict = Depends(current)) -> dict:
            if perm not in ctx["perms"]:
                raise HTTPException(403, f"Your role ({ctx['role']}) cannot do this.")
            return ctx
        return dep

    def me_payload(ctx: dict) -> dict:
        tenant = platform.tenant(ctx["tid"])
        return {"user": ctx["user"], "tenant": {"id": tenant["id"], "name": tenant["name"], "is_demo": tenant["is_demo"],
                                                 "data_region": tenant["data_region"]},
                "permissions": sorted(ctx["perms"]), "roles": ROLES}

    # ============================================================ public
    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": VERSION, "database": db.dialect, "rls_enforced": db.rls_enforced,
                "demo_data": seed_state["status"]}

    @app.get("/api/public/config")
    def public_config():
        demo = []
        if s.seed_demo:
            demo = [{"company": "Demo Finance Co.", "logins": ["admin@demofinance.example", "ciso@demofinance.example",
                                                                "analyst@demofinance.example", "viewer@demofinance.example"]},
                    {"company": "Demo Health Group", "logins": ["admin@demohealth.example", "ciso@demohealth.example"]}]
        return {"allow_signup": s.allow_signup, "privacy_contact": s.privacy_contact, "demo_accounts": demo,
                "demo_password": s.demo_password if s.seed_demo else None, "version": VERSION}

    # ============================================================== auth
    @app.post("/api/auth/signup")
    def signup(body: SignupBody, request: Request, response: Response):
        if not s.allow_signup:
            raise HTTPException(403, "Sign-up is disabled on this server.")
        if not body.consent:
            raise Invalid("Please accept the privacy notice (GDPR consent) to create an account.")
        if not EMAIL_RE.match(body.email):
            raise Invalid("Please enter a valid e-mail address.")
        problem = password_problem(body.password)
        if problem:
            raise Invalid(problem)
        key = "signup:" + client_ip(request)
        if platform.rate.blocked(key):
            raise HTTPException(429, "Too many sign-ups from this address. Try again later.")
        platform.rate.fail(key)
        tenant, user = platform.create_tenant(body.company, body.email, body.name, body.password, consent=True)
        with db.session(tenant["id"]) as c:
            full = c.one("SELECT * FROM users WHERE tenant_id = ? AND id = ?", (tenant["id"], user["id"]))
        open_session(response, request, full)
        return {"ok": True, "tenant": tenant}

    @app.post("/api/auth/login")
    def login(body: LoginBody, request: Request, response: Response):
        email = body.email.strip().lower()
        keys = ["ip:" + client_ip(request), "email:" + email]
        # 8 failures per account, 40 per address (an office or a demo laptop shares one address).
        if platform.rate.blocked(keys[1]) or platform.rate.blocked(keys[0], limit=40):
            raise HTTPException(429, "Too many failed attempts. Wait 15 minutes and try again.")
        with db.session() as c:
            user = db.user_by_email(c, email)
        if not user or not verify_password(body.password, user["password_hash"]):
            for k in keys:
                platform.rate.fail(k)
            raise HTTPException(401, "E-mail or password is incorrect.")
        platform.rate.reset("email:" + email)
        if bool(user["totp_enabled"]):
            open_session(response, request, user, mfa_pending=True)
            return {"mfa_required": True}
        open_session(response, request, user)
        return {"mfa_required": False}

    @app.post("/api/auth/login/2fa")
    def login_2fa(body: CodeBody, request: Request, response: Response):
        token = request.cookies.get(MFA_COOKIE)
        sess = load_session(token, mfa=True)
        if not sess:
            raise HTTPException(401, "Your login step expired. Please enter your password again.")
        key = "mfa:" + sess["token_hash"]
        if platform.rate.blocked(key):
            raise HTTPException(429, "Too many wrong codes. Please log in again.")
        with db.session(sess["tenant_id"]) as c:
            user = c.one("SELECT * FROM users WHERE tenant_id = ? AND id = ?", (sess["tenant_id"], sess["user_id"]))
        secret = platform.box.open(user["totp_secret"] or "") if user else None
        step = totp_verify(secret, body.code, int(user["totp_last_step"] or 0)) if secret else None
        if step is None:
            platform.rate.fail(key)
            raise HTTPException(401, "That code is not valid. Use the current 6-digit code from your authenticator app.")
        with db.session(sess["tenant_id"]) as c:
            c.execute("UPDATE users SET totp_last_step = ? WHERE tenant_id = ? AND id = ?", (step, user["tenant_id"], user["id"]))
        with db.session() as c:
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (sess["token_hash"],))
        response.delete_cookie(MFA_COOKIE, path="/")
        open_session(response, request, user)
        return {"ok": True}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            with db.session() as c:
                c.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(ctx: dict = Depends(current)):
        return me_payload(ctx)

    @app.get("/api/auth/microsoft")
    def microsoft_login():
        raise HTTPException(501, "Login with Microsoft (Entra ID, OpenID Connect) is planned but not configured in this "
                                 "version. Use e-mail and password with two-factor authentication.")

    @app.post("/api/auth/2fa/setup")
    def twofa_setup(ctx: dict = Depends(current)):
        secret = totp_new_secret()
        with db.session(ctx["tid"]) as c:
            c.execute("UPDATE users SET totp_secret = ?, totp_enabled = ? WHERE tenant_id = ? AND id = ?",
                      (platform.box.seal(secret), False, ctx["tid"], ctx["user"]["id"]))
        return {"secret": secret, "otpauth_uri": otpauth_uri(secret, ctx["user"]["email"])}

    @app.post("/api/auth/2fa/enable")
    def twofa_enable(body: CodeBody, ctx: dict = Depends(current)):
        with db.session(ctx["tid"]) as c:
            u = c.one("SELECT totp_secret, totp_last_step FROM users WHERE tenant_id = ? AND id = ?",
                      (ctx["tid"], ctx["user"]["id"]))
            secret = platform.box.open(u["totp_secret"] or "") if u else None
            step = totp_verify(secret, body.code, int(u["totp_last_step"] or 0)) if secret else None
            if step is None:
                raise Invalid("That code is not valid. Check the time on your phone and try the current code.")
            c.execute("UPDATE users SET totp_enabled = ?, totp_last_step = ? WHERE tenant_id = ? AND id = ?",
                      (True, step, ctx["tid"], ctx["user"]["id"]))
            platform.audit(c, ctx["tid"], ctx["user"], "user.2fa_enabled", ctx["user"]["email"], {}, ctx["ip"])
        return {"ok": True}

    @app.post("/api/auth/2fa/disable")
    def twofa_disable(body: CodeBody, ctx: dict = Depends(current)):
        with db.session(ctx["tid"]) as c:
            u = c.one("SELECT totp_secret, totp_last_step FROM users WHERE tenant_id = ? AND id = ?",
                      (ctx["tid"], ctx["user"]["id"]))
            secret = platform.box.open(u["totp_secret"] or "") if u and u["totp_secret"] else None
            if not secret or totp_verify(secret, body.code, int(u["totp_last_step"] or 0)) is None:
                raise Invalid("That code is not valid.")
            c.execute("UPDATE users SET totp_enabled = ?, totp_secret = NULL WHERE tenant_id = ? AND id = ?",
                      (False, ctx["tid"], ctx["user"]["id"]))
            platform.audit(c, ctx["tid"], ctx["user"], "user.2fa_disabled", ctx["user"]["email"], {}, ctx["ip"])
        return {"ok": True}

    @app.post("/api/auth/password")
    def change_password(body: PasswordBody, ctx: dict = Depends(current)):
        with db.session(ctx["tid"]) as c:
            u = c.one("SELECT password_hash FROM users WHERE tenant_id = ? AND id = ?", (ctx["tid"], ctx["user"]["id"]))
            if not verify_password(body.current, u["password_hash"]):
                raise Invalid("Your current password is incorrect.")
            problem = password_problem(body.new)
            if problem:
                raise Invalid(problem)
            c.execute("UPDATE users SET password_hash = ?, must_change_password = ? WHERE tenant_id = ? AND id = ?",
                      (hash_password(body.new), False, ctx["tid"], ctx["user"]["id"]))
            c.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?", (ctx["user"]["id"], ctx["session"]))
            platform.audit(c, ctx["tid"], ctx["user"], "user.password_changed", ctx["user"]["email"], {}, ctx["ip"])
        return {"ok": True}

    # ============================================================= users
    @app.get("/api/users")
    def list_users(ctx: dict = Depends(need("users"))):
        with db.session(ctx["tid"]) as c:
            rows = c.all("SELECT id, email, name, role, totp_enabled, created_at, last_login_at FROM users "
                         "WHERE tenant_id = ? ORDER BY created_at", (ctx["tid"],))
        for r in rows:
            r["totp_enabled"] = bool(r["totp_enabled"])
        return rows

    @app.post("/api/users")
    def add_user(body: UserBody, ctx: dict = Depends(need("users"))):
        if body.role not in ROLES:
            raise Invalid("Unknown role.")
        if not EMAIL_RE.match(body.email):
            raise Invalid("Please enter a valid e-mail address.")
        with db.session() as c:
            if db.user_by_email(c, body.email):
                raise Invalid("A user with this e-mail already exists.")
        temp = temporary_password()
        uid = new_id()
        with db.session(ctx["tid"]) as c:
            c.execute("INSERT INTO users (id, tenant_id, email, name, password_hash, role, must_change_password, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (uid, ctx["tid"], body.email.strip().lower(), body.name.strip(), hash_password(temp), body.role,
                       True, now_iso()))
            platform.audit(c, ctx["tid"], ctx["user"], "user.created", body.email, {"role": body.role}, ctx["ip"])
        return {"id": uid, "temporary_password": temp}

    @app.patch("/api/users/{uid}")
    def set_role(uid: str, body: RoleBody, ctx: dict = Depends(need("users"))):
        if body.role not in ROLES:
            raise Invalid("Unknown role.")
        if uid == ctx["user"]["id"] and body.role != "admin":
            raise Invalid("You cannot remove your own admin role.")
        with db.session(ctx["tid"]) as c:
            if not c.execute("UPDATE users SET role = ? WHERE tenant_id = ? AND id = ?", (body.role, ctx["tid"], uid)):
                raise NotFound("User not found.")
            platform.audit(c, ctx["tid"], ctx["user"], "user.role_changed", uid, {"role": body.role}, ctx["ip"])
        return {"ok": True}

    @app.delete("/api/users/{uid}")
    def remove_user(uid: str, ctx: dict = Depends(need("users"))):
        if uid == ctx["user"]["id"]:
            raise Invalid("You cannot delete yourself.")
        with db.session(ctx["tid"]) as c:
            row = c.one("SELECT email FROM users WHERE tenant_id = ? AND id = ?", (ctx["tid"], uid))
            if not row:
                raise NotFound("User not found.")
            c.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
            c.execute("DELETE FROM users WHERE tenant_id = ? AND id = ?", (ctx["tid"], uid))
            platform.audit(c, ctx["tid"], ctx["user"], "user.deleted", row["email"], {}, ctx["ip"])
        return {"ok": True}

    # ========================================================== settings
    @app.get("/api/settings")
    def get_settings(ctx: dict = Depends(need("read"))):
        with db.session(ctx["tid"]) as c:
            st = c.one("SELECT alert_email, slack_webhook, monitor_interval_hours FROM tenant_settings WHERE tenant_id = ?",
                       (ctx["tid"],)) or {}
        st["smtp_configured"] = bool(s.smtp_host)
        return st

    @app.put("/api/settings")
    def put_settings(body: SettingsBody, ctx: dict = Depends(need("alerts"))):
        if body.alert_email and not EMAIL_RE.match(body.alert_email):
            raise Invalid("Please enter a valid alert e-mail address.")
        if body.slack_webhook and not body.slack_webhook.startswith(platform.slack_prefix):
            raise Invalid(f"Slack webhook URLs start with {platform.slack_prefix}")
        with db.session(ctx["tid"]) as c:
            c.execute("UPDATE tenant_settings SET alert_email = ?, slack_webhook = ?, monitor_interval_hours = ?, updated_at = ? "
                      "WHERE tenant_id = ?", (body.alert_email or None, body.slack_webhook or None,
                                              body.monitor_interval_hours, now_iso(), ctx["tid"]))
            platform.audit(c, ctx["tid"], ctx["user"], "settings.updated", "alerts and monitoring",
                           {"monitor_interval_hours": body.monitor_interval_hours}, ctx["ip"])
        return {"ok": True}

    @app.post("/api/settings/test-alert")
    def test_alert(ctx: dict = Depends(need("alerts"))):
        with db.session(ctx["tid"]) as c:
            platform.create_alert(c, ctx["tid"], "info", "Test alert",
                                  f"This is a test alert sent by {ctx['user']['email']}.")
        return {"deliveries": platform.deliver_pending(ctx["tid"])}

    # ======================================================= connections
    @app.get("/api/connections")
    def connections(ctx: dict = Depends(need("read"))):
        with db.session(ctx["tid"]) as c:
            rows = c.all("SELECT id, provider, display_name, config, status, created_at, last_sync_at FROM cloud_connections "
                         "WHERE tenant_id = ? ORDER BY created_at", (ctx["tid"],))
        for r in rows:
            r["config"] = json.loads(r["config"] or "{}")
        return {"connections": rows, "providers": PROVIDERS, "external_id": "qm-" + ctx["tid"][:16]}

    @app.post("/api/connections")
    def add_connection(body: ConnectionBody, ctx: dict = Depends(need("connections"))):
        if body.provider not in PROVIDERS:
            raise Invalid("Unknown provider.")
        allowed = {f["key"] for f in PROVIDERS[body.provider]["fields"]}
        config = {k: v for k, v in body.config.items() if k in allowed and isinstance(v, (str, int, float, bool))}
        if body.provider == "aws":
            config["external_id"] = "qm-" + ctx["tid"][:16]
        if body.provider == "public":
            config.setdefault("source", "custom" if config.get("domains") else "finance")
            if config["source"] not in ("finance", "health", "tranco", "custom"):
                raise Invalid("Unknown website list.")
            config["top"] = max(5, min(int(config.get("top") or 45), 300))
            config["domains"] = str(config.get("domains", ""))[:5000]
            if config["source"] == "custom" and not config["domains"].strip():
                raise Invalid("Type at least one domain for a custom list.")
        if body.provider == "simulator":
            config.setdefault("profile", "generic")
            if config["profile"] not in ("generic", "bank", "hospital"):
                raise Invalid("Unknown simulator profile.")
            config["seed"] = int(config.get("seed") or 42)
            config["assets"] = max(60, min(int(config.get("assets") or 400), 1200))
            config["simulate_changes"] = True
        status = "connected"
        cid = new_id()
        with db.session(ctx["tid"]) as c:
            c.execute("INSERT INTO cloud_connections (id, tenant_id, provider, display_name, config, status, created_at) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?)", (cid, ctx["tid"], body.provider, body.display_name.strip(),
                                                       json.dumps(config), status, now_iso()))
            platform.audit(c, ctx["tid"], ctx["user"], "connection.created", body.display_name,
                           {"provider": body.provider}, ctx["ip"])
        return {"id": cid, "status": status}

    @app.post("/api/connections/{cid}/test")
    def test_connection(cid: str, ctx: dict = Depends(need("connections"))):
        with db.session(ctx["tid"]) as c:
            row = c.one("SELECT * FROM cloud_connections WHERE tenant_id = ? AND id = ?", (ctx["tid"], cid))
        if not row:
            raise NotFound("Connection not found.")
        return make_connector(row["provider"], json.loads(row["config"] or "{}"), s.simulator_url).test()

    @app.delete("/api/connections/{cid}")
    def delete_connection(cid: str, ctx: dict = Depends(need("connections"))):
        with db.session(ctx["tid"]) as c:
            row = c.one("SELECT display_name FROM cloud_connections WHERE tenant_id = ? AND id = ?", (ctx["tid"], cid))
            if not row:
                raise NotFound("Connection not found.")
            c.execute("DELETE FROM cloud_connections WHERE tenant_id = ? AND id = ?", (ctx["tid"], cid))
            platform.audit(c, ctx["tid"], ctx["user"], "connection.deleted", row["display_name"], {}, ctx["ip"])
        return {"ok": True}

    # ========================================================= discovery
    @app.post("/api/discovery/run")
    def run_discovery(body: RunBody, ctx: dict = Depends(need("discover"))):
        run_id = platform.start_discovery(ctx["tid"], ctx["user"], body.connection_id)
        return {"run_id": run_id}

    @app.get("/api/discovery/runs")
    def discovery_runs(ctx: dict = Depends(need("read"))):
        with db.session(ctx["tid"]) as c:
            return c.all("SELECT r.*, c.display_name AS connection FROM discovery_runs r LEFT JOIN cloud_connections c "
                         "ON c.id = r.connection_id AND c.tenant_id = r.tenant_id WHERE r.tenant_id = ? "
                         "ORDER BY r.started_at DESC LIMIT 20", (ctx["tid"],))

    # ============================================================== data
    @app.get("/api/overview")
    def overview(ctx: dict = Depends(need("read"))):
        tid = ctx["tid"]
        last = platform.last_discovery(tid)
        with db.session(tid) as c:
            unread = int(c.scalar("SELECT COUNT(*) AS n FROM alerts WHERE tenant_id = ? AND read_at IS NULL", (tid,)) or 0)
        est = platform.estate(tid)
        if est is None:
            return {"has_data": False, "last_discovery": last, "unread_alerts": unread}
        ov = est.overview()
        return {"has_data": True, **ov, "readiness": platform.readiness(tid), "top_queue": est.queue()[:5],
                "last_discovery": last, "unread_alerts": unread}

    @app.get("/api/assets")
    def assets(ctx: dict = Depends(need("read"))):
        return platform.require_estate(ctx["tid"]).assets()

    @app.get("/api/assets/{asset_id}/explain")
    def explain(asset_id: str, ctx: dict = Depends(need("read"))):
        est = platform.require_estate(ctx["tid"])
        if asset_id not in est.current:
            raise NotFound("Unknown asset.")
        return est.explain(asset_id)

    @app.get("/api/graph")
    def graph(ctx: dict = Depends(need("read"))):
        return platform.require_estate(ctx["tid"]).graph_data()

    @app.get("/api/graph/dependents/{asset_id}")
    def dependents(asset_id: str, ctx: dict = Depends(need("read"))):
        est = platform.require_estate(ctx["tid"])
        if asset_id not in est.current:
            raise NotFound("Unknown asset.")
        return est.dependents(asset_id)

    @app.get("/api/models")
    def models(ctx: dict = Depends(need("read"))):
        return platform.require_estate(ctx["tid"]).models_summary()

    @app.post("/api/models/retrain")
    def retrain(body: SeedBody, ctx: dict = Depends(need("discover"))):
        platform.require_estate(ctx["tid"])
        platform.retrain(ctx["tid"], ctx["user"], body.seed)
        return platform.require_estate(ctx["tid"]).models_summary()

    @app.get("/api/plan")
    def plan(ctx: dict = Depends(need("read"))):
        return platform.require_estate(ctx["tid"]).plan()

    @app.get("/api/whatif")
    def whatif(max_n: int = 60, ctx: dict = Depends(need("read"))):
        return platform.require_estate(ctx["tid"]).whatif_curve(max(1, min(max_n, 150)))

    @app.get("/api/deadlines")
    def deadlines(scenario: str = "expected", ctx: dict = Depends(need("read"))):
        from qmigrate.engine.deadline import SCENARIOS
        if scenario not in SCENARIOS:
            raise Invalid(f"Unknown scenario. Use one of: {', '.join(SCENARIOS)}.")
        return platform.require_estate(ctx["tid"]).deadline_overview(scenario)

    @app.get("/api/readiness")
    def readiness(ctx: dict = Depends(need("read"))):
        return platform.readiness(ctx["tid"])

    @app.get("/api/lab/{asset_id}")
    def lab_asset(asset_id: str, ctx: dict = Depends(need("read"))):
        est = platform.require_estate(ctx["tid"])
        if asset_id not in est.current:
            raise NotFound("Unknown asset.")
        x = est.explain(asset_id)
        with db.session(ctx["tid"]) as c:
            last = c.one("SELECT action, from_alg, to_alg, created_at FROM migrations WHERE tenant_id = ? AND asset_id = ? "
                         "ORDER BY created_at DESC", (ctx["tid"], asset_id))
        targets = [{"algorithm": t, "standard": ALGORITHMS[t].get("standard", ""), "status": ALGORITHMS[t]["status"],
                    "facts": PQC_FACTS.get(t)} for t in x["targets"]]
        return clean({"asset": x["asset"], "recommendation": x["recommendation"], "targets": targets,
                      "current_facts": CLASSICAL_FACTS.get(x["asset"]["algorithm"]) or PQC_FACTS.get(x["asset"]["algorithm"]),
                      "can_rollback": bool(last and last["action"] == "migrate"), "last_change": last})

    @app.post("/api/lab/validate")
    def lab_validate(body: LabBody, ctx: dict = Depends(need("validate"))):
        return platform.validate(ctx["tid"], body.asset_id, body.target)

    @app.post("/api/lab/migrate")
    def lab_migrate(body: LabBody, ctx: dict = Depends(need("migrate"))):
        return platform.migrate(ctx["tid"], ctx["user"], body.asset_id, body.target, ctx["ip"])

    @app.post("/api/lab/rollback")
    def lab_rollback(body: LabBody, ctx: dict = Depends(need("migrate"))):
        return platform.rollback(ctx["tid"], ctx["user"], body.asset_id, ctx["ip"])

    @app.post("/api/migrations/wave")
    def migrate_wave(body: WaveBody, ctx: dict = Depends(need("migrate"))):
        if body.wave not in ("Wave 1", "Wave 2", "Wave 3"):
            raise Invalid("Unknown wave.")
        return platform.migrate_wave(ctx["tid"], ctx["user"], body.wave, ctx["ip"])

    @app.post("/api/migrations/reset")
    def reset(ctx: dict = Depends(need("migrate"))):
        platform.reset(ctx["tid"], ctx["user"], ctx["ip"])
        return {"ok": True}

    @app.get("/api/migrations")
    def migrations(ctx: dict = Depends(need("read"))):
        with db.session(ctx["tid"]) as c:
            return c.all("SELECT id, asset_id, action, from_alg, to_alg, standard, wave, user_email, created_at, "
                         "class_before, class_after, ai_before, ai_after FROM migrations WHERE tenant_id = ? "
                         "ORDER BY created_at DESC LIMIT 200", (ctx["tid"],))

    @app.get("/api/report")
    def report(ctx: dict = Depends(need("read"))):
        est = platform.require_estate(ctx["tid"])
        return {"report": est.report(), "readiness": platform.readiness(ctx["tid"]), "waves": est.plan()["waves"]}

    @app.get("/api/report.pdf")
    def report_pdf_download(ctx: dict = Depends(need("read"))):
        tid = ctx["tid"]
        est = platform.require_estate(tid)
        tenant = platform.tenant(tid)
        with db.session(tid) as c:
            history = c.all("SELECT * FROM migrations WHERE tenant_id = ? ORDER BY created_at DESC", (tid,))
            simulated = bool(c.one("SELECT id FROM cloud_connections WHERE tenant_id = ? AND provider = 'simulator'", (tid,)))
            platform.audit(c, tid, ctx["user"], "report.downloaded", "PDF report", {}, ctx["ip"])
        pdf = report_pdf.build_report(tenant, est.overview(), platform.readiness(tid), est.report(), est.plan(),
                                      history, simulated)
        name = f"Q-MigrateAI_report_{tenant['slug']}_{datetime.now(timezone.utc):%Y-%m-%d}.pdf"
        return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/assistant")
    def ask(body: AskBody, ctx: dict = Depends(need("read"))):
        est = platform.require_estate(ctx["tid"])
        return assistant.answer(est, body.message, platform.readiness(ctx["tid"]))

    # ===================================================== project data view
    # One "project" = one connection (for example public websites chatgpt.com, google.com).
    @app.get("/api/projects")
    def projects(ctx: dict = Depends(need("read"))):
        return {"projects": project_data.list_projects(platform, ctx["tid"]),
                "can_edit": "discover" in ctx["perms"], "user": ctx["user"]["email"],
                "tenant": platform.tenant(ctx["tid"])["name"]}

    @app.get("/api/projects/{cid}/data")
    def project_rows(cid: str, ctx: dict = Depends(need("read"))):
        return project_data.project_data(platform, ctx["tid"], cid)

    @app.patch("/api/projects/{cid}/assets/{asset_id}")
    def project_correct(cid: str, asset_id: str, body: CorrectionBody, ctx: dict = Depends(need("discover"))):
        return project_data.correct(platform, ctx["tid"], cid, ctx["user"], asset_id, body.changes, body.note,
                                    body.revert, ctx["ip"])

    @app.get("/api/projects/{cid}/export")
    def project_export(cid: str, format: str = "csv", ctx: dict = Depends(need("read"))):
        kinds = {"csv": ("text/csv; charset=utf-8", project_data.to_csv),
                 "json": ("application/json", project_data.to_json),
                 "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", project_data.to_xlsx)}
        if format not in kinds:
            raise Invalid("Format must be csv, json or xlsx.")
        data = project_data.project_data(platform, ctx["tid"], cid)
        media, build = kinds[format]
        body = build(data)
        with db.session(ctx["tid"]) as c:
            platform.audit(c, ctx["tid"], ctx["user"], "data.exported", data["project"]["name"], {"format": format}, ctx["ip"])
        return Response(body, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="{project_data.file_name(data, format)}"'})

    # ============================================================ alerts
    @app.get("/api/alerts")
    def alerts(ctx: dict = Depends(need("read"))):
        with db.session(ctx["tid"]) as c:
            rows = c.all("SELECT * FROM alerts WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 200", (ctx["tid"],))
            outbox = c.all("SELECT channel, target, subject, status, error, created_at FROM notification_outbox "
                           "WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 20", (ctx["tid"],))
        return {"alerts": rows, "deliveries": outbox}

    @app.post("/api/alerts/{aid}/read")
    def alert_read(aid: str, ctx: dict = Depends(need("read"))):
        with db.session(ctx["tid"]) as c:
            c.execute("UPDATE alerts SET read_at = ? WHERE tenant_id = ? AND id = ?", (now_iso(), ctx["tid"], aid))
        return {"ok": True}

    @app.post("/api/alerts/read-all")
    def alerts_read_all(ctx: dict = Depends(need("read"))):
        with db.session(ctx["tid"]) as c:
            c.execute("UPDATE alerts SET read_at = ? WHERE tenant_id = ? AND read_at IS NULL", (now_iso(), ctx["tid"]))
        return {"ok": True}

    @app.get("/api/audit")
    def audit(ctx: dict = Depends(need("audit"))):
        with db.session(ctx["tid"]) as c:
            rows = c.all("SELECT user_email, action, target, details, ip, created_at FROM audit_log WHERE tenant_id = ? "
                         "ORDER BY created_at DESC LIMIT 300", (ctx["tid"],))
        for r in rows:
            r["details"] = json.loads(r["details"] or "{}")
        return rows

    # ============================================================== GDPR
    @app.get("/api/gdpr/export")
    def gdpr_export(ctx: dict = Depends(need("gdpr"))):
        data = platform.export_tenant(ctx["tid"])
        with db.session(ctx["tid"]) as c:
            platform.audit(c, ctx["tid"], ctx["user"], "gdpr.export", "all company data", {}, ctx["ip"])
        name = f"Q-MigrateAI_export_{datetime.now(timezone.utc):%Y-%m-%d}.json"
        return Response(json.dumps(data, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/gdpr/delete")
    def gdpr_delete(body: DeleteBody, response: Response, ctx: dict = Depends(need("gdpr"))):
        tenant = platform.tenant(ctx["tid"])
        if body.confirm.strip() != tenant["name"]:
            raise Invalid("Type the exact company name to confirm deletion.")
        platform.delete_tenant(ctx["tid"])
        log.info("tenant deleted on request (GDPR): %s", ctx["tid"])
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True, "deleted": True}

    # ============================================================ static web
    # The project data page lives outside web/ (the dashboard is kept unchanged): /project-data/
    app.mount("/project-data", StaticFiles(directory=Path(__file__).parent / "dataview", html=True), name="dataview")
    if s.serve_web and s.web_dir.exists():
        app.mount("/", StaticFiles(directory=s.web_dir, html=True), name="web")

    return app


app = create_app()
