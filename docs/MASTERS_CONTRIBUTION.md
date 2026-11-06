# Master's contribution: quantum deadlines and explainable risk

Most post-quantum tools (inventory scanners, cloud posture tools) answer **what** uses RSA or ECC.
Research has started to quantify **when** to migrate (see *Related work* below), but at the level of a whole
organisation or with assumed parameters. Q-MigrateAI adds two things to a measured, per-asset inventory:

1. **When** each asset must be upgraded: a per-asset quantum deadline from Mosca's theorem.
2. **Why** each asset got its risk score: a plain-language sentence, checked for faithfulness.

Both are measured against the rule-based baseline on the real bank and hospital data.

## 1. Quantum deadline (Mosca's theorem)

Mosca (2018): data is at risk if **X + Y > Z**.

| Symbol | Meaning | Where the number comes from |
|---|---|---|
| X | Years the data must stay secret (or a signature must be trusted) | Asset retention: sector default (finance 10 years, health 20), cloud tags, or certificate validity left |
| Y | Years the migration takes | `0.5 + 2.5 x effort/100 + 0.25 x log2(1 + dependants)` (max 1) `+ 1` if clients do not support PQC yet |
| Z | Years until a cryptographically relevant quantum computer (CRQC) | Expert scenarios below |

Per asset: **upgrade by = min(CRQC year - X, 2035)** and **start by = upgrade by - Y**.
The 2035 cap is NIST IR 8547, which disallows RSA and ECC after 2035 at every strength.

| Scenario | CRQC year | Basis (Quantum Threat Timeline Report 2025, 26 experts) |
|---|---|---|
| Cautious | 2033 | Risk-averse: within 10 years the average estimate is already 28-49 % |
| Expected (default) | 2038 | Between the 10- and 15-year horizons, where most experts put the odds above 50 % |
| Late | 2045 | 20-year horizon: 92 % of experts put the odds at 50 % or more |

Status: **late** (start date passed), **urgent** (start within 12 months), **soon** (within 3 years), **planned**,
plus **replace now** for classically weak 3DES/SHA-1 and **quantum-safe**.
An AES-256 database protected by an RSA key inherits the key's deadline, and the sentence names the key to upgrade.

Where it appears (dashboard code unchanged):
* each asset's reasons list (Assets page and graph side panel): `Quantum deadline: upgrade by 2028 ...`
* the PDF report: a "Quantum deadlines" section
* API: `GET /api/deadlines?scenario=cautious|expected|late`, and `deadline` fields in `/api/assets` and `/api/plan`

## 2. Explainable risk

* **Summary sentence**, from the formula's own contributions. The formula is additive, so the factors named
  really are the ones that add the most points: *"High risk because it uses X25519 for key exchange, which a quantum
  computer can break, it holds sensitivity 5/5 data and it is reachable from the internet."*
* **AI note**: the neural network's occlusion attributions, mapped to the same six factors. It says whether the AI
  agrees with the formula and, if not, which signal causes the difference (often exposure inherited through the
  dependency graph, which the formula does not see).

## 3. Evaluation against the rule baseline

Run on the PC after the first start has measured the real websites:

```
evaluate.bat          (Windows)
./evaluate.sh         (macOS / Linux)
```

It writes `data/research/evaluation_<date>.md` (tables ready for the thesis) and `.json`, for each workspace.

| Question | Measure |
|---|---|
| Does the deadline add information the risk score lacks? | Urgent assets (start within 12 months) that the rule baseline puts in Low/Medium or outside its top-N; urgent assets outside Wave 1; Spearman correlation between rule score and urgency |
| How sensitive is it to the quantum timeline? | Late / urgent / soon / planned counts for the three scenarios |
| Are the explanations faithful? | Deletion test on the test split: probability drop when the 3 explained inputs are reset vs 3 random inputs (ratio), and how often the prediction changes |
| Do the AI and the formula point at the same reasons? | Jaccard overlap of the named factors, split by whether their classes agree |

## 4. Supported is not switched on (P8)

Code and data: `qmigrate/research/p8_config_pqc/` (report in `results/summary.md`). In the platform: the
**Config check** page.

Software support for hybrid ML-KEM does not mean a deployment negotiates it. The study scans 37 public
repositories (79,593 files, every finding pinned to a commit) and combines each key-exchange setting, or its
absence, with the product's sourced default:

* Outside tests and docs, 12 of the 13 readable key-exchange settings pin a classical-only list. Most projects
  set nothing, so the product default decides. Envoy, Istio and Envoy Gateway default to off. Go-based servers
  default to on from Go 1.24. nginx, HAProxy and Apache depend on the OpenSSL version.
* Certbot's Apache options file pins the curve list from an earlier Mozilla guideline, which Mozilla has since
  updated to put X25519MLKEM768 first.
* On AWS the default depends on the tool that creates the listener: the console uses a PQ policy, while the
  API, CloudFormation and CDK (and the AWS Load Balancer Controller) default to `ELBSecurityPolicy-2016-08`.
* Naming ML-KEM in nginx, HAProxy or Apache stops the server from starting on OpenSSL 3.0–3.4 (3.0–3.2 even with
  `?`). The check reports the oldest OpenSSL each list needs.

## 5. A data path is only as safe as its weakest hop (P7)

Code and results: `qmigrate/engine/paths.py`, `qmigrate/research/p7_paths/`. In the platform: the **Data paths**
page.

Harvest-now-decrypt-later needs one readable hop, so the unit that matters is the path data travels, not the
asset. On both demo companies, Wave 1 of the per-asset queue raises asset coverage from about 8% to about 28% but
leaves none of about 450 data paths safe end to end, and the number of assets that look safe while carrying
harvestable data more than triples. With the same 20 migrations, path-first planning makes about 25 paths safe.
The same holds in 15 more generated estates. Limit: the evaluation uses synthetic estates, because no real
source here provides data-flow links yet.

## Related work and what is different

Cite these two papers; a reviewer who knows the field will expect them.

| Work | What it already does | What Q-MigrateAI adds |
|---|---|---|
| A. Gupta, S. Mittal, [Post-quantum readiness and cryptographic transition planning for enterprise cloud](https://link.springer.com/article/10.1186/s42400-026-00579-2), *Cybersecurity* 9, 147 (2026) | Mosca's inequality with a Monte Carlo estimator and expert-elicited Q-day timing, to compare migration start years and durations | Their model treats sensitive data as one stream for the organisation; ours gives a deadline **per asset**, from that asset's own data lifetime and dependants |
| A. Shaw, [Cost of Delay for Post-Quantum Migration](https://arxiv.org/abs/2610.09029), arXiv:2610.09029 (2026) | A per-asset ordered list that combines classical and harvest-now-decrypt-later risk as a cost of delay | Their case studies use parameters assumed from public documentation and are not validated against outcomes; ours runs on **measured** data (live TLS and certificate measurements, cloud APIs), derives migration time from the **dependency graph** (an asset inherits the deadline of the key that protects it) and explains every result in plain words |

| H. Balaji et al., [Operationalising Post-Quantum TLS: Automated Configuration Profiling and Hybrid PQC Deployment in Financial Infrastructure](https://arxiv.org/abs/2605.17955), arXiv:2605.17955 (2026) | Parses nginx, Apache and Spring Boot TLS configuration; measures 8,443 public nginx configs (the hybrid curve appears in 4, about 0.8% of contexts that set a curve) | P8 covers 11 products, including Envoy, Istio, Envoy Gateway, Go and AWS load balancers, where defaults differ; it reports the **effective outcome** (pinned off, default off, on, version-dependent), the OpenSSL version a list needs to load, and copy lineage against Mozilla's guideline versions |
| Moderne OpenRewrite recipes ([PQC recipe catalog](https://docs.moderne.io/user-documentation/recipes/recipe-catalog/cryptography/pqc/)) | Commercial code-rewrite recipes; by their names they find TLS named-group configuration and add a hybrid group | P8 measures and explains across configuration formats rather than rewriting one language's code |

Our P8 numbers point the same way as Balaji et al.: explicit lists that include ML-KEM are rare.

So the honest claim is not "the first deadline", but: *a per-asset quantum deadline computed from a measured
dependency graph, with faithful explanations, evaluated against the rule baseline.*

## Limits (state them in the thesis)

* The CRQC year is an expert estimate, which is why three scenarios are reported.
* Y is a model built from effort points, not measured project durations. The constants are in
  `qmigrate/engine/deadline.py`, and every result shows them.
* Risk labels come from the published rubric, not from human analysts, so F1 compares the models with that rubric.
  The deadline results do not depend on the labels.
* Public websites only show their TLS endpoint and certificate chain. Internal keys and databases need a connected
  cloud account.

## Sources

* M. Mosca, "Cybersecurity in an era with quantum computers: will we be ready?", IEEE Security & Privacy 16(5), 2018.
* M. Mosca, M. Piani, *Quantum Threat Timeline Report 2025*, Global Risk Institute / evolutionQ.
* A. Gupta, S. Mittal, "Post-quantum readiness and cryptographic transition planning for enterprise cloud",
  *Cybersecurity* 9, 147, 2026.
* A. Shaw, "Cost of Delay for Post-Quantum Migration: Putting Classical and Harvest-Now-Decrypt-Later Risk on One
  Ordered List", arXiv:2610.09029, 2026.
* NIST IR 8547, *Transition to Post-Quantum Cryptography Standards*.
* NIST FIPS 203, 204, 205 (ML-KEM, ML-DSA, SLH-DSA), August 2024.
