"""Two demo workspaces, to show tenant isolation.

With real data (the default), "Demo Finance Co." watches the public websites of real banks and payment
companies, and "Demo Health Group" those of real hospitals and health agencies; the workspace names and
logins are fictional. The e-mail domains use the reserved
'.example' top-level domain, so they can never belong to a real company.
"""
from __future__ import annotations

import logging

from qmigrate.server.db import new_id, now_iso
from qmigrate.server.security import hash_password

log = logging.getLogger("qmigrate.seed")

DEMO_TENANTS = [
    {
        "company": "Demo Finance Co.", "profile": "bank", "seed": 42, "domain": "demofinance.example",
        "users": [("admin", "Alex Admin"), ("ciso", "Camille CISO"), ("analyst", "Ana Analyst"), ("viewer", "Victor Viewer")],
    },
    {
        "company": "Demo Health Group", "profile": "hospital", "seed": 7, "domain": "demohealth.example",
        "users": [("admin", "Hana Admin"), ("ciso", "Hugo CISO")],
    },
]


def seed_demo(platform) -> list[str]:
    """Create the demo tenants if the database has no tenants yet. Returns the created tenant ids."""
    db, s = platform.db, platform.settings
    with db.session() as c:
        if c.one("SELECT id FROM tenants"):
            return []
    created = []
    for spec in DEMO_TENANTS:
        role, name = spec["users"][0]
        tenant, admin = platform.create_tenant(
            spec["company"], f"{role}@{spec['domain']}", name, s.demo_password, consent=True, is_demo=(s.data_source == "simulator"),
            profile=spec["profile"], seed=spec["seed"], assets=s.demo_assets)
        tid = tenant["id"]
        with db.session(tid) as c:
            for role, name in spec["users"][1:]:
                c.execute("INSERT INTO users (id, tenant_id, email, name, password_hash, role, gdpr_consent_at, created_at) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                          (new_id(), tid, f"{role}@{spec['domain']}", name, hash_password(s.demo_password), role,
                           now_iso(), now_iso()))
        log.info("seeding %s: running first discovery and training models", spec["company"])
        platform.start_discovery(tid, admin, wait=True, triggered_by="seed")
        created.append(tid)
    return created
