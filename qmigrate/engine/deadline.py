"""Quantum deadline for each asset, from Mosca's theorem.

Mosca's inequality (M. Mosca, "Cybersecurity in an era with quantum computers: will we be ready?",
IEEE Security & Privacy, 2018):

    if  X + Y > Z  the data is at risk

    X = how many years the data must stay secret (shelf life)
    Y = how many years the migration to quantum-safe cryptography takes
    Z = how many years until a cryptographically relevant quantum computer (CRQC) exists

So an asset must FINISH its migration by  (CRQC year - X), and START it by  (finish year - Y).
Anything an attacker records before the finish year ("harvest now, decrypt later") could still be
secret when the quantum computer arrives.

Z comes from expert estimates, not from us:
  * Mosca & Piani, "Quantum Threat Timeline Report 2025", Global Risk Institute / evolutionQ (26 experts):
    a CRQC within 10 years is 28-49 % likely on average; within 15 years 69 % of experts say 50 % or more;
    within 20 years 92 % say 50 % or more.
  * NIST IR 8547 (final, 2026): RSA / ECC deprecated after 2030 and disallowed after 2035, at every strength.
The finish year is never later than the NIST "disallowed" year, so the deadline is
min(CRQC year - X, 2035).

Y is an estimate built from the platform's migration effort points (catalog.MIGRATION_EFFORT), the
number of systems that depend on the asset, and whether its clients already support PQC. Every number
used is returned with the result so it can be checked and changed.
"""
from __future__ import annotations

import math
from datetime import date

from qmigrate.engine.catalog import ALGORITHMS, MIGRATION_EFFORT

# Year a CRQC is assumed to exist, per scenario. "expected" is where most experts in the 2025
# timeline report put the odds above 50 % (between the 10- and 15-year horizons).
SCENARIOS = {
    "cautious": {"crqc_year": 2033, "label": "Cautious (CRQC in 2033)",
                 "source": "Upper end of the 10-year expert estimate (28-49 % by ~2035), risk-averse planning"},
    "expected": {"crqc_year": 2038, "label": "Expected (CRQC in 2038)",
                 "source": "Between the 10- and 15-year horizons, where most experts put the odds above 50 %"},
    "late": {"crqc_year": 2045, "label": "Late (CRQC in 2045)",
             "source": "20-year horizon: 92 % of experts put the odds at 50 % or more"},
}
DEFAULT_SCENARIO = "expected"
NIST_DEPRECATED_AFTER = 2030
NIST_DISALLOWED_AFTER = 2035

# Migration time model (years): base + effort share + coordination with dependants + waiting for clients.
BASE_YEARS = 0.5
EFFORT_YEARS = 2.5          # an effort of 100 points adds 2.5 years
COORDINATION_YEARS = 0.25   # per doubling of the number of dependants, capped below
COORDINATION_CAP = 1.0
CLIENT_WAIT_YEARS = 1.0     # clients (browsers, partners, devices) do not support PQC yet

CONFIDENTIALITY = {"key_exchange", "key_wrapping", "data_encryption"}


def current_year() -> float:
    d = date.today()
    return d.year + (d.timetuple().tm_yday - 1) / 365.25


def migration_years(service_type: str, dependents: int, clients_support_pqc: bool) -> dict:
    effort = MIGRATION_EFFORT.get(service_type, 50)
    coord = min(COORDINATION_YEARS * math.log2(1 + max(dependents, 0)), COORDINATION_CAP)
    wait = 0.0 if clients_support_pqc else CLIENT_WAIT_YEARS
    total = BASE_YEARS + EFFORT_YEARS * effort / 100 + coord + wait
    return {"years": round(total, 1), "effort_points": effort, "coordination_years": round(coord, 2),
            "client_wait_years": wait}


def shelf_life(row: dict) -> float:
    """X: years the protected data or trust must last. For confidentiality this is the data's
    retention (harvest now, decrypt later). For signatures it is how long the signature must be
    trusted (certificate validity left); forging needs a quantum computer that already exists."""
    return float(max(row.get("retention_years") or 0, 0))


def status_of(start_by: float, now: float) -> str:
    if start_by < now:
        return "late"
    if start_by < now + 1:
        return "urgent"
    if start_by < now + 3:
        return "soon"
    return "planned"


STATUS_TEXT = {
    "late": "Late: the migration should already have started",
    "urgent": "Urgent: start within 12 months",
    "soon": "Soon: start within 3 years",
    "planned": "Planned: time is still available",
    "safe": "Already quantum-safe",
    "classical": "Weak today against classical attacks: replace now",
    "review": "Review: Grover's algorithm halves its strength",
}
STATUS_ORDER = ["late", "urgent", "soon", "planned", "classical", "review", "safe"]


def deadline_for(row: dict, rows: dict, scenario: str = DEFAULT_SCENARIO, now: float | None = None) -> dict:
    """Deadline for one asset view row (Estate.view rows). `rows` gives access to the asset whose
    weak key or certificate this one inherits its exposure from."""
    now = current_year() if now is None else now
    sc = SCENARIOS[scenario]
    alg = ALGORITHMS[row["algorithm"]]
    base = {"scenario": scenario, "crqc_year": sc["crqc_year"]}
    if not row["quantum_exposed"]:
        if alg["status"] == "legacy-weak":
            return {**base, "status": "classical", "text": STATUS_TEXT["classical"], "finish_by": int(now),
                    "start_by": int(now), "years_left": 0.0, "fix_asset": row["asset_id"]}
        status = "review" if row["algorithm"] == "AES-128" else "safe"
        return {**base, "status": status, "text": STATUS_TEXT[status], "finish_by": None, "start_by": None,
                "years_left": None, "fix_asset": None}

    # The asset to change: itself, or the weak key / certificate it relies on.
    fix = row["asset_id"]
    if not alg["quantum_vulnerable"] and row.get("inherited_from") in rows:
        fix = row["inherited_from"]
    f = rows[fix]
    y = migration_years(f["service_type"], f["dependents"], f["clients_support_pqc"])
    x = shelf_life(row)
    mosca_finish = sc["crqc_year"] - x
    finish = min(mosca_finish, NIST_DISALLOWED_AFTER)
    driver = "mosca" if mosca_finish <= NIST_DISALLOWED_AFTER else "nist"
    start = finish - y["years"]
    status = status_of(start, now)
    return {
        **base,
        "status": status, "text": STATUS_TEXT[status],
        "finish_by": int(math.floor(finish)), "start_by": int(math.floor(start)),
        "years_left": round(start - now, 1),
        "shelf_life_years": round(x, 1), "migration_years": y["years"], "migration": y,
        "driver": driver, "fix_asset": fix,
        "harvest_risk": bool(row["usage"] in CONFIDENTIALITY and x + y["years"] > sc["crqc_year"] - now),
    }


def sentence(d: dict, row: dict) -> str:
    """One plain-language line for the dashboard's reasons list."""
    if d["status"] in ("safe", "review"):
        return ""
    if d["status"] == "classical":
        return f"Quantum deadline: replace {row['algorithm']} now; it is already weak without a quantum computer."
    fix = "" if d["fix_asset"] == row["asset_id"] else f" (by upgrading {d['fix_asset']})"
    why = (f"its data must stay secret for {d['shelf_life_years']:g} years and the change takes about "
           f"{d['migration_years']:g} years" if d["driver"] == "mosca"
           else f"NIST disallows RSA and ECC after {NIST_DISALLOWED_AFTER} and the change takes about {d['migration_years']:g} years")
    if d["status"] == "late" and d["finish_by"] < int(current_year()):
        act = "Upgrade now" if d["fix_asset"] == row["asset_id"] else f"Upgrade {d['fix_asset']} now"
        return (f"Quantum deadline: overdue. Its data must stay secret for {d['shelf_life_years']:g} years, so data "
                f"recorded today could still matter when a quantum computer may exist ({d['crqc_year']}). {act}; "
                f"the change takes about {d['migration_years']:g} years.")
    when = "should already have started" if d["status"] == "late" else f"must start by {d['start_by']}"
    return (f"Quantum deadline: upgrade by {d['finish_by']}{fix}. If a quantum computer arrives in {d['crqc_year']}, "
            f"{why}, so the work {when}.")


def summarize(deadlines: dict[str, dict]) -> dict:
    counts = {s: 0 for s in STATUS_ORDER}
    for d in deadlines.values():
        counts[d["status"]] += 1
    dated = [d for d in deadlines.values() if d.get("finish_by") is not None and d["status"] not in ("classical",)]
    return {"counts": counts, "earliest_finish_by": min((d["finish_by"] for d in dated), default=None),
            "harvest_risk": sum(bool(d.get("harvest_risk")) for d in deadlines.values())}


def assumptions() -> dict:
    return {
        "formula": "finish_by = min(CRQC year - X, NIST disallow year); start_by = finish_by - Y",
        "x": "X = years the data must stay secret (retention) or the signature must be trusted",
        "y": (f"Y = {BASE_YEARS} + {EFFORT_YEARS} x effort/100 + {COORDINATION_YEARS} x log2(1 + dependants) "
              f"(max {COORDINATION_CAP}) + {CLIENT_WAIT_YEARS} if clients do not support PQC yet"),
        "scenarios": SCENARIOS,
        "nist": {"deprecated_after": NIST_DEPRECATED_AFTER, "disallowed_after": NIST_DISALLOWED_AFTER,
                 "source": "NIST IR 8547, Transition to Post-Quantum Cryptography Standards"},
        "sources": [
            "M. Mosca, Cybersecurity in an era with quantum computers: will we be ready? IEEE Security & Privacy 16(5), 2018",
            "M. Mosca, M. Piani, Quantum Threat Timeline Report 2025, Global Risk Institute / evolutionQ",
            "NIST IR 8547, Transition to Post-Quantum Cryptography Standards",
        ],
    }
