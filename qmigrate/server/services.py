"""The platform's business logic: tenants, discovery, estates, migrations, alerts, audit, GDPR."""
from __future__ import annotations

import json
import logging
import pickle
import re
import smtplib
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from email.message import EmailMessage

import requests

from qmigrate.engine import graph as g
from qmigrate.engine.catalog import ALGORITHMS
from qmigrate.engine.estate import Estate, clean, train_bundle
from qmigrate.server.connectors.base import ConnectorNotReady
from qmigrate.server.connectors.clouds import PROVIDERS, make_connector
from qmigrate.server.db import Database, new_id, now_iso
from qmigrate.server.security import SecretBox, hash_password

log = logging.getLogger("qmigrate")

ROLES = ["admin", "ciso", "analyst", "viewer"]
PERMISSIONS = {
    "viewer": {"read"},
    "analyst": {"read", "discover", "validate", "assistant"},
    "ciso": {"read", "discover", "validate", "assistant", "migrate", "connections", "alerts", "audit"},
    "admin": {"read", "discover", "validate", "assistant", "migrate", "connections", "alerts", "audit",
              "users", "settings", "gdpr"},
}
ASSET_COLUMNS = ["asset_id", "cloud", "region", "application", "owner_team", "service_type", "usage", "protocol",
                 "exposure", "data_sensitivity", "retention_years", "business_criticality", "clients_support_pqc",
                 "analyst_label"]


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "company"


def _as_bool(v) -> bool:
    return bool(v) and v not in ("0", "false", "False")


class RateLimiter:
    """Counts failures per key in a sliding window (in memory, per process)."""

    def __init__(self, limit: int = 8, window_s: int = 900):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, list[float]] = defaultdict(list)
        self.lock = threading.Lock()

    def blocked(self, key: str, limit: int | None = None) -> bool:
        with self.lock:
            now = time.time()
            self.hits[key] = [t for t in self.hits[key] if now - t < self.window]
            return len(self.hits[key]) >= (limit or self.limit)

    def fail(self, key: str) -> None:
        with self.lock:
            self.hits[key].append(time.time())

    def reset(self, key: str) -> None:
        with self.lock:
            self.hits.pop(key, None)


class Platform:
    def __init__(self, settings, db: Database):
        self.settings = settings
        self.db = db
        self.box = SecretBox(settings.secret_key)
        self.rate = RateLimiter()
        self._estates: dict[str, Estate] = {}
        self._locks: dict[str, threading.RLock] = defaultdict(threading.RLock)
        self._running: set[str] = set()
        self._start_lock = threading.Lock()   # makes "is a discovery running? if not, start one" atomic
        self._stop = threading.Event()
        self.slack_prefix = "https://hooks.slack.com/"

    # ================================================================ tenants
    def create_tenant(self, company: str, email: str, name: str, password: str, *, consent: bool,
                      is_demo: bool = False, profile: str = "generic", seed: int | None = None,
                      assets: int | None = None, source: str | None = None) -> tuple[dict, dict]:
        email = email.strip().lower()
        with self.db.session() as c:
            if self.db.user_by_email(c, email):
                raise Invalid("An account with this e-mail already exists.")
            base = _slug(company)
            slug, i = base, 1
            while c.one("SELECT id FROM tenants WHERE slug = ?", (slug,)):
                i += 1
                slug = f"{base}-{i}"
        tid, uid, ts = new_id(), new_id(), now_iso()
        with self.db.session(tid) as c:
            c.execute("INSERT INTO tenants (id, name, slug, data_region, is_demo, created_at) VALUES (?, ?, ?, 'EU', ?, ?)",
                      (tid, company.strip(), slug, is_demo, ts))
            c.execute("INSERT INTO users (id, tenant_id, email, name, password_hash, role, gdpr_consent_at, created_at) "
                      "VALUES (?, ?, ?, ?, ?, 'admin', ?, ?)",
                      (uid, tid, email, name.strip(), hash_password(password), ts if consent else None, ts))
            c.execute("INSERT INTO tenant_settings (tenant_id, alert_email, monitor_interval_hours, updated_at) "
                      "VALUES (?, ?, 24, ?)", (tid, email, ts))
            if self.settings.data_source == "simulator" or source == "simulator":
                provider, display = "simulator", "Demo cloud (simulator)"
                config = {"profile": profile, "seed": seed if seed is not None else (sum(map(ord, slug)) % 900 + 100),
                          "assets": assets or self.settings.demo_assets, "simulate_changes": True}
            else:   # real data: public websites of real organisations in the matching sector
                provider = "public"
                source = {"bank": "finance", "hospital": "health"}.get(profile, "tranco")
                config = {"source": source, "top": self.settings.public_sites}
                display = PROVIDERS["public"]["title"] + {"finance": ": finance sector", "health": ": health sector",
                                                           "tranco": ": most popular sites"}[source]
            c.execute("INSERT INTO cloud_connections (id, tenant_id, provider, display_name, config, status, created_at) "
                      "VALUES (?, ?, ?, ?, ?, 'connected', ?)",
                      (new_id(), tid, provider, display, json.dumps(config), ts))
            self.audit(c, tid, {"id": uid, "email": email}, "tenant.created", company,
                       {"gdpr_consent": consent, "data_region": "EU"})
        return {"id": tid, "name": company, "slug": slug}, {"id": uid, "email": email, "role": "admin"}

    def tenant(self, tid: str) -> dict:
        with self.db.session(tid) as c:
            row = c.one("SELECT * FROM tenants WHERE id = ?", (tid,))
        if not row:
            raise NotFound("tenant")
        row["is_demo"] = _as_bool(row["is_demo"])
        return row

    # ================================================================== audit
    @staticmethod
    def audit(c, tid: str, user: dict | None, action: str, target: str = "", details=None, ip: str | None = None):
        c.execute("INSERT INTO audit_log (id, tenant_id, user_id, user_email, action, target, details, ip, created_at) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (new_id(), tid, (user or {}).get("id"), (user or {}).get("email", "system"), action, target,
                   json.dumps(clean(details or {})), ip, now_iso()))

    # ================================================================ estates
    def estate(self, tid: str) -> Estate | None:
        with self._locks[tid]:
            if tid in self._estates:
                return self._estates[tid]
            with self.db.session(tid) as c:
                rows = c.all("SELECT * FROM assets WHERE tenant_id = ? ORDER BY asset_id", (tid,))
                edges = c.all("SELECT source, target, relation FROM dependencies WHERE tenant_id = ?", (tid,))
                model = c.one("SELECT bundle, positions FROM model_runs WHERE tenant_id = ? AND is_active = ? "
                              "ORDER BY created_at DESC", (tid, True))
            if not rows or not model:
                return None
            assets = []
            for r in rows:
                a = {k: r[k] for k in ASSET_COLUMNS}
                a["clients_support_pqc"] = _as_bool(a["clients_support_pqc"])
                a["algorithm_discovered"], a["algorithm_current"] = r["algorithm_discovered"], r["algorithm_current"]
                assets.append(a)
            try:
                # The bundle was written by this server (never by users), so loading it is safe.
                bundle = pickle.loads(bytes(model["bundle"]))
            except Exception:  # noqa: BLE001  e.g. scikit-learn was upgraded since training
                log.warning("stored models for tenant %s could not be loaded; retraining", tid)
                with self.db.session(tid) as c:
                    seed = c.scalar("SELECT seed FROM model_runs WHERE tenant_id = ? AND is_active = ?", (tid, True)) or 42
                self._train(tid, int(seed))
                return self.estate(tid)
            positions = json.loads(model["positions"]) if model["positions"] else None
            if positions and any(a["asset_id"] not in positions for a in assets):
                positions = None
            est = Estate(assets, edges, bundle, positions)
            self._estates[tid] = est
            return est

    def require_estate(self, tid: str) -> Estate:
        est = self.estate(tid)
        if est is None:
            raise NotFound("No inventory yet: connect a cloud and run a discovery first.")
        return est

    def invalidate(self, tid: str) -> None:
        with self._locks[tid]:
            self._estates.pop(tid, None)

    def last_discovery(self, tid: str) -> dict | None:
        with self.db.session(tid) as c:
            return c.one("SELECT * FROM discovery_runs WHERE tenant_id = ? ORDER BY started_at DESC", (tid,))

    def migrations_count(self, tid: str) -> int:
        with self.db.session(tid) as c:
            return int(c.scalar("SELECT COUNT(*) AS n FROM migrations WHERE tenant_id = ? AND action = 'migrate'",
                                (tid,)) or 0)

    def readiness(self, tid: str) -> dict:
        est = self.require_estate(tid)
        last = None
        with self.db.session(tid) as c:
            last = c.one("SELECT finished_at FROM discovery_runs WHERE tenant_id = ? AND status = 'completed' "
                         "ORDER BY finished_at DESC", (tid,))
        age = None
        if last and last["finished_at"]:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last["finished_at"])).total_seconds() / 86400
        return est.readiness(age, self.migrations_count(tid))

    # ============================================================== discovery
    def start_discovery(self, tid: str, user: dict | None, connection_id: str | None = None,
                        wait: bool = False, triggered_by: str = "user") -> str:
        with self.db.session(tid) as c:
            if connection_id:
                conn = c.one("SELECT * FROM cloud_connections WHERE tenant_id = ? AND id = ?", (tid, connection_id))
            else:
                conn = (c.one("SELECT * FROM cloud_connections WHERE tenant_id = ? AND provider = ? "
                              "ORDER BY created_at", (tid, self.settings.data_source))
                        or c.one("SELECT * FROM cloud_connections WHERE tenant_id = ? AND provider IN ('public', 'simulator') "
                                 "ORDER BY created_at", (tid,)))
            if not conn:
                raise NotFound("Cloud connection not found.")
        # One discovery at a time per workspace: a second click (or the scheduler) joins the running one.
        with self._start_lock, self.db.session(tid) as c:
            running = c.one("SELECT id FROM discovery_runs WHERE tenant_id = ? AND status = 'running' "
                            "ORDER BY started_at DESC", (tid,))
            if running and tid in self._running:
                return running["id"]
            # A run still marked running while nothing runs was cut off by a restart of the platform.
            c.execute("UPDATE discovery_runs SET status = 'failed', phase = 'failed', finished_at = ?, "
                      "message = 'Stopped because the platform was restarted. Run discovery again.' "
                      "WHERE tenant_id = ? AND status = 'running'", (now_iso(), tid))
            run_id = new_id()
            c.execute("INSERT INTO discovery_runs (id, tenant_id, connection_id, status, phase, triggered_by, started_at) "
                      "VALUES (?, ?, ?, 'running', 'scanning', ?, ?)",
                      (run_id, tid, conn["id"], triggered_by, now_iso()))
            self.audit(c, tid, user, "discovery.started", conn["display_name"], {"provider": conn["provider"]})
            self._running.add(tid)
        if wait:
            self._discover(tid, run_id, conn, user)
        else:
            threading.Thread(target=self._discover, args=(tid, run_id, conn, user), daemon=True).start()
        return run_id

    def _phase(self, tid: str, run_id: str, phase: str) -> None:
        with self.db.session(tid) as c:
            c.execute("UPDATE discovery_runs SET phase = ? WHERE tenant_id = ? AND id = ?", (phase, tid, run_id))

    def _discover(self, tid: str, run_id: str, conn: dict, user: dict | None) -> None:
        try:
            with self.db.session(tid) as c:
                done = int(c.scalar("SELECT COUNT(*) AS n FROM discovery_runs WHERE tenant_id = ? AND connection_id = ? "
                                    "AND status = 'completed'", (tid, conn["id"])) or 0)
            connector = make_connector(conn["provider"], json.loads(conn["config"] or "{}"), self.settings.simulator_url)
            data = connector.discover(run_index=done)
            self._phase(tid, run_id, "mapping")
            with self._locks[tid]:
                new_ids, new_vulnerable, total = self._store_inventory(tid, conn["id"], data, first=(done == 0))
                self._phase(tid, run_id, "training")
                self._train(tid, seed=42)
            with self.db.session(tid) as c:
                c.execute("UPDATE discovery_runs SET status = 'completed', phase = 'done', finished_at = ?, "
                          "assets_found = ?, new_assets = ?, new_vulnerable = ? WHERE tenant_id = ? AND id = ?",
                          (now_iso(), total, len(new_ids), len(new_vulnerable), tid, run_id))
                c.execute("UPDATE cloud_connections SET last_sync_at = ?, status = 'connected', last_meta = ? "
                          "WHERE tenant_id = ? AND id = ?",
                          (now_iso(), json.dumps(clean(data.get("meta") or {})), tid, conn["id"]))
                self.audit(c, tid, user, "discovery.completed", conn["display_name"],
                           {"assets": total, "new_assets": len(new_ids), "new_vulnerable": len(new_vulnerable)})
            self.invalidate(tid)
            if new_vulnerable:
                self._alert_new_assets(tid, new_vulnerable)
        except ConnectorNotReady as exc:
            self._fail_run(tid, run_id, str(exc), user)
        except Exception as exc:  # noqa: BLE001
            log.exception("discovery failed")
            self._fail_run(tid, run_id, f"Discovery failed: {exc}", user)
        finally:
            self._running.discard(tid)

    def _fail_run(self, tid, run_id, message, user):
        with self.db.session(tid) as c:
            c.execute("UPDATE discovery_runs SET status = 'failed', phase = 'failed', finished_at = ?, message = ? "
                      "WHERE tenant_id = ? AND id = ?", (now_iso(), message, tid, run_id))
            self.audit(c, tid, user, "discovery.failed", "", {"message": message})

    def _store_inventory(self, tid: str, connection_id: str, data: dict, first: bool):
        ts = now_iso()
        with self.db.session(tid) as c:
            # Each connection owns its assets: several connections (public websites, AWS, Azure, GCP)
            # can feed one workspace, and a discovery only replaces the assets of its own connection.
            in_db = {r["asset_id"]: r for r in c.all(
                "SELECT asset_id, algorithm_discovered, algorithm_current, connection_id, corrections FROM assets "
                "WHERE tenant_id = ?", (tid,))}
            incoming = list({a["asset_id"]: a for a in data["assets"]}.values())   # never the same asset twice
            incoming_ids = {a["asset_id"] for a in incoming}
            incoming_by_id = {a["asset_id"]: a for a in incoming}
            # Assets of other connections stay, unless this discovery found the same asset (then it takes it over).
            others = {aid for aid, r in in_db.items()
                      if r["connection_id"] not in (connection_id, None) and aid not in incoming_ids}
            existing = {aid: r for aid, r in in_db.items() if aid not in others}
            seen, new_ids, new_vulnerable = set(), [], []
            for a in incoming:
                aid = a["asset_id"]
                seen.add(aid)
                evidence = json.dumps(clean(a.get("evidence") or {}))
                if aid in existing:
                    old = existing[aid]
                    # Corrections made in the project data view win over what discovery measured again.
                    fixes = json.loads(old.get("corrections") or "{}")
                    a = {**a, **{f: v["value"] for f, v in fixes.items() if f in ASSET_COLUMNS}}
                    for f, v in fixes.items():
                        v["original"] = (incoming_by_id[aid].get(f) if f in incoming_by_id[aid] else v.get("original"))
                    values = [a.get(k) for k in ASSET_COLUMNS[1:]]
                    migrated = old["algorithm_current"] != old["algorithm_discovered"]
                    disc = old["algorithm_discovered"] if migrated else a["algorithm"]
                    cur = old["algorithm_current"] if migrated else a["algorithm"]
                    c.execute("UPDATE assets SET connection_id = ?, cloud = ?, region = ?, application = ?, owner_team = ?, "
                              "service_type = ?, usage = ?, protocol = ?, exposure = ?, data_sensitivity = ?, "
                              "retention_years = ?, business_criticality = ?, clients_support_pqc = ?, analyst_label = ?, "
                              "algorithm_discovered = ?, algorithm_current = ?, last_seen = ?, evidence = ?, corrections = ? "
                              "WHERE tenant_id = ? AND asset_id = ?",
                              [connection_id, *values, disc, cur, ts, evidence, json.dumps(fixes) if fixes else None,
                               tid, aid])
                else:
                    values = [a.get(k) for k in ASSET_COLUMNS[1:]]
                    c.execute("INSERT INTO assets (tenant_id, asset_id, connection_id, cloud, region, application, owner_team, "
                              "service_type, usage, protocol, exposure, data_sensitivity, retention_years, "
                              "business_criticality, clients_support_pqc, analyst_label, algorithm_discovered, "
                              "algorithm_current, first_seen, last_seen, evidence) "
                              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              [tid, aid, connection_id, *values, a["algorithm"], a["algorithm"], ts, ts, evidence])
                    new_ids.append(aid)
                    if not first and ALGORITHMS[a["algorithm"]]["quantum_vulnerable"]:
                        new_vulnerable.append(a)
            for aid in set(existing) - seen:
                c.execute("DELETE FROM assets WHERE tenant_id = ? AND asset_id = ?", (tid, aid))
            mine = set(existing) | seen
            for e in c.all("SELECT source, target FROM dependencies WHERE tenant_id = ?", (tid,)):
                if e["source"] in mine or e["target"] in mine:
                    c.execute("DELETE FROM dependencies WHERE tenant_id = ? AND source = ? AND target = ?",
                              (tid, e["source"], e["target"]))
            valid = seen | others
            c.executemany("INSERT INTO dependencies (tenant_id, source, target, relation) VALUES (?, ?, ?, ?)",
                          [(tid, e["source"], e["target"], e["relation"]) for e in data["edges"]
                           if e["source"] in valid and e["target"] in valid])
        return new_ids, new_vulnerable, len(seen)

    def _train(self, tid: str, seed: int = 42) -> dict:
        with self.db.session(tid) as c:
            rows = c.all("SELECT * FROM assets WHERE tenant_id = ? ORDER BY asset_id", (tid,))
            edges = c.all("SELECT source, target, relation FROM dependencies WHERE tenant_id = ?", (tid,))
        assets = []
        for r in rows:
            a = {k: r[k] for k in ASSET_COLUMNS}
            a["clients_support_pqc"] = _as_bool(a["clients_support_pqc"])
            a["algorithm_discovered"], a["algorithm_current"] = r["algorithm_discovered"], r["algorithm_current"]
            assets.append(a)
        if len(assets) < 20:
            raise Invalid(f"Only {len(assets)} cryptographic assets were found; the AI models need at least 20. "
                          "Add more resources, or add the 'Public websites (real data)' connection to this workspace too.")
        counts = {c: sum(1 for a in assets if a["analyst_label"] == c) for c in ("Low", "Medium", "High", "Critical")}
        if min(counts.values()) < 5:
            # Labels from several small connections can leave a class almost empty; re-rank the whole
            # workspace with the same rubric so every risk class has examples to learn from.
            from qmigrate.realdata.collector import label_assets
            by_id = {a["asset_id"]: {**a, "algorithm": a["algorithm_discovered"]} for a in assets}
            label_assets(by_id, edges, force_balance=True)
            with self.db.session(tid) as c:
                for a in assets:
                    a["analyst_label"] = by_id[a["asset_id"]]["analyst_label"]
                    c.execute("UPDATE assets SET analyst_label = ? WHERE tenant_id = ? AND asset_id = ?",
                              (a["analyst_label"], tid, a["asset_id"]))
        bundle = train_bundle(assets, edges, seed)
        graph = g.build_graph([{**a, "algorithm": a["algorithm_discovered"]} for a in assets], edges)
        positions = g.layout(graph, 42)
        metrics = {k: {m: v for m, v in res.items() if m != "confusion"} for k, res in bundle["results"].items()}
        with self.db.session(tid) as c:
            c.execute("UPDATE model_runs SET is_active = ? WHERE tenant_id = ?", (False, tid))
            c.execute("INSERT INTO model_runs (id, tenant_id, created_at, seed, is_active, metrics, positions, bundle) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (new_id(), tid, now_iso(), seed, True, json.dumps(clean(metrics)),
                       json.dumps(clean({k: list(v) for k, v in positions.items()})), pickle.dumps(bundle)))
            c.execute("DELETE FROM model_runs WHERE tenant_id = ? AND is_active = ?", (tid, False))
        self.invalidate(tid)
        return metrics

    def retrain(self, tid: str, user: dict, seed: int) -> None:
        self._train(tid, seed)
        with self.db.session(tid) as c:
            self.audit(c, tid, user, "models.retrained", "", {"seed": seed})

    # ============================================================= migrations
    def _record(self, c, tid, user, action, item, wave=None, checks=None):
        c.execute("INSERT INTO migrations (id, tenant_id, asset_id, action, from_alg, to_alg, standard, wave, user_id, "
                  "user_email, created_at, rule_before, rule_after, ai_before, ai_after, class_before, class_after, checks) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (new_id(), tid, item["asset_id"], action, item.get("from"), item.get("to"), item.get("standard", ""),
                   wave, (user or {}).get("id"), (user or {}).get("email"), now_iso(),
                   item.get("rule_before"), item.get("rule_after"), item.get("ai_before"), item.get("ai_after"),
                   item.get("class_before"), item.get("class_after"), json.dumps(clean(checks or []))))

    def validate(self, tid: str, asset_id: str, target: str) -> dict:
        est = self.require_estate(tid)
        if asset_id not in est.current:
            raise NotFound("Unknown asset.")
        if target not in ALGORITHMS:
            raise Invalid("Unknown target algorithm.")
        return est.simulate(asset_id, target)

    def migrate(self, tid: str, user: dict, asset_id: str, target: str, ip=None) -> dict:
        with self._locks[tid]:
            est = self.require_estate(tid)
            if asset_id not in est.current:
                raise NotFound("Unknown asset.")
            if est.current[asset_id]["algorithm"] == target:
                raise Invalid(f"{asset_id} already uses {target}.")
            sim = self.validate(tid, asset_id, target)
            if not sim["valid"]:
                raise Invalid("Validation failed: " + "; ".join(c["detail"] for c in sim["checks"] if c["result"] == "FAIL"))
            with self.db.session(tid) as c:
                c.execute("UPDATE assets SET algorithm_current = ? WHERE tenant_id = ? AND asset_id = ?", (target, tid, asset_id))
                self._record(c, tid, user, "migrate", sim, checks=sim["checks"])
                self.audit(c, tid, user, "migration.applied", asset_id, {"from": sim["from"], "to": target}, ip)
            self.invalidate(tid)
        return sim

    def migrate_wave(self, tid: str, user: dict, wave: str, ip=None) -> dict:
        with self._locks[tid]:
            est = self.require_estate(tid)
            before = est.overview()["now"]
            steps = est.wave_steps(wave)
            with self.db.session(tid) as c:
                for s in steps:
                    c.execute("UPDATE assets SET algorithm_current = ? WHERE tenant_id = ? AND asset_id = ?",
                              (s["to"], tid, s["asset_id"]))
                    self._record(c, tid, user, "migrate", s, wave=wave)
                self.audit(c, tid, user, "migration.wave", wave, {"assets": len(steps)}, ip)
            self.invalidate(tid)
        return {"wave": wave, "before": before, "steps": steps}

    def rollback(self, tid: str, user: dict, asset_id: str, ip=None) -> dict:
        with self._locks[tid]:
            est = self.require_estate(tid)
            if asset_id not in est.current:
                raise NotFound("Unknown asset.")
            with self.db.session(tid) as c:
                last = c.one("SELECT * FROM migrations WHERE tenant_id = ? AND asset_id = ? ORDER BY created_at DESC",
                             (tid, asset_id))
                if not last or last["action"] != "migrate":
                    raise Invalid("This asset has no migration to roll back.")
            target = last["from_alg"]
            sim = est.simulate(asset_id, target)
            with self.db.session(tid) as c:
                c.execute("UPDATE assets SET algorithm_current = ? WHERE tenant_id = ? AND asset_id = ?", (target, tid, asset_id))
                self._record(c, tid, user, "rollback", sim)
                self.audit(c, tid, user, "migration.rolled_back", asset_id, {"from": sim["from"], "to": target}, ip)
            self.invalidate(tid)
        return sim

    def reset(self, tid: str, user: dict, ip=None) -> None:
        with self._locks[tid]:
            with self.db.session(tid) as c:
                c.execute("UPDATE assets SET algorithm_current = algorithm_discovered WHERE tenant_id = ?", (tid,))
                c.execute("INSERT INTO migrations (id, tenant_id, asset_id, action, user_id, user_email, created_at) "
                          "VALUES (?, ?, '*', 'reset', ?, ?, ?)", (new_id(), tid, user.get("id"), user.get("email"), now_iso()))
                self.audit(c, tid, user, "migration.reset", "all assets", {}, ip)
            self.invalidate(tid)

    # ================================================================= alerts
    def _alert_new_assets(self, tid: str, assets: list[dict]) -> None:
        est = self.estate(tid)
        with self.db.session(tid) as c:
            for a in assets:
                row = est.view["rows"].get(a["asset_id"]) if est else None
                cls = row["ai_class"] if row else "High"
                severity = "critical" if cls in ("Critical", "High") else "warning"
                title = f"New quantum-vulnerable asset: {a['asset_id']}"
                body = (f"Discovery found {a['asset_id']} ({a['service_type'].replace('_', ' ')}, {a['cloud']}) using "
                        f"{a['algorithm']}, which a quantum computer can break. AI risk: {cls}.")
                self.create_alert(c, tid, severity, title, body, a["asset_id"])
        self.deliver_pending(tid)

    def create_alert(self, c, tid, severity, title, body, asset_id=None) -> str:
        aid = new_id()
        c.execute("INSERT INTO alerts (id, tenant_id, severity, title, body, asset_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (aid, tid, severity, title, body, asset_id, now_iso()))
        st = c.one("SELECT alert_email, slack_webhook FROM tenant_settings WHERE tenant_id = ?", (tid,)) or {}
        c.execute("INSERT INTO notification_outbox (id, tenant_id, channel, target, subject, body, status, created_at) "
                  "VALUES (?, ?, 'email', ?, ?, ?, 'pending', ?)", (new_id(), tid, st.get("alert_email"), title, body, now_iso()))
        c.execute("INSERT INTO notification_outbox (id, tenant_id, channel, target, subject, body, status, created_at) "
                  "VALUES (?, ?, 'slack', ?, ?, ?, 'pending', ?)", (new_id(), tid, st.get("slack_webhook"), title, body, now_iso()))
        return aid

    def deliver_pending(self, tid: str) -> list[dict]:
        with self.db.session(tid) as c:
            pending = c.all("SELECT * FROM notification_outbox WHERE tenant_id = ? AND status = 'pending' ORDER BY created_at",
                            (tid,))
        results = []
        for n in pending:
            status, error = self._send(n)
            with self.db.session(tid) as c:
                c.execute("UPDATE notification_outbox SET status = ?, error = ? WHERE tenant_id = ? AND id = ?",
                          (status, error, tid, n["id"]))
            results.append({"channel": n["channel"], "status": status, "error": error})
        return results

    def _send(self, n: dict) -> tuple[str, str | None]:
        s = self.settings
        if n["channel"] == "email":
            if not n["target"]:
                return "skipped", "No alert e-mail address set."
            if not s.smtp_host:
                return "skipped", "SMTP is not configured (placeholder): set SMTP_HOST in .env to send e-mails."
            try:
                msg = EmailMessage()
                msg["Subject"], msg["From"], msg["To"] = f"[Q-MigrateAI] {n['subject']}", s.smtp_from, n["target"]
                msg.set_content(f"{n['body']}\n\nOpen the platform: {s.public_url}\n")
                with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
                    if s.smtp_starttls:
                        smtp.starttls()
                    if s.smtp_user:
                        smtp.login(s.smtp_user, s.smtp_password)
                    smtp.send_message(msg)
                return "sent", None
            except Exception as exc:  # noqa: BLE001
                return "failed", str(exc)[:300]
        if n["channel"] == "slack":
            if not n["target"]:
                return "skipped", "No Slack webhook set (placeholder)."
            if not n["target"].startswith(self.slack_prefix):
                return "failed", "Webhook URL must start with " + self.slack_prefix
            try:
                r = requests.post(n["target"], json={"text": f"*{n['subject']}*\n{n['body']}"}, timeout=8)
                return ("sent", None) if r.status_code < 300 else ("failed", f"HTTP {r.status_code}")
            except requests.RequestException as exc:
                return "failed", str(exc)[:300]
        return "skipped", "Unknown channel."

    # =============================================================== monitor
    def start_monitor(self) -> None:
        if not self.settings.monitor_enabled:
            return
        threading.Thread(target=self._monitor_loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _monitor_loop(self) -> None:
        while not self._stop.wait(self.settings.monitor_check_minutes * 60):
            try:
                self.monitor_tick()
            except Exception:  # noqa: BLE001
                log.exception("monitor tick failed")

    def monitor_tick(self) -> list[str]:
        started = []
        with self.db.session() as c:
            tenants = c.all("SELECT id FROM tenants")
        for t in tenants:
            tid = t["id"]
            if tid in self._running:
                continue
            with self.db.session(tid) as c:
                st = c.one("SELECT monitor_interval_hours FROM tenant_settings WHERE tenant_id = ?", (tid,))
                last = c.one("SELECT finished_at FROM discovery_runs WHERE tenant_id = ? AND status = 'completed' "
                             "ORDER BY finished_at DESC", (tid,))
            hours = int((st or {}).get("monitor_interval_hours") or 0)
            if hours <= 0 or not last or not last["finished_at"]:
                continue
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(last["finished_at"])).total_seconds() / 3600
            if age_h >= hours:
                self.start_discovery(tid, None, triggered_by="monitor")
                started.append(tid)
        return started

    # =================================================================== GDPR
    def export_tenant(self, tid: str) -> dict:
        out = {"exported_at": now_iso(), "format": "Q-MigrateAI GDPR export v1"}
        with self.db.session(tid) as c:
            out["company"] = c.one("SELECT id, name, slug, data_region, created_at FROM tenants WHERE id = ?", (tid,))
            out["users"] = c.all("SELECT id, email, name, role, totp_enabled, gdpr_consent_at, created_at, last_login_at "
                                 "FROM users WHERE tenant_id = ?", (tid,))
            out["settings"] = c.one("SELECT alert_email, slack_webhook, monitor_interval_hours FROM tenant_settings "
                                    "WHERE tenant_id = ?", (tid,))
            for table in ["cloud_connections", "discovery_runs", "assets", "dependencies", "migrations", "audit_log",
                          "alerts", "notification_outbox", "config_checks"]:
                out[table] = c.all(f"SELECT * FROM {table} WHERE tenant_id = ?", (tid,))
            out["model_runs"] = c.all("SELECT id, created_at, seed, is_active, metrics FROM model_runs WHERE tenant_id = ?", (tid,))
        return clean(out)

    def delete_tenant(self, tid: str) -> None:
        with self._locks[tid]:
            with self.db.session(tid) as c:
                c.execute("DELETE FROM sessions WHERE tenant_id = ?", (tid,))
                for table in ["config_checks", "notification_outbox", "alerts", "audit_log", "migrations", "model_runs",
                              "dependencies",
                              "assets", "discovery_runs", "cloud_connections", "tenant_settings", "users"]:
                    c.execute(f"DELETE FROM {table} WHERE tenant_id = ?", (tid,))
                c.execute("DELETE FROM tenants WHERE id = ?", (tid,))
            self._estates.pop(tid, None)

    # ============================================================= providers
    @staticmethod
    def providers() -> dict:
        return PROVIDERS
