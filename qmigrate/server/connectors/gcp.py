"""Google Cloud connector (read-only, Google Cloud REST APIs).

Credentials come from `gcloud auth application-default login` on this PC (Application Default
Credentials), or GOOGLE_APPLICATION_CREDENTIALS. Nothing is stored in the platform. Only GET calls:

  cloudkms: locations, keyRings, cryptoKeys                -> algorithm (RSA_*, EC_*, GOOGLE_SYMMETRIC_ENCRYPTION, PQ_*)
  compute: aggregated/sslCertificates                      -> public certificate PEM (key algorithm, expiry)
  compute: aggregated/targetHttpsProxies, sslPolicies      -> HTTPS load balancers, TLS profile, certificates
  compute: aggregated/forwardingRules                      -> external or internal load balancer
  sqladmin: instances                                      -> Cloud SQL disk encryption key (CMEK)
  storage: buckets                                         -> default KMS key (CMEK)
Roles: roles/viewer and roles/cloudkms.viewer on the project.
"""
from __future__ import annotations

import re

import requests

from qmigrate.server.connectors.base import CloudConnector
from qmigrate.server.connectors.inventory import Inventory, cert_algorithm_from_pem, missing_package, short

SCOPE = "https://www.googleapis.com/auth/cloud-platform.read-only"


def kms_algorithm(alg: str | None, purpose: str | None) -> tuple[str, str]:
    a = (alg or "").upper()
    usage = {"ASYMMETRIC_SIGN": "signature", "ASYMMETRIC_DECRYPT": "key_wrapping", "MAC": "hashing"}.get(purpose or "", "key_wrapping")
    if a.startswith("GOOGLE_SYMMETRIC") or "AES_256" in a:
        return "AES-256", "key_wrapping"
    if "AES_128" in a:
        return "AES-128", "data_encryption"
    m = re.search(r"RSA_\w*?_(2048|3072|4096)", a)
    if m:
        return f"RSA-{m.group(1)}", usage
    if "EC_SIGN_P384" in a or "SECP384" in a:
        return "ECDSA-P384", "signature"
    if "EC_SIGN" in a:
        return "ECDSA-P256", "signature"
    if "ML_DSA_65" in a or "PQ_SIGN_ML_DSA_65" in a:
        return "ML-DSA-65", "signature"
    if "ML_DSA_87" in a:
        return "ML-DSA-87", "signature"
    if "SLH_DSA" in a:
        return "SLH-DSA-SHA2-128s", "signature"
    if "ML_KEM_1024" in a:
        return "ML-KEM-1024", "key_exchange"
    if "ML_KEM_768" in a or "KEM_XWING" in a:
        return "ML-KEM-768", "key_exchange"
    if a.startswith("HMAC_SHA256"):
        return "SHA-256", "hashing"
    if a.startswith("HMAC"):
        return "SHA-384", "hashing"
    return "", usage


def ssl_policy_kex(policy: dict | None) -> tuple[str, str]:
    if not policy:
        return "ECDHE-P256", "TLS 1.0-1.3 (Google default policy)"
    profile, minv = policy.get("profile", "COMPATIBLE"), policy.get("minTlsVersion", "TLS_1_0")
    if profile == "COMPATIBLE" and minv in ("TLS_1_0", "TLS_1_1"):
        return "RSA-2048", f"TLS {minv[4:].replace('_', '.')}+ (allows RSA key transport)"
    return "ECDHE-P256", f"TLS {minv[4:].replace('_', '.')}+ ({profile.lower()})"


class GcpConnector(CloudConnector):
    provider = "gcp"
    title = "Google Cloud"

    def __init__(self, config: dict, session=None):
        super().__init__(config)
        self._session = session

    def _http(self):
        if self._session is None:
            try:
                import google.auth
                from google.auth.transport.requests import AuthorizedSession
            except ImportError as exc:
                raise missing_package("Google Cloud", "google-auth") from exc
            creds, default_project = google.auth.default(scopes=[SCOPE])
            self._session = AuthorizedSession(creds)
            self.config.setdefault("project_id", default_project)
        return self._session

    def _get(self, url: str, params=None) -> dict:
        r = self._http().get(url, params=params, timeout=30)
        if r.status_code == 403 and "has not been used" in r.text:
            return {}                                   # that API is not enabled in the project: nothing to read
        r.raise_for_status()
        return r.json()

    def _pages(self, url: str, key: str, params=None) -> list:
        out, params = [], dict(params or {})
        while True:
            data = self._get(url, params)
            items = data.get(key, [])
            out += list(items.values()) if isinstance(items, dict) else items
            token = data.get("nextPageToken")
            if not token:
                return out
            params["pageToken"] = token

    def _project(self) -> str:
        self._http()
        p = (self.config.get("project_id") or "").strip()
        if not p:
            raise RuntimeError("Set the Google Cloud project ID on the connection.")
        return p

    def test(self) -> dict:
        try:
            p = self._project()
            info = self._get(f"https://cloudresourcemanager.googleapis.com/v1/projects/{p}")
            return {"ok": True, "status": "connected", "message": f"Signed in to Google Cloud project '{info.get('name', p)}'."}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": "error",
                    "message": f"Google Cloud sign-in failed: {exc}. Run `gcloud auth application-default login` on this PC first."}

    def discover(self, run_index: int = 0) -> dict:
        p = self._project()
        inv = Inventory("GCP")
        self._kms(p, inv)
        self._certs(p, inv)
        self._https_proxies(p, inv)
        self._sql(p, inv)
        self._buckets(p, inv)
        return inv.result()

    def _kms(self, p, inv):
        base = "https://cloudkms.googleapis.com/v1"
        for loc in self._pages(f"{base}/projects/{p}/locations", "locations"):
            lid = loc["locationId"]
            for ring in self._pages(f"{base}/projects/{p}/locations/{lid}/keyRings", "keyRings"):
                for key in self._pages(f"{base}/{ring['name']}/cryptoKeys", "cryptoKeys"):
                    alg, usage = kms_algorithm((key.get("versionTemplate") or {}).get("algorithm"), key.get("purpose"))
                    inv.add(f"GCP-KMS-{short(key['name'].split('/')[-1], 30)}", "kms_key", alg, region=lid,
                            application=f"key ring {ring['name'].split('/')[-1]}", tags=key.get("labels"), usage=usage,
                            aliases=(key["name"],))

    def _certs(self, p, inv):
        url = f"https://compute.googleapis.com/compute/v1/projects/{p}/aggregated/sslCertificates"
        for scope in self._pages(url, "items"):
            for c in scope.get("sslCertificates", []):
                alg, years = cert_algorithm_from_pem(c.get("certificate", ""))
                region = c.get("region", "global").rsplit("/", 1)[-1]
                inv.add(f"GCP-CERT-{short(c['name'], 30)}", "tls_certificate", alg or "", region=region,
                        application=", ".join((c.get("managed") or {}).get("domains", [])) or c["name"],
                        exposure="internet", retention_years=years, aliases=(c["selfLink"],))

    def _https_proxies(self, p, inv):
        compute = f"https://compute.googleapis.com/compute/v1/projects/{p}"
        policies = {}
        for pol in self._pages(f"{compute}/global/sslPolicies", "items"):
            policies[pol["selfLink"]] = pol
        external = set()
        for scope in self._pages(f"{compute}/aggregated/forwardingRules", "items"):
            for fr in scope.get("forwardingRules", []):
                if fr.get("loadBalancingScheme", "").startswith("EXTERNAL"):
                    external.add(fr.get("target"))
        for scope in self._pages(f"{compute}/aggregated/targetHttpsProxies", "items"):
            for px in scope.get("targetHttpsProxies", []):
                alg, proto = ssl_policy_kex(policies.get(px.get("sslPolicy")))
                region = px.get("region", "global").rsplit("/", 1)[-1]
                aid = inv.add(f"GCP-LB-{short(px['name'])}", "load_balancer", alg, region=region,
                              application=px["name"], protocol=proto,
                              exposure="internet" if px["selfLink"] in external else "internal", aliases=(px["selfLink"],))
                for cert in px.get("sslCertificates", []):
                    inv.link(aid, cert, "trusts_cert")

    def _sql(self, p, inv):
        for i in self._pages(f"https://sqladmin.googleapis.com/v1/projects/{p}/instances", "items"):
            aid = inv.add(f"GCP-SQL-{short(i['name'])}", "database", "AES-256", region=i.get("region", ""),
                          application=f"{i.get('databaseVersion', 'Cloud SQL')} {i['name']}",
                          tags=(i.get("settings") or {}).get("userLabels"),
                          exposure="internet" if any(a.get("type") == "PRIMARY" for a in i.get("ipAddresses", [])) else "internal",
                          aliases=(i.get("selfLink"),))
            key = (i.get("diskEncryptionConfiguration") or {}).get("kmsKeyName") or ""
            inv.link(aid, key.split("/cryptoKeyVersions")[0], "uses_key")

    def _buckets(self, p, inv):
        for b in self._pages("https://storage.googleapis.com/storage/v1/b", "items", {"project": p}):
            aid = inv.add(f"GCP-GCS-{short(b['name'])}", "object_storage", "AES-256", region=b.get("location", "").lower(),
                          application=b["name"], tags=b.get("labels"), aliases=(b.get("selfLink"),))
            key = (b.get("encryption") or {}).get("defaultKmsKeyName") or ""
            inv.link(aid, key.split("/cryptoKeyVersions")[0], "uses_key")
