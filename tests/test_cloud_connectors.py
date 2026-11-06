"""AWS, Azure and Google Cloud connectors, tested offline.

AWS runs against moto (an in-memory imitation of the AWS APIs); Azure and Google Cloud against
recorded-shape JSON answers. Each test checks the algorithms, the dependency edges and that the
result can be stored and trained by the platform.
"""
from __future__ import annotations

import datetime as dt

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from qmigrate.engine.catalog import ALGORITHMS, SERVICE_LABELS


def _check(inv):
    ids = {a["asset_id"] for a in inv["assets"]}
    for a in inv["assets"]:
        assert a["algorithm"] in ALGORITHMS and a["service_type"] in SERVICE_LABELS
        assert a["analyst_label"] in ("Low", "Medium", "High", "Critical")
    for e in inv["edges"]:
        assert e["source"] in ids and e["target"] in ids
    return {a["asset_id"]: a for a in inv["assets"]}


def _pem() -> str:
    k = ec.generate_private_key(ec.SECP256R1())
    n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "shop.example")])
    now = dt.datetime.now(dt.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key()).serial_number(7)
         .not_valid_before(now).not_valid_after(now + dt.timedelta(days=400)).sign(k, hashes.SHA256()))
    return c.public_bytes(serialization.Encoding.PEM).decode()


# ------------------------------------------------------------------ AWS (moto)
def test_aws_connector(monkeypatch):
    moto = pytest.importorskip("moto")
    import boto3
    for k, v in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "AWS_DEFAULT_REGION": "eu-west-3"}.items():
        monkeypatch.setenv(k, v)
    with moto.mock_aws():
        r = "eu-west-3"
        kms = boto3.client("kms", region_name=r)
        sym = kms.create_key(Description="payments data key")["KeyMetadata"]
        kms.create_key(Description="token signing", KeySpec="RSA_2048", KeyUsage="SIGN_VERIFY")
        kms.create_key(Description="partner key", KeySpec="ECC_NIST_P384", KeyUsage="SIGN_VERIFY",
                       Tags=[{"TagKey": "DataClassification", "TagValue": "restricted"}])
        s3 = boto3.client("s3", region_name=r)
        s3.create_bucket(Bucket="qm-statements", CreateBucketConfiguration={"LocationConstraint": r})
        s3.put_bucket_encryption(Bucket="qm-statements", ServerSideEncryptionConfiguration={"Rules": [
            {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms", "KMSMasterKeyID": sym["Arn"]}}]})
        rds = boto3.client("rds", region_name=r)
        rds.create_db_instance(DBInstanceIdentifier="ledger", DBInstanceClass="db.t3.micro", Engine="postgres",
                               MasterUsername="u", MasterUserPassword="p" * 12, AllocatedStorage=20,
                               StorageEncrypted=True, KmsKeyId=sym["KeyId"])
        acm = boto3.client("acm", region_name=r)
        cert_arn = acm.request_certificate(DomainName="shop.example", ValidationMethod="DNS")["CertificateArn"]
        ec2 = boto3.client("ec2", region_name=r)
        vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        subnets = [ec2.create_subnet(VpcId=vpc, CidrBlock=f"10.0.{i}.0/24", AvailabilityZone=f"{r}{z}")["Subnet"]["SubnetId"]
                   for i, z in ((1, "a"), (2, "b"))]
        elb = boto3.client("elbv2", region_name=r)
        lb = elb.create_load_balancer(Name="shop-alb", Subnets=subnets, Scheme="internet-facing")["LoadBalancers"][0]
        tg = elb.create_target_group(Name="tg", Protocol="HTTP", Port=80, VpcId=vpc)["TargetGroups"][0]
        elb.create_listener(LoadBalancerArn=lb["LoadBalancerArn"], Protocol="HTTPS", Port=443,
                            SslPolicy="ELBSecurityPolicy-TLS13-1-2-PQ-2025-09", Certificates=[{"CertificateArn": cert_arn}],
                            DefaultActions=[{"Type": "forward", "TargetGroupArn": tg["TargetGroupArn"]}])

        from qmigrate.server.connectors.aws import AwsConnector
        con = AwsConnector({"regions": r})
        assert con.test()["ok"]
        by_id = _check(con.discover())
    key = f"AWS-KMS-{sym['KeyId'][:8]}"
    assert by_id[key]["algorithm"] == "AES-256" and by_id[key]["data_sensitivity"] == 5
    assert {a["algorithm"] for a in by_id.values()} >= {"RSA-2048", "ECDSA-P384", "X25519+ML-KEM-768"}
    p384 = next(a for a in by_id.values() if a["algorithm"] == "ECDSA-P384")
    assert p384["usage"] == "signature" and p384["data_sensitivity"] == 5          # from the tag
    assert by_id["AWS-LB-shop-alb"]["exposure"] == "internet"


def test_aws_policy_mapping():
    from qmigrate.server.connectors.aws import elb_policy_kex
    assert elb_policy_kex("ELBSecurityPolicy-TLS13-1-2-PQ-2025-09")[0] == "X25519+ML-KEM-768"
    assert elb_policy_kex("ELBSecurityPolicy-TLS13-1-2-2021-06")[0] == "X25519"
    assert elb_policy_kex("ELBSecurityPolicy-2016-08")[0] == "RSA-2048"


# ------------------------------------------------------------------ Azure (fake HTTP)
class _Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, ""

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(response=self)


class _Fake:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)
        for key, data in self.routes.items():
            if url.endswith(key):
                return _Resp(data)
        return _Resp({"value": []})


class _Cred:
    def get_token(self, scope):
        class T:
            token = "fake-token"
        return T()


def test_azure_connector():
    from qmigrate.server.connectors.azure import AzureConnector
    sub = "/subscriptions/s1"
    vault = f"{sub}/resourceGroups/rg/providers/Microsoft.KeyVault/vaults/qmvault"
    kv = "https://qmvault.vault.azure.net"
    der = x509.load_pem_x509_certificate(_pem().encode()).public_bytes(serialization.Encoding.DER)
    import base64
    routes = {
        "/subscriptions/s1": {"displayName": "Student subscription"},
        "/Microsoft.KeyVault/vaults": {"value": [{"id": vault, "name": "qmvault", "location": "francecentral",
                                                    "properties": {"vaultUri": kv + "/"}}]},
        f"{vault}/keys": {"value": [
            {"id": f"{vault}/keys/cmk", "name": "cmk", "properties": {"kty": "RSA", "keySize": 3072, "keyOps": ["wrapKey", "unwrapKey"]}},
            {"id": f"{vault}/keys/sign", "name": "sign", "properties": {"kty": "EC", "curveName": "P-256", "keyOps": ["sign", "verify"]}}]},
        f"{kv}/certificates": {"value": [{"id": f"{kv}/certificates/web"}]},
        f"{kv}/certificates/web": {"policy": {"key_props": {"kty": "RSA", "key_size": 2048}}, "cer": base64.b64encode(der).decode()},
        "/Microsoft.Network/applicationGateways": {"value": [{"id": f"{sub}/agw1", "name": "agw1", "location": "francecentral",
            "properties": {"httpListeners": [{"properties": {"protocol": "Https"}}],
                           "frontendIPConfigurations": [{"properties": {"publicIPAddress": {"id": "pip"}}}],
                           "sslPolicy": {"policyName": "AppGwSslPolicy20150501"},
                           "sslCertificates": [{"properties": {"keyVaultSecretId": f"{kv}/secrets/web/abc123"}}]}}]},
        "/Microsoft.Storage/storageAccounts": {"value": [{"id": f"{sub}/st1", "name": "st1", "location": "francecentral",
            "properties": {"encryption": {"keySource": "Microsoft.Keyvault",
                                          "keyvaultproperties": {"keyname": "cmk", "keyvaulturi": kv + "/"}}}}]},
        "/Microsoft.Sql/servers": {"value": [{"id": f"{sub}/sql1", "name": "sql1", "location": "francecentral"}]},
        f"{sub}/sql1/encryptionProtector/current": {"properties": {"uri": f"{kv}/keys/cmk/v1"}},
        f"{sub}/sql1/databases": {"value": [{"id": f"{sub}/sql1/db1", "name": "patients"}, {"id": "m", "name": "master"}]},
    }
    con = AzureConnector({"subscription_id": "s1"}, session=_Fake(routes), credential=_Cred())
    assert con.test()["ok"]
    by_id = _check(inv := con.discover())
    assert by_id["AZ-KV-qmvault-cmk"]["algorithm"] == "RSA-3072"
    assert by_id["AZ-KV-qmvault-sign"]["algorithm"] == "ECDSA-P256"
    assert by_id["AZ-CERT-qmvault-web"]["algorithm"] == "ECDSA-P256"        # read from the real certificate
    assert by_id["AZ-AGW-agw1"]["algorithm"] == "RSA-2048" and by_id["AZ-AGW-agw1"]["exposure"] == "internet"
    edges = {(e["source"], e["target"]) for e in inv["edges"]}
    assert ("AZ-AGW-agw1", "AZ-CERT-qmvault-web") in edges
    assert ("AZ-ST-st1", "AZ-KV-qmvault-cmk") in edges and ("AZ-DB-sql1-patients", "AZ-KV-qmvault-cmk") in edges


# ------------------------------------------------------------------ Google Cloud (fake HTTP)
class _GResp(_Resp):
    pass


class _GFake:
    def __init__(self, routes):
        self.routes = routes

    def get(self, url, params=None, timeout=None):
        for key, data in self.routes.items():
            if url.endswith(key):
                return _GResp(data)
        return _GResp({})


def test_gcp_connector():
    from qmigrate.server.connectors.gcp import GcpConnector, kms_algorithm
    p = "projects/demo-proj"
    ring = f"{p}/locations/europe-west9/keyRings/main"
    key = f"{ring}/cryptoKeys/cmek"
    compute = "compute/v1/projects/demo-proj"
    cert_link = f"https://www.googleapis.com/{compute}/global/sslCertificates/web"
    proxy_link = f"https://www.googleapis.com/{compute}/global/targetHttpsProxies/web-proxy"
    pol_link = f"https://www.googleapis.com/{compute}/global/sslPolicies/old"
    routes = {
        "v1/projects/demo-proj": {"name": "Demo project"},
        f"{p}/locations": {"locations": [{"locationId": "europe-west9"}]},
        f"{p}/locations/europe-west9/keyRings": {"keyRings": [{"name": ring}]},
        f"{ring}/cryptoKeys": {"cryptoKeys": [
            {"name": key, "purpose": "ENCRYPT_DECRYPT", "versionTemplate": {"algorithm": "GOOGLE_SYMMETRIC_ENCRYPTION"}},
            {"name": f"{ring}/cryptoKeys/signer", "purpose": "ASYMMETRIC_SIGN", "versionTemplate": {"algorithm": "RSA_SIGN_PSS_3072_SHA256"}},
            {"name": f"{ring}/cryptoKeys/pq", "purpose": "ASYMMETRIC_SIGN", "versionTemplate": {"algorithm": "PQ_SIGN_ML_DSA_65"}}]},
        f"{compute}/aggregated/sslCertificates": {"items": {"global": {"sslCertificates": [
            {"name": "web", "selfLink": cert_link, "certificate": _pem()}]}}},
        f"{compute}/global/sslPolicies": {"items": [{"selfLink": pol_link, "profile": "COMPATIBLE", "minTlsVersion": "TLS_1_0"}]},
        f"{compute}/aggregated/forwardingRules": {"items": {"global": {"forwardingRules": [
            {"loadBalancingScheme": "EXTERNAL_MANAGED", "target": proxy_link}]}}},
        f"{compute}/aggregated/targetHttpsProxies": {"items": {"global": {"targetHttpsProxies": [
            {"name": "web-proxy", "selfLink": proxy_link, "sslPolicy": pol_link, "sslCertificates": [cert_link]}]}}},
        "v1/projects/demo-proj/instances": {"items": [{"name": "orders", "region": "europe-west9",
            "diskEncryptionConfiguration": {"kmsKeyName": key + "/cryptoKeyVersions/1"}}]},
        "storage/v1/b": {"items": [{"name": "qm-backups", "location": "EU", "encryption": {"defaultKmsKeyName": key}}]},
    }
    con = GcpConnector({"project_id": "demo-proj"}, session=_GFake(routes))
    assert con.test()["ok"]
    by_id = _check(inv := con.discover())
    assert by_id["GCP-KMS-cmek"]["algorithm"] == "AES-256"
    assert by_id["GCP-KMS-signer"]["algorithm"] == "RSA-3072"
    assert by_id["GCP-KMS-pq"]["algorithm"] == "ML-DSA-65"
    assert by_id["GCP-CERT-web"]["algorithm"] == "ECDSA-P256"
    assert by_id["GCP-LB-web-proxy"]["algorithm"] == "RSA-2048" and by_id["GCP-LB-web-proxy"]["exposure"] == "internet"
    edges = {(e["source"], e["target"]) for e in inv["edges"]}
    assert {("GCP-LB-web-proxy", "GCP-CERT-web"), ("GCP-SQL-orders", "GCP-KMS-cmek"), ("GCP-GCS-qm-backups", "GCP-KMS-cmek")} <= edges
    assert kms_algorithm("EC_SIGN_P384_SHA384", "ASYMMETRIC_SIGN")[0] == "ECDSA-P384"


# ------------------------------------------------------------------ several connections, one workspace
def test_connections_share_a_workspace(tmp_path, monkeypatch):
    """A small cloud account plus public websites: discovery of one keeps the other's assets."""
    from fastapi.testclient import TestClient

    from conftest import login, make_settings
    from qmigrate.realdata import collector as col
    from qmigrate.server.app import create_app
    from qmigrate.server.connectors.gcp import GcpConnector
    from test_realdata import _Hosting, _measured

    lab_leaf = x509.load_pem_x509_certificate(_pem().encode())
    lab = {"leaf": lab_leaf, "ca": lab_leaf}
    web = col.build_inventory(_measured(lab, 15), __import__("qmigrate.realdata.domain_lists", fromlist=["x"]).SECTORS["finance"],
                              {}, _Hosting())
    monkeypatch.setattr(col, "collect", lambda config, **kw: web)
    small = {"assets": [], "edges": []}

    def fake_discover(self, run_index=0):
        from qmigrate.server.connectors.inventory import Inventory
        inv = Inventory("GCP")
        k = inv.add("GCP-KMS-cmek", "kms_key", "RSA-2048", region="europe-west9", application="ring")
        d = inv.add("GCP-SQL-orders", "database", "AES-256", region="europe-west9", application="orders")
        inv.link(d, k, "uses_key")
        small.update(inv.result())
        return small
    monkeypatch.setattr(GcpConnector, "discover", fake_discover)

    s, _ = make_settings(tmp_path, "sqlite")
    s.data_source = "public"
    with TestClient(create_app(s, seed_in_background=False), headers={"X-QM-Request": "1"}) as c:
        c.app_settings = s
        login(c, "admin@demofinance.example")
        before = c.get("/api/assets").json()
        n_before = len(before["items"] if isinstance(before, dict) and "items" in before else before)
        r = c.post("/api/connections", json={"provider": "gcp", "display_name": "GCP", "config": {"project_id": "demo-proj"}})
        assert r.status_code == 200 and r.json()["status"] == "connected"
        c.post("/api/discovery/run", json={"connection_id": r.json()["id"]})
        import time
        for _ in range(120):
            runs = c.get("/api/discovery/runs").json()
            if runs[0]["status"] != "running":
                break
            time.sleep(0.5)
        assert runs[0]["status"] == "completed", runs[0]
        after = c.get("/api/assets").json()
        rows = after["items"] if isinstance(after, dict) and "items" in after else after
        assert len(rows) == n_before + 2
        assert "GCP" in {r["cloud"] for r in rows} and any(r["asset_id"].startswith("TLS-") for r in rows)


def test_same_websites_from_a_second_connection_and_double_clicks(tmp_path, monkeypatch):
    """Regression: 'UNIQUE constraint failed: assets.tenant_id, assets.asset_id'. A second public-websites
    connection that finds the same sites takes them over, duplicate rows are ignored, and clicking
    Run discovery twice starts only one run."""
    import threading
    import time

    from fastapi.testclient import TestClient

    from conftest import login, make_settings
    from qmigrate.realdata import collector as col
    from qmigrate.server.app import create_app
    from test_realdata import _Hosting, _measured

    lab_leaf = x509.load_pem_x509_certificate(_pem().encode())
    web = col.build_inventory(_measured({"leaf": lab_leaf, "ca": lab_leaf}, 15),
                              __import__("qmigrate.realdata.domain_lists", fromlist=["x"]).SECTORS["finance"], {}, _Hosting())
    gate = threading.Event()

    def slow_collect(config, **kw):
        gate.wait(5)
        return {"assets": web["assets"] + web["assets"][:3], "edges": web["edges"]}   # includes duplicates
    monkeypatch.setattr(col, "collect", lambda config, **kw: web)

    s, _ = make_settings(tmp_path, "sqlite")
    s.data_source = "public"
    with TestClient(create_app(s, seed_in_background=False), headers={"X-QM-Request": "1"}) as c:
        c.app_settings = s
        login(c, "admin@demofinance.example")
        n = len(c.get("/api/assets").json())
        r = c.post("/api/connections", json={"provider": "public", "display_name": "Banks again",
                                              "config": {"source": "finance", "top": 15}})
        assert r.status_code == 200, r.text
        monkeypatch.setattr(col, "collect", slow_collect)
        first = c.post("/api/discovery/run", json={"connection_id": r.json()["id"]}).json()
        second = c.post("/api/discovery/run", json={"connection_id": r.json()["id"]}).json()
        assert first == second, "a second click joins the running discovery"
        gate.set()
        for _ in range(120):
            runs = c.get("/api/discovery/runs").json()
            if runs[0]["status"] != "running":
                break
            time.sleep(0.5)
        assert runs[0]["status"] == "completed", runs[0]
        assert len(c.get("/api/assets").json()) == n
