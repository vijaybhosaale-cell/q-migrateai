# Master's contribution: quantum deadlines and explainable risk

Most post-quantum tools (inventory scanners, cloud posture tools) answer **what** uses RSA or ECC.
Q-MigrateAI adds two things they do not give:

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
* NIST IR 8547, *Transition to Post-Quantum Cryptography Standards*.
* NIST FIPS 203, 204, 205 (ML-KEM, ML-DSA, SLH-DSA), August 2024.
