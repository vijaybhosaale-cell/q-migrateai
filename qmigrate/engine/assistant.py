"""AI assistant: answers questions in plain language from the platform's own data.

It is deliberately grounded and rule-based: it recognises the question's intent
and asset IDs, then builds the answer from the explanation, queue, what-if and
readiness APIs. It never invents numbers. (A large language model could be
plugged in later to rephrase these grounded answers.)
"""
from __future__ import annotations

import re

from qmigrate.engine.estate import Estate

ASSET_RE = re.compile(r"\b([A-Za-z]{2,6}-[A-Za-z]{2,6}-\d{3})\b")

GLOSSARY = {
    "ml-kem": "ML-KEM (FIPS 203) is NIST's post-quantum key-encapsulation standard, used to agree on session keys. "
              "In a hybrid such as X25519 + ML-KEM-768 the connection stays safe as long as either part is unbroken.",
    "ml-dsa": "ML-DSA (FIPS 204) is NIST's main post-quantum digital-signature standard, for certificates, tokens and code.",
    "slh-dsa": "SLH-DSA (FIPS 205) is a hash-based post-quantum signature. It is very conservative but has large "
               "signatures, so it suits long-lived code signing more than TLS.",
    "hybrid": "A hybrid combines a classical algorithm with a post-quantum one, so security holds if either is unbroken. "
              "It is the usual first step because older clients can still fall back to the classical half.",
    "harvest": "Harvest now, decrypt later: an attacker records encrypted traffic or data today and decrypts it once a "
               "large quantum computer exists. Long-lived sensitive data is therefore already at risk.",
    "rollback": "Every migration in the platform stores the previous policy, so one click restores it. "
                "This is crypto-agility: changing algorithms without rebuilding systems.",
}


def _fmt_reasons(reasons: list[str], limit: int = 4) -> str:
    return "\n".join(f"- {r}" for r in reasons[:limit])


def answer(est: Estate, question: str, readiness: dict | None = None) -> dict:
    q = question.strip()
    ql = q.lower()
    refs: list[str] = []

    ids = [m.upper() for m in ASSET_RE.findall(q)]
    known = [i for i in ids if i in est.current]
    if ids and not known:
        return {"answer": f"I could not find {', '.join(ids)} in your inventory. Check the ID on the Assets page.",
                "references": [], "suggestions": ["What should we migrate first?"]}
    if known:
        aid = known[0]
        x = est.explain(aid)
        a, ai, rule = x["asset"], x["ai"], x["rule"]
        rec = x["recommendation"]
        text = (f"**{aid}** ({a['service_label']}, {a['cloud']}) is rated **{ai['class']}** by the neural network "
                f"(confidence {round(100 * ai['confidence'])}%) and scores {rule['score']:.0f}/100 on the rule-based formula.\n\n"
                f"Why:\n{_fmt_reasons(x['reasons'])}")
        if rec:
            text += f"\n\nRecommended: move from {a['algorithm']} to **{rec['target']}** ({rec['standard']})."
        else:
            text += f"\n\n{a['algorithm']} is already quantum-safe; no migration is needed for this asset itself."
        deps = len(x["dependents"]["all"])
        if deps:
            text += f" {deps} assets depend on it."
        return {"answer": text, "references": [aid],
                "suggestions": [f"What if we migrate the top 10?", "What should we migrate first?"]}

    for key, text in GLOSSARY.items():
        if key in ql or (key == "harvest" and "hndl" in ql):
            return {"answer": text, "references": [], "suggestions": ["Why is the top asset critical?"]}

    m = re.search(r"\b(?:top|first)\s+(\d{1,3})\b", ql)
    if ("what if" in ql or "what-if" in ql or "if we migrate" in ql) or (m and "migrate" in ql and "what" in ql):
        n = int(m.group(1)) if m else 20
        curve = est.whatif_curve(max(n, 1))
        base, pt = curve[0], curve[min(n, len(curve) - 1)]
        text = (f"If you migrate the top {pt['n']} assets of the current plan:\n"
                f"- quantum-exposed assets: {base['quantum_exposed']} → {pt['quantum_exposed']}\n"
                f"- quantum-safe coverage: {base['coverage_pct']}% → {pt['coverage_pct']}%\n"
                f"- Critical assets: {base['critical']} → {pt['critical']}\n"
                f"- estimated effort: {pt['effort_points']} points (about {pt['person_days']} person-days, "
                f"assuming 10 points per person-day).")
        return {"answer": text, "references": [], "suggestions": ["What should we migrate first?"]}

    if any(w in ql for w in ("first", "priority", "prioritise", "prioritize", "start", "next")):
        top = est.queue()[:5]
        if not top:
            return {"answer": "Nothing is left to migrate: every asset is on a quantum-safe policy.", "references": [],
                    "suggestions": []}
        lines = [f"{t['rank']}. **{t['asset_id']}** ({t['service_label']}): {t['algorithm']} → {t['target']}, "
                 f"{t['dependents']} dependants, AI risk {t['ai_class']}" for t in top]
        refs = [t["asset_id"] for t in top]
        return {"answer": "Migrate these first (highest priority):\n" + "\n".join(lines) +
                "\n\nShared keys and certificate authorities come first because fixing one protects everything that depends on it.",
                "references": refs, "suggestions": [f"Why is {refs[0]} critical?"]}

    if "critical" in ql or "riskiest" in ql or "most risk" in ql or "highest risk" in ql:
        rows = sorted(est.view["rows"].values(), key=lambda r: -r["ai_score"])
        r = rows[0]
        return answer(est, f"Why is {r['asset_id']} critical?", readiness)

    if readiness is not None and any(w in ql for w in ("readiness", "nist", "compliance", "ready")):
        lines = [f"- {i['title']}: {'n/a' if i['score'] is None else str(i['score']) + '%'}" for i in readiness["items"]]
        return {"answer": f"Indicative post-quantum readiness: **{readiness['overall']}%**.\n" + "\n".join(lines) +
                "\n\n" + readiness["note"], "references": [], "suggestions": ["What should we migrate first?"]}

    if any(w in ql for w in ("how many", "status", "overview", "exposed", "summary", "safe")):
        k = est.overview()["now"]
        return {"answer": (f"You have **{k['total_assets']}** cryptographic assets. {k['quantum_exposed']} are "
                           f"quantum-exposed, {k['quantum_safe']} are quantum-safe ({k['coverage_pct']}%), and the AI "
                           f"rates {k['critical']} as Critical."),
                "references": [], "suggestions": ["What should we migrate first?", "What is our NIST readiness?"]}

    return {"answer": ("I can answer questions about your own inventory, for example:\n"
                       "- Why is AWS-KMS-004 critical?\n- What should we migrate first?\n"
                       "- What if we migrate the top 10?\n- How many assets are quantum-exposed?\n"
                       "- What is our NIST readiness?\n- What is ML-KEM?"),
            "references": [], "suggestions": ["What should we migrate first?", "Why is the riskiest asset critical?"]}
