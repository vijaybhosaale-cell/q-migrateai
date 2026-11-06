# Real data: where it comes from and how to use it

Q-MigrateAI now runs on **real, existing data** measured live from the internet. No synthetic data is used by default.

## What is measured

For every website in the chosen list, discovery reads only public information, the same way a browser does:

| What | How | Becomes in the platform |
|---|---|---|
| Post-quantum readiness of the key exchange | One TLS 1.3 hello offering the hybrid **X25519MLKEM768** (FIPS 203 ML-KEM-768 + X25519). The server's first reply says whether it accepts it, or which classical group it wants instead (X25519, P-256...). The connection is then closed. | A *Load balancer (TLS)* asset, algorithm `X25519+ML-KEM-768` (safe) or `X25519` / `ECDHE-P256` / `RSA-2048` (quantum-vulnerable) |
| Certificate chain | A normal HTTPS handshake; missing issuers are downloaded from the public "CA Issuers" URL inside the certificate | A *TLS certificate* asset (RSA-2048, ECDSA-P256...) and shared *Certificate authority* assets |
| Dependencies | Site → its certificate → intermediate CA → root CA | Edges in the dependency map; one CA key protects many sites |
| Hosting cloud and region | The site's IP address matched against the IP lists published by [AWS](https://ip-ranges.amazonaws.com/ip-ranges.json), [Google Cloud](https://www.gstatic.com/ipranges/cloud.json), [Azure](https://www.microsoft.com/en-us/download/details.aspx?id=56519) and [Cloudflare](https://www.cloudflare.com/ips-v4) | The "Cloud" and "Region" columns (AWS, Azure, GCP, Cloudflare, Other hosting, Public PKI) |
| Popularity | The [Tranco](https://tranco-list.eu/) research ranking of the top 1 million websites | Business criticality (top 100 = 5, top 1,000 = 4) |

## Website lists

| Choice in "Connect" | Websites |
|---|---|
| `finance` | 45 real banks, payment companies and central banks (used by the *Demo Finance Co.* login) |
| `health` | 43 real hospitals, health agencies and pharma companies (used by the *Demo Health Group* login) |
| `tranco` | The current top N websites of the Tranco list (downloaded automatically) |
| `custom` | Your own domains, comma-separated |

The lists are in `qmigrate/realdata/domain_lists.py`.

## What the internet cannot tell us (assumptions)

- **Data sensitivity and retention** are set per sector: finance 5/5 and 10 years (anti-money-laundering record keeping), health 5/5 and 20 years (patient records), popular sites 3/5 and 2 years. Change them in `domain_lists.py`.
- **AI training labels** come from a documented rubric (`rubric_score` in `qmigrate/realdata/collector.py`), not from human analysts.
- Private assets (KMS keys, databases, VPNs, backups) cannot be seen from the internet.

## How to run

1. Double-click `start_demo.bat` (internet needed). The first start installs packages, then measures the finance and health websites (about one minute each) and trains the AI models.
2. Log in as `ciso@demofinance.example` or `ciso@demohealth.example` (password `QuantumDemo!2026`).
3. To check other websites: **Connect and discover → Public websites (real data) → Set up**, pick `tranco` or `custom`, save, then **Run discovery**.

To start again from fresh measurements, run `reset_demo_data.bat` and then `start_demo.bat`.

## Ethics and safety

One ordinary HTTPS connection per website, like opening it in a browser, plus public certificate and IP-range files. No credentials, no private keys, no port or path scanning, at most 300 websites per run. Use it on public websites or your own domains only.
