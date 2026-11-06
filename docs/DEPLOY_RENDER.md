# Live demo on Render (free)

Result: the platform at `https://q-migrateai.onrender.com` (or the address Render shows), built from this
repository by `render.yaml`. Free web service in Frankfurt (EU).

## What runs

| Company | Data | Logins (password: the DEMO_PASSWORD you set) |
|---|---|---|
| Demo Finance Co. | Real: live TLS and certificate measurements of 45 bank and payment websites | admin@, ciso@, analyst@, viewer@demofinance.example |
| Demo Health Group | Real: 43 hospital and health websites | admin@, ciso@demohealth.example |
| Demo Lab (simulated) | Synthetic estate with data-flow links, marked "Demo data". Used for the Data paths page (P7) | admin@, ciso@, analyst@, viewer@demolab.example |

Public sign-up is off and the login page does not show the demo password, so only people you give it to can log in.
Give the guide or jury a **viewer** login if they should only look.

## Deploy (first time, about 15 minutes)

1. Sign up at https://render.com with **GitHub** (account `vijaybhosaale-cell`) and allow Render to read the
   `q-migrateai` repository.
2. Dashboard → **New** → **Blueprint** → choose `q-migrateai` → Render reads `render.yaml`.
3. Type a **DEMO_PASSWORD** (at least 12 characters, not the one in the README), then **Apply**.
4. Wait for the first build (5–10 minutes). Open the address Render shows; `/api/health` must answer `"status":"ok"`.

Every push to `main` redeploys automatically.

## Free-plan limits (say them in the demo)

* The service **sleeps after 15 minutes without visits**. The next visit wakes it in about a minute.
* The disk is not kept: after waking, the platform measures the real websites again and retrains the models
  (a few minutes on the free CPU). **Open the site 5–10 minutes before a demo.**
* For an always-on version with PostgreSQL and row-level security, use the Hetzner guide
  ([DEPLOY_HETZNER.md](DEPLOY_HETZNER.md)) or a paid Render instance.
