"""Project data view: everything collected for one project (one connection), its migration status,
corrections made by users, and exports (CSV, JSON, Excel).

A "project" here is one connection on the Connect page, for example "Public websites" with the
custom domains chatgpt.com, google.com. Each row is one cryptographic asset that discovery found
for it (the website's TLS key exchange, its certificate, the certificate authorities behind it).

Status of a row:
  * migrated          - the platform migrated it (current algorithm differs from the one discovered);
  * needs_migration   - it still uses an algorithm a quantum computer breaks (or a weak/legacy one);
  * safe              - it already uses a quantum-safe algorithm (no migration needed).
"used" means the row is part of the AI risk analysis, the migration plan and the report.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from qmigrate.engine.catalog import ALGORITHMS, SAFE_STATUSES, SERVICE_LABELS
from qmigrate.engine.estate import clean
from qmigrate.server.db import now_iso

STATUS_TEXT = {"migrated": "Migrated", "needs_migration": "Needs migration", "safe": "Already quantum-safe"}
EXPOSURES = ("internet", "partner", "internal")

# Fields a user may correct. (Measured algorithms are not editable: change them by migrating in the PQC lab.)
EDITABLE = {
    "application": "Target / application",
    "owner_team": "Owner (organisation)",
    "region": "Region",
    "exposure": "Exposure",
    "data_sensitivity": "Data sensitivity (1-5)",
    "retention_years": "Must stay secret for (years)",
    "business_criticality": "Business criticality (1-5)",
    "clients_support_pqc": "Clients support post-quantum",
}

# Where each piece of data comes from, and what the platform uses it for.
FIELD_GUIDE = [
    ("asset_id", "Asset", "Discovery", "Identifies the asset everywhere in the platform"),
    ("target", "Target", "What you typed in the project (domain) or the cloud resource name", "Groups the data per target"),
    ("kind", "Kind", "Discovery", "Risk model feature (type of service)"),
    ("algorithm_discovered", "Algorithm found", "Measured live (TLS handshake / certificate / cloud API)",
     "Main input of the risk score and the quantum deadline"),
    ("algorithm_current", "Algorithm now", "Discovered value, or the target chosen when migrating", "Migration status"),
    ("status", "Status", "Calculated", "Shows which data is migrated and which still needs migration"),
    ("protocol", "Protocol", "Measured live", "Shown in the report"),
    ("tls_version", "TLS version", "Measured live (public websites)", "Evidence"),
    ("cipher", "Cipher suite", "Measured live (public websites)", "Evidence"),
    ("pq_group", "Key-exchange group offered back", "Measured live: post-quantum test (X25519MLKEM768 offer)",
     "Decides if the site is already post-quantum"),
    ("cert_issuer", "Certificate issuer", "Measured live (certificate chain)", "Dependency map (who signs what)"),
    ("cert_expires", "Certificate expires", "Measured live (certificate)", "Years the signature must stay valid"),
    ("ip", "IP address", "Measured live (DNS / connection)", "Finds the hosting cloud"),
    ("cloud", "Hosting cloud", "Matched with AWS / Azure / Google Cloud / Cloudflare published IP lists", "Grouping, report"),
    ("region", "Region", "Hosting IP list or cloud API", "Grouping, report"),
    ("owner_team", "Owner", "Certificate organisation name or cloud account", "Report"),
    ("exposure", "Exposure", "Discovery (internet-facing sites are 'internet')", "Risk model feature"),
    ("data_sensitivity", "Data sensitivity (1-5)", "Sector assumption of the project (finance, health ...)",
     "Risk model feature, harvest-now-decrypt-later check"),
    ("retention_years", "Must stay secret for (years)", "Sector assumption, or certificate lifetime",
     "Quantum deadline (Mosca's X)"),
    ("business_criticality", "Business criticality (1-5)", "Sector assumption / popularity rank", "Risk model feature"),
    ("clients_support_pqc", "Clients support post-quantum", "Assumption (browsers support hybrid ML-KEM)", "Migration plan"),
    ("risk_class", "AI risk class", "Calculated by the AI model", "Priority in the migration plan"),
    ("ai_score", "AI risk score (0-100)", "Calculated by the AI model", "Priority in the migration plan"),
    ("rule_score", "Formula risk score (0-100)", "Calculated by the transparent formula", "Comparison with the AI"),
    ("upgrade_by", "Upgrade by (year)", "Calculated with Mosca's theorem", "Quantum deadline"),
    ("used_in_analysis", "Used in analysis", "Calculated", "Yes = part of the risk analysis, plan and report"),
    ("migrated_at", "Migrated on", "Migration history", "Migration status"),
    ("note", "Note", "Typed by a user", "Your own remarks"),
]

EXPORT_COLUMNS = [f for f, *_ in FIELD_GUIDE] + ["corrected_fields", "first_seen", "last_seen"]


def _num(v):
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def status_of(discovered: str, current: str) -> str:
    if current != discovered:
        return "migrated"
    alg = ALGORITHMS.get(current, {})
    if alg.get("status") in SAFE_STATUSES:
        return "safe"
    return "needs_migration"


def _target(r: dict) -> str:
    aid = r["asset_id"]
    if aid.startswith("CA-"):
        return "Certificate authorities (shared)"
    return r.get("application") or aid


def connection(platform, tid: str, cid: str) -> dict:
    with platform.db.session(tid) as c:
        conn = c.one("SELECT id, provider, display_name, config, status, created_at, last_sync_at, last_meta "
                     "FROM cloud_connections WHERE tenant_id = ? AND id = ?", (tid, cid))
    if not conn:
        from qmigrate.server.services import NotFound
        raise NotFound("Project not found.")
    conn["config"] = json.loads(conn["config"] or "{}")
    conn["last_meta"] = json.loads(conn["last_meta"] or "{}")
    return conn


def list_projects(platform, tid: str) -> list[dict]:
    with platform.db.session(tid) as c:
        conns = c.all("SELECT id, provider, display_name, config, status, last_sync_at FROM cloud_connections "
                      "WHERE tenant_id = ? ORDER BY created_at", (tid,))
        rows = c.all("SELECT connection_id, algorithm_discovered, algorithm_current FROM assets WHERE tenant_id = ?", (tid,))
    out = []
    for conn in conns:
        mine = [r for r in rows if r["connection_id"] == conn["id"]]
        counts = {k: 0 for k in STATUS_TEXT}
        for r in mine:
            counts[status_of(r["algorithm_discovered"], r["algorithm_current"])] += 1
        config = json.loads(conn["config"] or "{}")
        out.append({"id": conn["id"], "name": conn["display_name"], "provider": conn["provider"],
                    "targets": _targets_text(conn["provider"], config), "last_sync_at": conn["last_sync_at"],
                    "assets": len(mine), "counts": counts})
    return out


def _targets_text(provider: str, config: dict) -> str:
    if provider == "public":
        src = config.get("source", "finance")
        if src == "custom":
            return str(config.get("domains", ""))
        return {"finance": "Banks and payment companies", "health": "Hospitals and health agencies",
                "tranco": "Most popular websites (Tranco)"}.get(src, src) + f" (top {config.get('top') or 50})"
    if provider == "aws":
        return "AWS regions: " + str(config.get("regions", ""))
    if provider == "azure":
        return "Azure subscription " + str(config.get("subscription_id", ""))
    if provider == "gcp":
        return "Google Cloud project " + str(config.get("project_id", ""))
    return provider


def project_data(platform, tid: str, cid: str) -> dict:
    conn = connection(platform, tid, cid)
    with platform.db.session(tid) as c:
        rows = c.all("SELECT * FROM assets WHERE tenant_id = ? AND connection_id = ? ORDER BY asset_id", (tid, cid))
        last_mig = {}
        for m in c.all("SELECT asset_id, action, to_alg, user_email, created_at FROM migrations WHERE tenant_id = ? "
                       "AND action IN ('migrate', 'rollback') ORDER BY created_at", (tid,)):
            last_mig[m["asset_id"]] = m
    est = platform.estate(tid)
    analysed = {}
    if est is not None:
        analysed = {r["asset_id"]: r for r in est.assets()}
    items = []
    for r in rows:
        ev = json.loads(r.get("evidence") or "{}")
        fixes = json.loads(r.get("corrections") or "{}")
        a = analysed.get(r["asset_id"])
        st = status_of(r["algorithm_discovered"], r["algorithm_current"])
        mig = last_mig.get(r["asset_id"]) if st == "migrated" else None
        pq = ev.get("pq_probe") or {}
        items.append(clean({
            "asset_id": r["asset_id"], "target": _target(r), "application": r["application"],
            "kind": SERVICE_LABELS.get(r["service_type"], r["service_type"]), "usage": r["usage"],
            "algorithm_discovered": r["algorithm_discovered"], "algorithm_current": r["algorithm_current"],
            "status": st, "status_text": STATUS_TEXT[st],
            "protocol": r["protocol"], "tls_version": ev.get("tls_version"), "cipher": ev.get("cipher"),
            "pq_group": pq.get("group"), "pq_note": pq.get("note"),
            "cert_issuer": ev.get("issuer"), "cert_subject": ev.get("subject"), "cert_expires": ev.get("not_after"),
            "ip": ev.get("ip"), "cloud": r["cloud"], "region": r["region"], "owner_team": r["owner_team"],
            "exposure": r["exposure"], "data_sensitivity": r["data_sensitivity"],
            "retention_years": _num(r["retention_years"]), "business_criticality": r["business_criticality"],
            "clients_support_pqc": bool(r["clients_support_pqc"]) and r["clients_support_pqc"] not in ("0", "false"),
            "risk_class": a["ai_class"] if a else None, "ai_score": a["ai_score"] if a else None,
            "rule_score": a["rule_score"] if a else None,
            "upgrade_by": (a.get("deadline") or {}).get("finish_by") if a else None,
            "why": a.get("why") if a else None,
            "used_in_analysis": a is not None,
            "migrated_at": mig["created_at"] if mig else None, "migrated_by": mig["user_email"] if mig else None,
            "note": r.get("note") or "", "corrections": fixes,
            "corrected_fields": ", ".join(EDITABLE.get(f, f) for f in fixes),
            "evidence": ev, "first_seen": r["first_seen"], "last_seen": r["last_seen"],
        }))
    counts = {k: sum(1 for i in items if i["status"] == k) for k in STATUS_TEXT}
    meta = conn["last_meta"] or {}
    not_reached = meta.get("failed") or []
    targets: dict[str, dict] = {}
    for i in items:
        t = targets.setdefault(i["target"], {"target": i["target"], "assets": 0, **{k: 0 for k in STATUS_TEXT}})
        t["assets"] += 1
        t[i["status"]] += 1
    return clean({
        "project": {"id": conn["id"], "name": conn["display_name"], "provider": conn["provider"],
                    "targets": _targets_text(conn["provider"], conn["config"]), "last_sync_at": conn["last_sync_at"],
                    "status": conn["status"]},
        "summary": {"assets": len(items), **counts, "used_in_analysis": sum(1 for i in items if i["used_in_analysis"]),
                    "corrected": sum(1 for i in items if i["corrections"]),
                    "targets_requested": meta.get("domains"), "targets_reached": meta.get("reached"),
                    "not_reached": len(not_reached)},
        "analysis_ready": est is not None,
        "targets": sorted(targets.values(), key=lambda t: (t["target"].startswith("Certificate authorities"), t["target"])),
        "not_reached": not_reached,
        "rows": items,
        "editable": EDITABLE, "exposures": list(EXPOSURES),
        "field_guide": [{"field": f, "label": lab, "source": src, "used_for": use} for f, lab, src, use in FIELD_GUIDE],
        "status_text": STATUS_TEXT,
        "generated_at": now_iso(),
    })


# ------------------------------------------------------------------ corrections
def _validate(field: str, value):
    from qmigrate.server.services import Invalid
    if field not in EDITABLE:
        raise Invalid(f"'{field}' cannot be corrected here.")
    if field in ("application", "owner_team", "region"):
        value = str(value or "").strip()
        if not value or len(value) > 120:
            raise Invalid(f"{EDITABLE[field]}: type 1 to 120 characters.")
        return value
    if field == "exposure":
        if value not in EXPOSURES:
            raise Invalid("Exposure must be internet, partner or internal.")
        return value
    if field in ("data_sensitivity", "business_criticality"):
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise Invalid(f"{EDITABLE[field]}: a whole number from 1 to 5.") from None
        if not 1 <= v <= 5:
            raise Invalid(f"{EDITABLE[field]}: a whole number from 1 to 5.")
        return v
    if field == "retention_years":
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise Invalid("Years must be a number from 0 to 100.") from None
        if not 0 <= v <= 100:
            raise Invalid("Years must be a number from 0 to 100.")
        return int(v) if v.is_integer() else round(v, 1)
    if field == "clients_support_pqc":
        if isinstance(value, str):
            value = value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    return value


def correct(platform, tid: str, cid: str, user: dict, asset_id: str, changes: dict, note: str | None,
            revert: list[str] | None, ip: str | None = None) -> dict:
    from qmigrate.server.services import Invalid, NotFound
    connection(platform, tid, cid)
    with platform._locks[tid]:
        with platform.db.session(tid) as c:
            row = c.one("SELECT * FROM assets WHERE tenant_id = ? AND connection_id = ? AND asset_id = ?",
                        (tid, cid, asset_id))
            if not row:
                raise NotFound("Unknown asset in this project.")
            fixes = json.loads(row.get("corrections") or "{}")
            done = {}
            for field, raw in (changes or {}).items():
                value = _validate(field, raw)
                current = row[field]
                if field == "clients_support_pqc":
                    current = bool(current) and current not in ("0", "false")
                if value == current:
                    continue
                original = fixes[field]["original"] if field in fixes else current
                if value == original:
                    fixes.pop(field, None)          # set back to what discovery measured: no longer a correction
                else:
                    fixes[field] = {"value": value, "original": original, "by": user.get("email"), "at": now_iso()}
                c.execute(f"UPDATE assets SET {field} = ? WHERE tenant_id = ? AND asset_id = ?", (value, tid, asset_id))
                done[field] = {"from": current, "to": value}
            for field in revert or []:
                if field not in fixes:
                    continue
                original = fixes.pop(field)["original"]
                c.execute(f"UPDATE assets SET {field} = ? WHERE tenant_id = ? AND asset_id = ?", (original, tid, asset_id))
                done[field] = {"from": row[field], "to": original, "reverted": True}
            if note is not None:
                note = note.strip()
                if len(note) > 1000:
                    raise Invalid("Notes can be up to 1000 characters.")
                if note != (row.get("note") or ""):
                    c.execute("UPDATE assets SET note = ? WHERE tenant_id = ? AND asset_id = ?", (note or None, tid, asset_id))
                    done["note"] = {"to": note}
            if not done:
                return {"changed": {}}
            c.execute("UPDATE assets SET corrections = ? WHERE tenant_id = ? AND asset_id = ?",
                      (json.dumps(fixes) if fixes else None, tid, asset_id))
            platform.audit(c, tid, user, "data.corrected", asset_id, done, ip)
        platform.invalidate(tid)   # risk scores and deadlines are recalculated with the corrected data
    return {"changed": clean(done)}


# ------------------------------------------------------------------ exports
def _cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (dict, list)):
        return json.dumps(v)
    return v


def _export_rows(data: dict) -> list[dict]:
    out = []
    for r in data["rows"]:
        row = {k: _cell(r.get(k)) for k in EXPORT_COLUMNS}
        row["status"] = r["status_text"]
        out.append(row)
    return out


def file_name(data: dict, ext: str) -> str:
    import re
    slug = re.sub(r"[^A-Za-z0-9]+", "-", data["project"]["name"]).strip("-")[:40] or "project"
    return f"Q-MigrateAI_data_{slug}_{datetime.now(timezone.utc):%Y-%m-%d}.{ext}"


def to_csv(data: dict) -> bytes:
    labels = {f: lab for f, lab, *_ in FIELD_GUIDE}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([labels.get(c, c.replace("_", " ").capitalize()) for c in EXPORT_COLUMNS])
    for row in _export_rows(data):
        w.writerow([row[c] for c in EXPORT_COLUMNS])
    return ("﻿" + buf.getvalue()).encode("utf-8")      # BOM so Excel opens accents correctly


def to_json(data: dict) -> bytes:
    out = {k: data[k] for k in ("project", "summary", "targets", "not_reached", "rows", "field_guide", "generated_at")}
    out["format"] = "Q-MigrateAI project data v1"
    return json.dumps(out, indent=2, ensure_ascii=False).encode("utf-8")


def to_xlsx(data: dict) -> bytes:
    from qmigrate.server.services import Invalid
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise Invalid("Excel export needs the openpyxl package: run  pip install openpyxl  (or download CSV).") from None
    wb = Workbook()
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="2B2560")
    status_fill = {"Migrated": "D7F5E3", "Needs migration": "FBD9D7", "Already quantum-safe": "E3F0FF"}

    ws = wb.active
    ws.title = "Summary"
    p, s = data["project"], data["summary"]
    lines = [("Project", p["name"]), ("Targets", p["targets"]), ("Last discovery", p["last_sync_at"] or ""),
             ("Assets found", s["assets"]), ("Used in analysis", s["used_in_analysis"]),
             ("Migrated", s["migrated"]), ("Needs migration", s["needs_migration"]),
             ("Already quantum-safe", s["safe"]), ("Corrected by users", s["corrected"]),
             ("Websites that could not be reached (not used)", s["not_reached"]),
             ("Exported", data["generated_at"])]
    for k, v in lines:
        ws.append([k, v])
    ws.append([])
    ws.append(["Target", "Assets", "Migrated", "Needs migration", "Already quantum-safe"])
    for c in ws[ws.max_row]:
        c.font, c.fill = head, fill
    for t in data["targets"]:
        ws.append([t["target"], t["assets"], t["migrated"], t["needs_migration"], t["safe"]])
    if data["not_reached"]:
        ws.append([])
        ws.append(["Not reached (not used)", "Reason"])
        for c in ws[ws.max_row]:
            c.font, c.fill = head, fill
        for f in data["not_reached"]:
            ws.append([f.get("domain"), "; ".join(f.get("errors") or [])])
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 40

    ws = wb.create_sheet("Data")
    labels = {f: lab for f, lab, *_ in FIELD_GUIDE}
    ws.append([labels.get(c, c.replace("_", " ").capitalize()) for c in EXPORT_COLUMNS])
    for c in ws[1]:
        c.font, c.fill = head, fill
        c.alignment = Alignment(wrap_text=True, vertical="top")
    st_col = EXPORT_COLUMNS.index("status") + 1
    for row in _export_rows(data):
        ws.append([row[c] for c in EXPORT_COLUMNS])
        color = status_fill.get(row["status"])
        if color:
            ws.cell(ws.max_row, st_col).fill = PatternFill("solid", fgColor=color)
    for i, c in enumerate(EXPORT_COLUMNS, 1):
        ws.column_dimensions[get_column_letter(i)].width = 30 if c in ("cert_issuer", "cipher", "target", "asset_id") else 18
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions

    ws = wb.create_sheet("Field guide")
    ws.append(["Column", "Where the data comes from", "What the platform uses it for"])
    for c in ws[1]:
        c.font, c.fill = head, fill
    for g in data["field_guide"]:
        ws.append([g["label"], g["source"], g["used_for"]])
    for col, w in zip("ABC", (32, 70, 60)):
        ws.column_dimensions[col].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
