# Third-party components

Shipped with the web app (`web/dist`):

| Component | Use | Licence | Licence file |
|---|---|---|---|
| Cytoscape.js 3.30.4 | Dependency map | MIT | `web/dist/vendor/cytoscape.LICENSE.txt` |
| qrcode-generator | Two-factor QR code | MIT | `web/dist/vendor/qrcode.LICENSE.txt` |
| Space Grotesk | Headings | SIL Open Font License 1.1 | `web/dist/fonts/` |
| IBM Plex Sans, IBM Plex Mono | Body text, asset IDs | SIL Open Font License 1.1 | `web/dist/fonts/` |

Installed by `pip` (not shipped in this folder): FastAPI (MIT), Starlette (BSD-3), Pydantic (MIT), Uvicorn (BSD-3),
NumPy (BSD-3), scikit-learn (BSD-3), NetworkX (BSD-3), Requests (Apache-2.0), ReportLab (BSD), cryptography
(Apache-2.0 or BSD), psycopg 3 (LGPL-3.0, used as an unmodified library).

Used by the Docker deployment: Caddy (Apache-2.0), PostgreSQL (PostgreSQL Licence), Python base image (PSF and others).

Build tools (not needed to run): TypeScript (Apache-2.0), Tailwind CSS (MIT).
