"""Azure connector (read-only, Azure Resource Manager + Key Vault REST APIs).

Credentials come from `az login` on this PC (DefaultAzureCredential: Azure CLI, environment variables
or a managed identity). Nothing is stored in the platform. Only GET calls are made:

  Microsoft.KeyVault/vaults, vaults/keys                 -> Key Vault keys (kty, keySize, curveName)
  https://<vault>.vault.azure.net/certificates           -> certificates (key type and size)   [Key Vault Reader]
  Microsoft.Network/applicationGateways                   -> TLS policy, certificates, public frontend
  Microsoft.Storage/storageAccounts                       -> encryption key source (Microsoft or Key Vault key)
  Microsoft.Sql/servers, databases, encryptionProtector   -> TDE protector (service-managed or Key Vault key)
"""
from __future__ import annotations

import requests

from qmigrate.server.connectors.base import CloudConnector
from qmigrate.server.connectors.inventory import Inventory, cert_algorithm_from_pem, missing_package, short

ARM = "https://management.azure.com"


def key_algorithm(kty: str | None, size, curve: str | None, ops) -> tuple[str, str]:
    kty = (kty or "").upper()
    ops = [o.lower() for o in (ops or [])]
    usage = "signature" if "sign" in ops and "wrapkey" not in ops else "key_wrapping"
    if kty.startswith("RSA"):
        size = int(size or 2048)
        return ("RSA-4096" if size >= 4096 else "RSA-3072" if size >= 3072 else "RSA-2048"), usage
    if kty.startswith("EC"):
        return ("ECDSA-P384" if curve and ("384" in curve or "521" in curve) else "ECDSA-P256"), "signature"
    if kty.startswith("OCT"):
        return "AES-256", "key_wrapping"
    return "", usage


def appgw_kex(policy: dict | None) -> tuple[str, str]:
    p = policy or {}
    name = (p.get("policyName") or "").lower()
    minv = (p.get("minProtocolVersion") or "").lower()
    if "2022" in name or "tlsv1_3" in minv:
        return "ECDHE-P256", "TLS 1.2/1.3"
    if not p or "2015" in name or "2017" in name or "tlsv1_0" in minv:
        return "RSA-2048", "TLS 1.0-1.2 (allows RSA key transport)"
    return "ECDHE-P256", "TLS 1.2"


class AzureConnector(CloudConnector):
    provider = "azure"
    title = "Microsoft Azure"

    def __init__(self, config: dict, session=None, credential=None):
        super().__init__(config)
        self.http = session or requests.Session()
        self._cred = credential

    # ------------------------------------------------------------------ auth + HTTP
    def _credential(self):
        if self._cred is None:
            try:
                from azure.identity import DefaultAzureCredential
            except ImportError as exc:
                raise missing_package("Azure", "azure-identity") from exc
            tenant = (self.config.get("tenant_id") or "").strip() or None
            self._cred = DefaultAzureCredential(exclude_interactive_browser_credential=True,
                                                **({"additionally_allowed_tenants": ["*"]} if tenant else {}))
        return self._cred

    def _get(self, url: str, scope: str = "https://management.azure.com/.default", params=None) -> dict:
        token = self._credential().get_token(scope).token
        r = self.http.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _list(self, url: str, api: str, scope: str = "https://management.azure.com/.default") -> list[dict]:
        out, params = [], {"api-version": api}
        while url:
            data = self._get(url, scope, params)
            out += data.get("value", [])
            url, params = data.get("nextLink"), None
        return out

    def _sub(self) -> str:
        sub = (self.config.get("subscription_id") or "").strip()
        if not sub:
            subs = self._list(f"{ARM}/subscriptions", "2022-12-01")
            if not subs:
                raise RuntimeError("No Azure subscription found for this login.")
            sub = subs[0]["subscriptionId"]
        return sub

    def test(self) -> dict:
        try:
            sub = self._sub()
            info = self._get(f"{ARM}/subscriptions/{sub}", params={"api-version": "2022-12-01"})
            return {"ok": True, "status": "connected", "message": f"Signed in to Azure subscription '{info.get('displayName', sub)}'."}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": "error", "message": f"Azure sign-in failed: {exc}. Run `az login` on this PC first."}

    # ------------------------------------------------------------------ discovery
    def discover(self, run_index: int = 0) -> dict:
        sub = self._sub()
        base = f"{ARM}/subscriptions/{sub}/providers"
        inv = Inventory("Azure")
        self._keyvaults(base, inv)
        self._appgw(base, inv)
        self._storage(base, inv)
        self._sql(base, inv)
        return inv.result()

    def _keyvaults(self, base, inv):
        for v in self._list(f"{base}/Microsoft.KeyVault/vaults", "2023-07-01"):
            region, vname = v.get("location", ""), v["name"]
            vault_uri = v.get("properties", {}).get("vaultUri", f"https://{vname}.vault.azure.net/").rstrip("/")
            for k in self._list(f"{ARM}{v['id']}/keys", "2023-07-01"):
                p = k.get("properties", {})
                alg, usage = key_algorithm(p.get("kty"), p.get("keySize"), p.get("curveName"), p.get("keyOps"))
                inv.add(f"AZ-KV-{short(vname, 20)}-{short(k['name'], 24)}", "kms_key", alg, region=region,
                        application=f"Key Vault {vname}", tags=k.get("tags") or v.get("tags"), usage=usage,
                        aliases=(k["id"], f"{vault_uri}/keys/{k['name']}", p.get("keyUri"), p.get("keyUriWithVersion")))
            try:
                certs = self._list(f"{vault_uri}/certificates", "7.4", scope="https://vault.azure.net/.default")
            except requests.HTTPError as exc:
                inv.skipped.append(f"{vname}: certificates not readable ({exc.response.status_code}); "
                                   "grant 'Key Vault Reader' on the vault")
                continue
            for c in certs:
                name = c["id"].rstrip("/").split("/")[-1]
                full = self._get(f"{vault_uri}/certificates/{name}", "https://vault.azure.net/.default", {"api-version": "7.4"})
                kp = (full.get("policy") or {}).get("key_props", {})
                alg, _ = key_algorithm(kp.get("kty"), kp.get("key_size"), kp.get("crv"), ["sign"])
                years = None
                if full.get("cer"):     # the public certificate (base64 DER)
                    pem = "-----BEGIN CERTIFICATE-----\n" + full["cer"] + "\n-----END CERTIFICATE-----\n"
                    alg2, years = cert_algorithm_from_pem(pem)
                    alg = alg2 or alg
                inv.add(f"AZ-CERT-{short(vname, 20)}-{short(name, 24)}", "tls_certificate", alg, region=region,
                        application=name, exposure="internet", tags=c.get("tags"), retention_years=years,
                        aliases=(c["id"], f"{vault_uri}/secrets/{name}", full.get("sid")))

    def _appgw(self, base, inv):
        for g in self._list(f"{base}/Microsoft.Network/applicationGateways", "2023-09-01"):
            p = g.get("properties", {})
            if not any(l.get("properties", {}).get("protocol") == "Https" for l in p.get("httpListeners", [])):
                continue
            public = any(f.get("properties", {}).get("publicIPAddress") for f in p.get("frontendIPConfigurations", []))
            alg, proto = appgw_kex(p.get("sslPolicy"))
            aid = inv.add(f"AZ-AGW-{short(g['name'])}", "load_balancer", alg, region=g.get("location", ""),
                          application=g["name"], tags=g.get("tags"), protocol=proto,
                          exposure="internet" if public else "internal", aliases=(g["id"],))
            for c in p.get("sslCertificates", []):
                secret = c.get("properties", {}).get("keyVaultSecretId")
                if secret:
                    inv.link(aid, secret.rsplit("/", 1)[0] if secret.count("/") > 4 else secret, "trusts_cert")

    def _storage(self, base, inv):
        for a in self._list(f"{base}/Microsoft.Storage/storageAccounts", "2023-01-01"):
            enc = a.get("properties", {}).get("encryption", {})
            aid = inv.add(f"AZ-ST-{short(a['name'])}", "object_storage", "AES-256", region=a.get("location", ""),
                          application=a["name"], tags=a.get("tags"),
                          exposure="internet" if a.get("properties", {}).get("publicNetworkAccess", "Enabled") == "Enabled" else "internal",
                          aliases=(a["id"],))
            kv = enc.get("keyvaultproperties") or {}
            if enc.get("keySource") == "Microsoft.Keyvault" and kv.get("keyname"):
                inv.link(aid, f"{kv.get('keyvaulturi', '').rstrip('/')}/keys/{kv['keyname']}", "uses_key")

    def _sql(self, base, inv):
        for srv in self._list(f"{base}/Microsoft.Sql/servers", "2021-11-01"):
            try:
                prot = self._get(f"{ARM}{srv['id']}/encryptionProtector/current", params={"api-version": "2021-11-01"})
            except requests.HTTPError:
                prot = {}
            uri = (prot.get("properties") or {}).get("uri")
            for db in self._list(f"{ARM}{srv['id']}/databases", "2021-11-01"):
                if db["name"] == "master":
                    continue
                aid = inv.add(f"AZ-DB-{short(srv['name'], 20)}-{short(db['name'], 20)}", "database", "AES-256",
                              region=db.get("location", srv.get("location", "")), application=f"SQL {db['name']}",
                              tags=db.get("tags") or srv.get("tags"), aliases=(db["id"],))
                if uri:
                    inv.link(aid, uri.rsplit("/", 1)[0] if uri.count("/") > 4 else uri, "uses_key")
