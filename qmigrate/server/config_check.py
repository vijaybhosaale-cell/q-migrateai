"""Config check: paste or upload TLS configuration and see whether post-quantum key exchange is switched on.

Uses the P8 scanner (qmigrate/research/p8_config_pqc). Nothing is executed or fetched: the text is
read line by line. File contents are not stored; only the findings (with a one-line snippet) are kept
for the company, and they are included in the GDPR export and deleted with the company.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from qmigrate.research.p8_config_pqc import rules
from qmigrate.research.p8_config_pqc.scanner import scan_text

MAX_FILES = 20
MAX_FILE_CHARS = 200_000
MAX_TOTAL_CHARS = 1_000_000
STUDY_SUMMARY = Path(__file__).resolve().parents[1] / "research" / "p8_config_pqc" / "results" / "summary.json"

# Outcomes from worst to best, for sorting and the overall verdict.
ORDER = ["off_pinned", "off_draft", "off_default", "unknown", "depends_library", "on_if_go124", "on"]


def safe_name(name: str) -> str:
    base = re.split(r"[\\/]", name.strip())[-1] or "config"
    return re.sub(r"[^A-Za-z0-9._ -]", "_", base)[:120]


def check(files: list[dict]) -> dict:
    """files: [{"name": "nginx.conf", "text": "..."}]. Returns findings, counts and a verdict."""
    findings = []
    names = []
    for f in files:
        name = safe_name(f.get("name") or "config")
        names.append(name)
        for x in scan_text(name, f.get("text") or ""):
            out = rules.outcome(x.product, x.kind, x.cls)
            findings.append({
                "file": name, "line": x.line, "product": x.product, "kind": x.kind, "setting": x.setting,
                "values": x.values, "class": x.cls, "outcome": out,
                "outcome_text": rules.OUTCOME_TEXT.get(out, out),
                "advice": rules.advice(x.product, x.kind, x.cls, x.values),
                "min_openssl": x.min_openssl, "snippet": x.snippet[:200],
                "default_source": rules.DEFAULTS.get(x.product, {}).get("source", "") if x.kind == "default" else "",
            })
    findings.sort(key=lambda r: (ORDER.index(r["outcome"]) if r["outcome"] in ORDER else 99, r["file"], r["line"]))
    counts = dict(Counter(r["outcome"] for r in findings))
    if not findings:
        verdict = "nothing_found"
    elif any(r["outcome"] in ("off_pinned", "off_draft", "off_default") for r in findings):
        verdict = "pq_off"
    elif all(r["outcome"] == "on" for r in findings):
        verdict = "pq_on"
    else:
        verdict = "depends"
    breakage = sum(1 for r in findings if r["min_openssl"])
    return {"files": names, "findings": findings, "summary": {"counts": counts, "verdict": verdict,
                                                              "findings": len(findings), "breakage_risk": breakage}}


def study_headline() -> dict | None:
    """The public-repository study behind this check (results committed with the code)."""
    try:
        s = json.loads(STUDY_SUMMARY.read_text())
    except (OSError, ValueError):
        return None
    keep = ("generated", "repositories_scanned", "files_scanned", "explicit_settings", "explicit_deployable",
            "explicit_deployable_readable", "pinned_classical_deployable", "pinned_classical_share_of_readable_deployable",
            "pq_enabled_deployable", "groups")
    return {k: s.get(k) for k in keep} | {"defaults": rules.DEFAULTS}
