"""P8 study: in real public configuration, is post-quantum key exchange actually switched on?

    python -m qmigrate.research.p8_config_pqc.study --clone          # clone the corpus, scan, write results
    python -m qmigrate.research.p8_config_pqc.study --dir /path/to/clones

Writes to qmigrate/research/p8_config_pqc/results/:
    corpus.json   every repository with the exact commit that was scanned
    findings.csv  one row per setting (or missing setting) found, with a GitHub link to the line
    summary.json  the numbers behind the report
    summary.md    the report
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from qmigrate.research.p8_config_pqc import corpus, rules
from qmigrate.research.p8_config_pqc.scanner import Finding, scan_tree

RESULTS = Path(__file__).resolve().parent / "results"
GROUPS = {
    "copied_config": ("deploy", "chart", "example"),   # files people deploy or copy into production
    "shipped_code": ("source",),                      # Go code that runs inside the shipped binaries
    "tests_docs": ("test", "docs"),                   # not deployed as such
}
DEPLOYABLE = GROUPS["copied_config"] + GROUPS["shipped_code"]
FIELDS = ["repo", "repo_kind", "commit", "path", "line", "product", "kind", "setting", "values", "class",
          "outcome", "category", "hard_fail_risk", "min_openssl", "same_list_as", "link"]
GUIDELINE_REPO = "mozilla/ssl-config-generator"

# Checked by hand against the files at the pinned commits (links in findings.csv).
OBSERVATIONS = [
    "* **Certbot's Apache plugin** ships `current-options-ssl-apache.conf` with `SSLOpenSSLConfCmd Curves "
    "X25519:prime256v1:secp384r1`. The file says it is based on ssl-config.mozilla.org and that Certbot manages it. "
    "The list is identical to an earlier Mozilla guideline, while Mozilla's newest guideline puts X25519MLKEM768 "
    "first. A server Certbot configured keeps post-quantum off even after OpenSSL is upgraded to 3.5.",
    "* **h5bp server-configs-nginx**, a widely copied nginx boilerplate, pins `ssl_ecdh_curve` to classical lists "
    "in both its balanced and strict policies. That overrides the OpenSSL 3.5 default, which would have offered "
    "ML-KEM.",
    "* **AWS Load Balancer Controller** uses `ELBSecurityPolicy-2016-08` when an Ingress has no `ssl-policy` "
    "annotation (`defaultSSLPolicy` in its Go source), and the Terraform ALB module's examples use "
    "`ELBSecurityPolicy-TLS13-1-2-Res-2021-06`. Neither is a PQ policy. AWS's own console now defaults to "
    "`ELBSecurityPolicy-TLS13-1-2-Res-PQ-2025-09`, but listeners created through the API, CloudFormation or CDK "
    "still default to `ELBSecurityPolicy-2016-08`: the same load balancer gets post-quantum or not depending on "
    "the tool that created it.",
    "* **Compliance modes can switch post-quantum off.** Istio's FIPS 140-2 and 140-3 modes set CurvePreferences "
    "to P-256 (and P-384) only. Only its separate `pqc` policy offers ML-KEM. FIPS and post-quantum are not "
    "exclusive: AWS ships FIPS policies with PQ (for example `ELBSecurityPolicy-TLS13-1-2-FIPS-PQ-2025-09`).",
    "* **Code generators spread pinned lists.** Cilium's four go-swagger-generated API servers all carry "
    "`CurvePreferences: []tls.CurveID{tls.CurveP256}` from the generator template, which replaces Go's default "
    "(the default includes ML-KEM from Go 1.24).",
]


def guideline_lists(checkouts: list[corpus.Checkout]) -> tuple[dict[tuple, list[str]], dict]:
    """Every curve list Mozilla's TLS guidelines ever recommended, keyed by canonical list.
    Many server configs say they are 'based on ssl-config.mozilla.org', so an identical list shows
    which guideline version a config was copied from."""
    by_list: dict[tuple, list[str]] = defaultdict(list)
    newest: dict = {}
    for c in checkouts:
        if c.repo != GUIDELINE_REPO or c.error:
            continue
        files = sorted((c.path / "docs" / "guidelines").glob("[0-9]*.json"),
                       key=lambda p: tuple(int(x) for x in p.stem.split(".")))
        for f in files:
            try:
                confs = json.loads(f.read_text()).get("configurations", {})
            except (OSError, ValueError):
                continue
            for name, conf in confs.items():
                curves = conf.get("tls_curves") or []
                if curves:
                    by_list[rules.canonical_list(curves)].append(f"Mozilla {f.stem} {name}")
            if files and f == files[-1]:
                newest = {"version": f.stem, "lists": {k: v.get("tls_curves") for k, v in confs.items()}}
    return by_list, newest


def _rel(f: Finding, repo: str) -> str:
    return f.path[len(repo) + 1:] if f.path.startswith(repo + "/") else f.path


def to_rows(checkouts: list[corpus.Checkout], guide: dict | None = None) -> tuple[list[dict], list[dict]]:
    guide = guide or {}
    rows, manifest = [], []
    for c in checkouts:
        entry = {"repo": c.repo, "kind": c.kind, "commit": c.sha, "files_scanned": 0, "error": c.error}
        if not c.error:
            findings, n = scan_tree(c.path, label=c.repo)
            entry["files_scanned"] = n
            for f in findings:
                rel = _rel(f, c.repo)
                rows.append({
                    "repo": c.repo, "repo_kind": c.kind, "commit": c.sha, "path": rel, "line": f.line,
                    "product": f.product, "kind": f.kind, "setting": f.setting, "values": " ".join(f.values),
                    "class": f.cls, "outcome": rules.outcome(f.product, f.kind, f.cls), "category": f.category,
                    "hard_fail_risk": int(f.hard_fail_risk), "min_openssl": f.min_openssl,
                    "same_list_as": ("" if f.kind != "explicit" or f.product == "guideline" else
                                     " / ".join(guide.get(rules.canonical_list(f.values), [])[-2:])),
                    "link": f"https://github.com/{c.repo}/blob/{c.sha}/{rel}#L{f.line}",
                })
        manifest.append(entry)
    return rows, manifest


def _pct(a: int, b: int) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


def summarise(rows: list[dict], manifest: list[dict], newest_guideline: dict | None = None) -> dict:
    # guideline data (Mozilla's recommended lists) is a reference, not a server setting
    explicit = [r for r in rows if r["kind"] == "explicit" and r["product"] != "guideline"]
    deployable = [r for r in rows if r["category"] in DEPLOYABLE]
    exp_dep = [r for r in explicit if r["category"] in DEPLOYABLE]
    readable = [r for r in exp_dep if r["class"] not in ("unresolved",)]

    by_product = defaultdict(Counter)
    for r in explicit:
        by_product[r["product"]][r["class"]] += 1
    by_category = defaultdict(Counter)
    for r in explicit:
        by_category[r["category"]][r["class"]] += 1
    per_repo = {}
    for m in manifest:
        rr = [r for r in rows if r["repo"] == m["repo"]]
        e = [r for r in rr if r["kind"] == "explicit" and r["product"] != "guideline"]
        per_repo[m["repo"]] = {
            "kind": m["kind"], "commit": m["commit"][:12], "files": m["files_scanned"],
            "explicit": len(e),
            "pq_enabled": sum(r["class"] in ("pq_enabled", "pq_mesh_policy") for r in e),
            "pq_excluded": sum(r["class"] == "pq_excluded" for r in e),
            "defaults": sum(r["kind"] == "default" for r in rr), "error": m["error"],
        }

    groups = {}
    for g, cats in GROUPS.items():
        ex = [r for r in explicit if r["category"] in cats]
        rd = [r for r in ex if r["class"] != "unresolved"]
        groups[g] = {
            "explicit": len(ex), "readable": len(rd),
            "pq_enabled": sum(r["class"] in ("pq_enabled", "pq_mesh_policy") for r in rd),
            "pq_excluded": sum(r["class"] == "pq_excluded" for r in rd),
            "no_setting": sum(1 for r in rows if r["kind"] == "default" and r["category"] in cats),
        }
        groups[g]["pinned_classical_pct"] = _pct(groups[g]["pq_excluded"], len(rd))

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "groups": groups,
        "repositories": len(manifest),
        "repositories_scanned": sum(1 for m in manifest if not m["error"]),
        "files_scanned": sum(m["files_scanned"] for m in manifest),
        "findings": len(rows),
        "explicit_settings": len(explicit),
        "explicit_by_class": dict(Counter(r["class"] for r in explicit)),
        "explicit_deployable": len(exp_dep),
        "explicit_deployable_by_class": dict(Counter(r["class"] for r in exp_dep)),
        "explicit_deployable_readable": len(readable),
        "pinned_classical_deployable": sum(r["class"] == "pq_excluded" for r in readable),
        "pq_enabled_deployable": sum(r["class"] in ("pq_enabled", "pq_mesh_policy") for r in readable),
        "pinned_classical_share_of_readable_deployable": _pct(
            sum(r["class"] == "pq_excluded" for r in readable), len(readable)),
        "pq_enabled_share_of_readable_deployable": _pct(
            sum(r["class"] in ("pq_enabled", "pq_mesh_policy") for r in readable), len(readable)),
        "deployable_outcomes": dict(Counter(r["outcome"] for r in deployable)),
        "hard_fail_risk": sum(r["hard_fail_risk"] for r in rows),
        "hard_fail_risk_deployable": sum(r["hard_fail_risk"] for r in deployable),
        "explicit_by_product": {p: dict(c) for p, c in sorted(by_product.items())},
        "explicit_by_category": {k: dict(c) for k, c in sorted(by_category.items())},
        "per_repo": per_repo,
        "newest_mozilla_guideline": newest_guideline or {},
        "pinned_copied_from_older_guideline": [
            {"repo": r["repo"], "path": r["path"], "line": int(r["line"]), "values": r["values"],
             "same_list_as": r["same_list_as"], "link": r["link"]}
            for r in rows if r["class"] == "pq_excluded" and r["same_list_as"] and r["product"] != "guideline"],
    }


def _table(head: list[str], body: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return "\n".join(out)


def report(s: dict, rows: list[dict]) -> str:
    cls_cols = ["pq_enabled", "pq_excluded", "draft_only", "auto", "unresolved", "pq_mesh_policy"]
    lines = [
        "# P8 · Supported is not switched on",
        "",
        f"Scan date {s['generated']}. {s['repositories_scanned']} public repositories, "
        f"{s['files_scanned']:,} configuration and Go files, {s['findings']:,} findings. "
        "Every repository is pinned to the commit in `corpus.json`; every finding links to its line in `findings.csv`.",
        "",
        "## Headline",
        "",
        f"* **{s['explicit_settings']}** places set the TLS key-exchange groups explicitly; "
        f"**{s['explicit_deployable']}** of them are in configuration people deploy or copy, or in shipped Go code.",
        f"* Of the {s['explicit_deployable_readable']} that can be read, **{s['pinned_classical_deployable']}** "
        f"({s['pinned_classical_share_of_readable_deployable']}%) pin a classical-only list. On those endpoints "
        "post-quantum key exchange stays off even after the software is upgraded to a version that supports ML-KEM.",
        f"* **{s['pq_enabled_deployable']}** ({s['pq_enabled_share_of_readable_deployable']}%) include a hybrid "
        "ML-KEM group.",
        f"* **{s['hard_fail_risk']}** nginx, HAProxy or Apache settings name an ML-KEM group. Such a list is "
        "rejected, and the server does not start, on OpenSSL 3.0–3.4 (3.0–3.2 even with the `?` prefix).",
        "",
        "The numbers are small because most projects never set the groups at all (the \"No setting\" column): "
        "for them the product default decides, which is why the defaults table at the end matters as much as "
        "the pinned lists.",
        "",
        _table(["Where", "Explicit settings", "Readable", "PQ on", "Pinned classical", "Pinned %", "No setting"],
               [[{"copied_config": "Configs, charts, examples", "shipped_code": "Shipped Go code",
                  "tests_docs": "Tests and docs"}[g], v["explicit"], v["readable"], v["pq_enabled"],
                 v["pq_excluded"], f"{v['pinned_classical_pct']}%", v["no_setting"]]
                for g, v in s["groups"].items()]),
        "",
        "## Observations",
        "",
        *OBSERVATIONS,
        "",
        "## What TLS endpoints outside tests and docs get",
        "",
        "Explicit settings and TLS configurations with no setting (where the product default decides) together. "
        "Go `tls.Config` values include clients as well as servers:",
        "",
        _table(["Outcome", "Findings"], [[rules.OUTCOME_TEXT.get(k, k), v] for k, v in
                                         sorted(s["deployable_outcomes"].items(), key=lambda kv: -kv[1])]),
        "",
        "## Explicit settings by product",
        "",
        _table(["Product", *cls_cols, "Default without a setting"],
               [[p, *[c.get(k, 0) for k in cls_cols], rules.DEFAULTS.get(p, {}).get("pq_default", "")]
                for p, c in s["explicit_by_product"].items()]),
        "",
        "## Explicit settings by file category",
        "",
        "Categories come from the file path (tests/, docs/, examples/, charts/ ...).",
        "",
        _table(["Category", *cls_cols], [[k, *[c.get(x, 0) for x in cls_cols]]
                                         for k, c in s["explicit_by_category"].items()]),
        "",
        "## Per repository",
        "",
        _table(["Repository", "Kind", "Commit", "Files", "Explicit", "PQ on", "Pinned classical", "No setting"],
               [[r, v["kind"], f"`{v['commit']}`", v["files"], v["explicit"], v["pq_enabled"], v["pq_excluded"],
                 v["defaults"]] for r, v in s["per_repo"].items()]),
        "",
        "## Examples of pinned classical lists outside tests and docs",
        "",
    ]
    pinned = [r for r in rows if r["class"] == "pq_excluded" and r["category"] in DEPLOYABLE]
    seen = set()
    for r in pinned:
        key = (r["repo"], r["values"])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"* [{r['repo']}/{r['path']}:{r['line']}]({r['link']}) · {r['product']} · `{r['values'][:80]}`")
        if len(seen) >= 20:
            break
    ng = s.get("newest_mozilla_guideline") or {}
    copied = s.get("pinned_copied_from_older_guideline") or []
    if ng:
        lines += [
            "",
            "## Copied from an older guideline",
            "",
            f"Mozilla's TLS guideline {ng['version']} recommends "
            + "; ".join(f"{k}: `{':'.join(v or [])}`" for k, v in ng["lists"].items() if v)
            + ". Pinned lists that are identical to an earlier Mozilla recommendation were most likely copied "
              "from it and never updated:",
            "",
        ]
        lines += [f"* [{c['repo']}/{c['path']}:{c['line']}]({c['link']}) · `{c['values']}` = {c['same_list_as']}"
                  for c in copied] or ["* none found"]
    lines += [
        "",
        "## Product defaults used",
        "",
        _table(["Product", "Without a setting", "Source"],
               [[p, d["pq_default"], d["source"]] for p, d in rules.DEFAULTS.items()]),
        "",
        "## Limits",
        "",
        "* The scanner reads text. It does not render Helm templates or resolve variables, so templated values are "
        "counted as unresolved and left out of the percentages.",
        "* A setting in a repository is not a running server. The study measures what people are given to copy, "
        "and the companion live measurement (Discovery) measures what servers negotiate.",
        "* Go and Go-based products switch ML-KEM on by default only when built with Go 1.24 or newer; "
        "the scan cannot see the toolchain a binary was built with.",
        "* File categories are inferred from paths and can be wrong for unusual layouts.",
    ]
    return "\n".join(lines) + "\n"


def run(base: Path, clone: bool, refresh: bool, out: Path) -> dict:
    if clone:
        checkouts = corpus.fetch_all(base, refresh=refresh)
    else:
        checkouts = [corpus.Checkout(r, k, base / r.replace("/", "__"), "", "") for r, k in corpus.REPOS]
        for c in checkouts:
            if (c.path / ".git").exists():
                c.sha = corpus._git("rev-parse", "HEAD", cwd=c.path)
            else:
                c.error = "not cloned"
    guide, newest = guideline_lists(checkouts)
    rows, manifest = to_rows(checkouts, guide)
    s = summarise(rows, manifest, newest)
    out.mkdir(parents=True, exist_ok=True)
    (out / "corpus.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with (out / "findings.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    (out / "summary.json").write_text(json.dumps(s, indent=2) + "\n")
    (out / "summary.md").write_text(report(s, rows))
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, default=corpus.default_dir(), help="where the clones live")
    ap.add_argument("--clone", action="store_true", help="clone missing repositories first")
    ap.add_argument("--refresh", action="store_true", help="update existing clones to the newest commit")
    ap.add_argument("--out", type=Path, default=RESULTS)
    a = ap.parse_args(argv)
    s = run(a.dir, a.clone or a.refresh, a.refresh, a.out)
    print(json.dumps({k: s[k] for k in ("repositories_scanned", "files_scanned", "explicit_settings",
                                        "explicit_deployable", "pinned_classical_share_of_readable_deployable",
                                        "pq_enabled_share_of_readable_deployable", "hard_fail_risk")}, indent=2))


if __name__ == "__main__":
    main()
