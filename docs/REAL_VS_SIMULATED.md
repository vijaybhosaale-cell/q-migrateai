# What is real and what is simulated

This page is deliberately blunt, so nobody (guide, jury, customer) is misled during a demo.

## Real: built, running and tested

| Part | What is real about it | How it was checked |
|---|---|---|
| Web application | Every page of the journey works in the browser: login, dashboard, dependency map, risk, plan, PQC lab, report, models, alerts, audit, settings, privacy | 23-step automated browser test (Playwright, Chromium), desktop and phone width |
| Accounts and security | Sign-up with GDPR consent, scrypt passwords, sessions in HttpOnly cookies, CSRF header, login rate limits, roles (Admin, CISO, Analyst, Viewer), audit log | API tests + browser test |
| Two-factor authentication | Real TOTP codes (RFC 6238) that work with Microsoft Authenticator, Google Authenticator, 1Password; QR code; replay protection | Browser test computes real codes and logs in |
| Multi-tenant isolation | `tenant_id` on every row; on PostgreSQL, row-level security policies enforced while the app runs as a non-superuser role | Tests try to read another tenant's rows directly in SQL and get nothing |
| AI risk engine | Dependency graph (NetworkX), inherited exposure, rule formula, 5 trained models (rule-based, Random Forest, MLP, MLP + graph features, SIGN graph neural network), cross-validation, permutation importance, per-asset explanations | Same engine as the Stage 1 MVP, reused unchanged |
| Migration planning | Waves 1/2/3, priority formula, effort estimate, what-if curve | Tests + browser test |
| Migration actions | Migrate one asset, migrate a whole wave, roll back, reset; each one recalculates the risk of everything that depends on it and is stored with the previous policy | Tests + browser test |
| PDF report | Generated on the server (ReportLab): executive summary, before/after, readiness checks, top risks, waves, queue, history, method and limits | Downloaded and opened in the test |
| Alerts | Alerts are stored and shown; scheduled re-discovery raises alerts for new quantum-vulnerable assets; Slack webhook delivery works | Slack tested against a local stand-in webhook |
| GDPR functions | Consent at sign-up, "i" notice, export all company data as JSON (no password hashes or 2FA secrets), delete the company and all its data | Browser test exports, deletes, then checks login fails |
| Deployment files | Docker Compose (Caddy, engine, simulator, PostgreSQL, backups), Caddyfile, `.env` secrets | Caddyfile validated and run with the real Caddy binary; Compose file validated with the Docker Compose CLI; production-like run (PostgreSQL + RLS + Caddy + separate simulator) passed the full browser test; a backup was taken and restored |

## Simulated or placeholder: be clear about these in a demo

| Part | Status | What it would take |
|---|---|---|
| **Cloud data** | **Real (default).** Discovery measures the public websites of real organisations live: TLS key exchange (including whether the server accepts post-quantum X25519MLKEM768), certificate chains and the cloud that hosts each site (from the IP lists AWS, Google Cloud, Azure and Cloudflare publish). See [REAL_DATA.md](REAL_DATA.md). The synthetic simulator is switched off unless `ENABLE_SIMULATOR=1` and `DATA_SOURCE=simulator`. Private assets (KMS keys, databases, VPNs) are not visible from the internet. | Real cloud connectors (below) for private assets |
| **AWS / Azure / GCP scanning** | **Built, read-only.** KMS / Key Vault / Cloud KMS keys, certificates, load balancer TLS policies and data-store encryption keys, signed in with the cloud CLI login on the PC (`aws configure`, `az login`, `gcloud auth application-default login`). Tested against moto (AWS) and recorded API answers (Azure, Google Cloud), **not yet against a real account**. Setup: [CLOUD_SETUP.md](CLOUD_SETUP.md). | A first run on a real (free-tier) account of each cloud |
| **AI training labels** | **Rubric, not analysts.** On real data the labels come from a documented migration-priority rubric (`qmigrate/realdata/collector.py`, `rubric_score`: algorithm exposure, harvest-now-decrypt-later, how many sites depend on the asset, criticality). The models learn that rubric; they are not proven against real analysts. (The AI models page says which source the labels come from.) | Labels from real security analysts, or a pilot customer |
| **PQC "migration"** | **Policy change only.** Migrating changes the algorithm recorded for the asset and recomputes risk. Nothing is reconfigured in a real cloud. | Calls to each cloud's key / certificate / load-balancer APIs, with change windows |
| **Validation checks** | **Policy checks** (standard, security level, client support, key and signature sizes, rollback path), not a live TLS handshake test. | A test client doing a real hybrid X25519+ML-KEM-768 handshake (for example with OpenSSL 3.5 or liboqs) |
| **Before / after measurement** | Computed from the model of the estate, not measured on live traffic | Live scanning before and after |
| **Login with Microsoft** | **Placeholder button** (the server answers "not configured"). | Register an Entra ID app and add OpenID Connect |
| **E-mail alerts** | Code is real, but sending needs SMTP settings in `.env`. Without them, deliveries are logged as "skipped". | Any SMTP account (for example Brevo, Mailjet, Office 365) |
| **Slack alerts** | Real if you paste a real incoming-webhook URL; otherwise nothing is sent | A Slack workspace webhook |
| **Assistant** | **Rule-based**, not a large language model. It answers only from the company's own data (asset explanations, plan, what-if, readiness, glossary), so it never invents facts. | Optional LLM with retrieval over the same data |
| **NIST readiness %** | An **indicative** score from six checks aligned with NIST guidance (FIPS 203/204/205, NIST IR 8547 timeline). Not a certification or an audit. | A formal assessment |
| **Privacy policy** | **Template**, marked "to be reviewed by a lawyer". | Legal review |
| **Docker images on a real server** | Not built inside this development environment (the container registry was blocked here). The same code ran in a production-like setup without containers. | Run `docker compose up -d --build` on the server (see the deployment guide) |

## One sentence for the jury

"The platform runs on real, live data: the public websites of real banks, payment companies, hospitals and health agencies,
measured for post-quantum readiness. Scanning private cloud assets (KMS keys, databases) is the next step, with the
read-only access already designed."
