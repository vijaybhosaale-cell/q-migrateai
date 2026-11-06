# Project data: see, correct and download what was collected

Click **Project data** in the sidebar (under *Insight and operations*), or open **http://localhost:8002/project-data/**.

A *project* is one connection on the **Connect and discover** page, for example *Public websites* with your own
domains `chatgpt.com, google.com`, or an AWS / Azure / Google Cloud account. Run discovery for it, then open this page.

## What the page shows

* **Every data row collected for the project**: for a website, its TLS key exchange (and whether it already accepts
  the post-quantum hybrid X25519MLKEM768), its certificate (key, issuer, expiry) and the certificate authorities
  behind it, with the IP address, hosting cloud, TLS version and cipher that were measured.
* **The business data** used by the risk model: data sensitivity, how many years the data must stay secret,
  business criticality, exposure. For public websites these come from the project's sector assumptions.
* **Status of each row**
  * **Needs migration**: still uses an algorithm a quantum computer breaks (RSA, ECDSA, ECDHE, X25519 ...).
  * **Migrated**: migrated in the platform (PQC lab or a wave); shows when and by whom.
  * **Already quantum-safe**: no migration needed (for example X25519+ML-KEM-768).
* **Used in analysis**: the row is part of the AI risk analysis, the migration plan and the PDF report.
  Websites that could not be reached are listed under **Not reached (not used)**.
* **By target**: the same counts per website / resource you typed.
* **Field guide**: where every column comes from and what the platform uses it for.

## Correcting data

Click a row. Analysts, CISOs and admins can correct: target name, owner, region, exposure, data sensitivity,
years the data must stay secret, business criticality and whether clients support post-quantum, and add a note.
Measured algorithms are not editable: change them by migrating in the PQC lab.

* Risk scores and the quantum deadline are recalculated straight away with the corrected values.
* Corrections are kept when discovery runs again; the page shows the measured value next to the correction,
  with a button to go back to the measured value.
* Every correction is written to the audit log (`data.corrected`). Viewers can see and download, not edit.

## Downloads

**Download Excel** (sheets: Summary, Data, Field guide), **CSV** (opens in Excel) or **JSON**.
Downloads are written to the audit log (`data.exported`).

## API

| Call | What it does |
|---|---|
| `GET /api/projects` | Projects with row counts per status |
| `GET /api/projects/{id}/data` | All rows, summary, per-target counts, not reached, field guide |
| `PATCH /api/projects/{id}/assets/{asset_id}` | Body `{"changes": {...}, "note": "...", "revert": ["field"]}` |
| `GET /api/projects/{id}/export?format=csv\|json\|xlsx` | Download |

The page lives in `qmigrate/server/dataview/` and the logic in `qmigrate/server/project_data.py`;
the only dashboard change is the **Project data** link in the sidebar (Insight and operations), in `web/src/main.ts` and `web/dist/js/main.js`.
