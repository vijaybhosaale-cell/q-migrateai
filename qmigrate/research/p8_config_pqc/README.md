# P8 · Supported is not switched on

**Question.** Hybrid post-quantum key exchange (X25519MLKEM768) is available in Envoy, Istio, Go, OpenSSL 3.5,
nginx, HAProxy, Apache and AWS load balancers. Do the configurations people actually deploy and copy turn it on?

**Why it matters.** Inventory tools count *which software* runs. An upgraded server still negotiates classical
key exchange when its configuration pins a classical group list, or when the product's default leaves ML-KEM out.
In both cases recorded traffic stays open to "harvest now, decrypt later". Upgrading the software does not fix it.

## What is in this folder

| File | What it does |
|---|---|
| `rules.py` | Group names, the classification of a group list, every product's default (with a source link), the OpenSSL breakage rule, and the fix for each product |
| `scanner.py` | Reads text files and finds each place that sets key-exchange groups (or a TLS listener that sets none) |
| `corpus.py` | The 37 public repositories studied, cloned shallow and pinned to an exact commit |
| `study.py` | Runs the scan over the corpus and writes `results/` |
| `results/` | `corpus.json` (commits), `findings.csv` (one row per finding, with a GitHub link to the line), `summary.json`, `summary.md` (the report) |

## Reproduce

```bash
python -m qmigrate.research.p8_config_pqc.study --clone        # about 2.3 GB of shallow clones, a few minutes
python -m qmigrate.research.p8_config_pqc.study --dir /path/to/clones
```

`QM_CORPUS_DIR` sets where the clones go (default `~/.cache/qmigrate/p8-corpus`). To re-run on exactly the
commits in `results/corpus.json`, check out each listed commit before running `--dir`.

## What the scanner recognises

| Product | Explicit setting | No setting (default) |
|---|---|---|
| Envoy | `ecdh_curves` | `DownstreamTlsContext` without it: off |
| Envoy Gateway | `ClientTrafficPolicy tls.ecdhCurves` | off |
| Istio | `meshConfig.tlsDefaults.ecdhCurves`, `COMPLIANCE_POLICY=pqc` | off |
| nginx, ingress-nginx | `ssl_ecdh_curve`, `ssl-ecdh-curve` | `listen ... ssl` without it: OpenSSL default |
| HAProxy | `ssl-default-bind-curves`, `curves` on `bind` | OpenSSL default |
| Apache | `SSLOpenSSLConfCmd Curves/Groups` | `SSLEngine on` without it: OpenSSL default |
| Go, Caddy, Traefik | `CurvePreferences`, `curves`, `curvePreferences` | `tls.Config{}` without it: on from Go 1.24 |
| Java | `jdk.tls.namedGroups` | |
| AWS ELB | `ssl-policy` annotations, Terraform `ssl_policy`, CloudFormation `SslPolicy`, Go defaults | API/IaC default `ELBSecurityPolicy-2016-08`: off |
| Mozilla guideline | `tls_curves` in ssl-config-generator data (reference only) | |

Each explicit list is classed as `pq_enabled`, `pq_excluded` (classical only), `draft_only` (withdrawn Kyber
draft), `auto` or `unresolved` (template or variable, left out of the percentages).

## Things this adds that inventory scanners do not report

1. **Effective outcome, not presence.** Each finding is combined with the product's sourced default, so one
   report says whether that endpoint negotiates ML-KEM: on, off because the list is pinned, off because of the
   default, or dependent on the OpenSSL or Go version.
2. **Breakage before rollout.** Naming ML-KEM in nginx, HAProxy or Apache stops the server from starting on
   OpenSSL 3.0–3.4 (on 3.0–3.2 even with the `?` prefix, which arrived in 3.3). Each such setting is flagged with
   the oldest OpenSSL that accepts it.
3. **Copy lineage.** A pinned list identical to an earlier Mozilla guideline (which now includes X25519MLKEM768)
   was most likely copied and never refreshed. Certbot's Apache options file is one example.

## In the platform

The **Config check** page (`/api/config-check`) runs the same scanner on configuration a user pastes or
uploads. The text is never executed, fetched or stored: only the findings are kept, for that company, in the
GDPR export and deleted with the company. The latest check appears in the PDF report.

## Limits

* Text only: Helm templates are not rendered and variables are not resolved.
* A repository is not a running server. The live TLS probe in Discovery measures what servers negotiate.
* Go defaults depend on the toolchain a binary was built with, which the scan cannot see.
* File categories (test, docs, example, chart, deploy, source) are inferred from paths.
