"""One-click PDF report for a CISO: executive summary, before/after, readiness and plan."""
from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

NAVY = colors.HexColor("#0B1220")
BLUE = colors.HexColor("#1D4ED8")
GREY = colors.HexColor("#64748B")
LINE = colors.HexColor("#CBD5E1")
TINT = colors.HexColor("#EEF2FF")

body = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5, leading=13, textColor=colors.HexColor("#0F172A"), spaceAfter=4)
small = ParagraphStyle("s", parent=body, fontSize=8, leading=10.5, textColor=GREY)
h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=NAVY, spaceAfter=4)
h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=BLUE, spaceBefore=10, spaceAfter=5)
cell = ParagraphStyle("c", parent=body, fontSize=8.3, leading=10.4, spaceAfter=0)
cellb = ParagraphStyle("cb", parent=cell, fontName="Helvetica-Bold")


def _esc(text) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(rows, widths, header=True):
    data = [[Paragraph(_esc(v), cellb if (header and r == 0) else cell) for v in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), TINT)]
    t.setStyle(TableStyle(style))
    return t


def build_report(tenant: dict, overview: dict, readiness: dict, report: dict, plan: dict,
                 history: list[dict], simulated: bool) -> bytes:
    buf = io.BytesIO()
    W = A4[0] - 36 * mm
    generated = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")

    def frame(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(GREY)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(18 * mm, 10 * mm, f"Q-MigrateAI  |  {tenant['name']}  |  Confidential")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"Post-quantum readiness report - {tenant['name']}",
                            author="Q-MigrateAI")
    b, a = report["before"], report["after"]
    s = []
    s.append(Paragraph("Post-Quantum Readiness Report", h1))
    s.append(Paragraph(f"<b>{_esc(tenant['name'])}</b> &nbsp;|&nbsp; Generated {generated}", body))
    if simulated:
        s.append(Paragraph("Data source: demo simulator. All assets in this report are synthetic.", small))
    s.append(Spacer(1, 6))

    s.append(Paragraph("Executive summary", h2))
    delta_cov = round(a["coverage_pct"] - b["coverage_pct"], 1)
    migrated = sum(1 for h in history if h["action"] == "migrate")
    summary = (f"The inventory contains <b>{a['total_assets']}</b> cryptographic assets across "
               f"{len(a['by_cloud'])} cloud provider(s). <b>{a['quantum_exposed']}</b> are exposed to a future "
               f"quantum computer, because they use RSA, elliptic-curve cryptography or Diffie-Hellman, or depend on a key "
               f"or certificate that does. Quantum-safe coverage is <b>{a['coverage_pct']}%</b>")
    summary += (f", up {delta_cov} points since discovery after {migrated} migration(s)." if delta_cov > 0
                else ". No migrations have been applied yet.")
    summary += (f" The AI model rates <b>{a['critical']}</b> assets as Critical. Indicative post-quantum readiness "
                f"is <b>{readiness['overall']}%</b>.")
    s.append(Paragraph(summary, body))
    top = plan["queue"][:3]
    if top:
        s.append(Paragraph("Recommended next step: start Wave 1 with " + ", ".join(
            f"{_esc(t['asset_id'])} ({_esc(t['service_label'])}, {t['dependents']} dependants)" for t in top) +
            ". Shared keys and certificate authorities come first because fixing one protects every asset that depends on it.",
            body))

    s.append(Paragraph("Before and after", h2))
    rows = [["Measure", "At discovery", "Now", "Change"]]
    for label, key in [("Quantum-exposed assets", "quantum_exposed"), ("Quantum-safe assets", "quantum_safe"),
                       ("Quantum-safe coverage (%)", "coverage_pct"), ("Critical (AI)", "critical"),
                       ("High + Critical (AI)", "high_critical"), ("Average AI risk score", "mean_ai_score")]:
        d = round(a[key] - b[key], 1)
        rows.append([label, b[key], a[key], f"{d:+}" if d else "0"])
    s.append(_table(rows, [W * 0.46, W * 0.18, W * 0.18, W * 0.18]))

    s.append(Paragraph("Readiness checks", h2))
    rows = [["Check", "Score"]] + [[i["title"], "n/a" if i["score"] is None else f"{i['score']}%"] for i in readiness["items"]]
    s.append(_table(rows, [W * 0.8, W * 0.2]))
    s.append(Paragraph(_esc(readiness["note"]), small))

    s.append(PageBreak())
    s.append(Paragraph("Top 10 risks now", h2))
    rows = [["Asset", "Service", "Cloud", "Algorithm", "AI risk", "Dependants"]]
    for r in report["top_risks"]:
        rows.append([r["asset_id"], r["service_label"], r["cloud"], r["algorithm"], f"{r['ai_class']} ({r['ai_score']:.0f})",
                     r["dependents"]])
    s.append(_table(rows, [W * 0.2, W * 0.2, W * 0.1, W * 0.22, W * 0.16, W * 0.12]))

    s.append(Paragraph("Migration plan", h2))
    rows = [["Wave", "Assets", "Effort points", "Approx. person-days"]]
    rows += [[w["name"], w["assets"], w["effort_points"], w["person_days"]] for w in plan["waves"]]
    s.append(_table(rows, [W * 0.3, W * 0.2, W * 0.25, W * 0.25]))
    s.append(Paragraph(f"Assumption: {plan['points_per_person_day']} effort points are about one person-day.", small))
    rows = [["#", "Asset", "Now", "Move to", "Standard", "Priority"]]
    rows += [[q["rank"], q["asset_id"], q["algorithm"], q["target"], q["standard"], q["priority"]] for q in plan["queue"][:15]]
    s.append(Spacer(1, 4))
    s.append(_table(rows, [W * 0.06, W * 0.19, W * 0.17, W * 0.22, W * 0.24, W * 0.12]))

    dls = report.get("deadlines")
    if dls:
        c = dls["counts"]
        s.append(Paragraph("Quantum deadlines (Mosca's theorem)", h2))
        s.append(Paragraph(
            f"Assuming a quantum computer able to break RSA and ECC arrives in 2038 (expert median range), "
            f"<b>{c['late']}</b> asset(s) should already be migrating, <b>{c['urgent']}</b> must start within 12 months "
            f"and <b>{c['soon']}</b> within 3 years. {dls['harvest_risk']} asset(s) carry data that could be recorded "
            f"today and decrypted later. Each deadline is: data secrecy lifetime + migration time must end before the "
            f"quantum computer arrives, and never later than NIST's 2035 cut-off for RSA and ECC.", body))
        rows = [["Asset", "Algorithm", "Upgrade by", "Start by", "Status"]]
        rows += [[d["asset_id"], d["algorithm"], d["finish_by"] or "-", d["start_by"] or "-", d["status"]]
                 for d in report.get("deadline_items", [])]
        s.append(_table(rows, [W * 0.3, W * 0.22, W * 0.15, W * 0.15, W * 0.18]))

    if history:
        s.append(Paragraph("Migration history", h2))
        rows = [["When (UTC)", "Action", "Asset", "Change", "By"]]
        for h in history[:25]:
            rows.append([h["created_at"][:16].replace("T", " "), h["action"], h["asset_id"],
                         f"{h['from_alg'] or ''} -> {h['to_alg'] or ''}" if h["action"] != "reset" else "all assets restored",
                         h["user_email"] or "system"])
        s.append(_table(rows, [W * 0.2, W * 0.12, W * 0.18, W * 0.32, W * 0.18]))

    s.append(KeepTogether([
        Paragraph("Method and limits", h2),
        Paragraph("Risk combines a transparent weighted formula (crypto exposure, data sensitivity, retention, external "
                  "exposure, dependency impact, business criticality) with a neural network that also reads the dependency "
                  "graph, so exposure inherited from shared keys and certificates is visible. Migration validation checks "
                  "are policy checks based on published NIST parameter sizes; they are not a live handshake test. "
                  "Readiness is indicative and is not a certification.", body),
    ]))
    doc.build(s, onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()
