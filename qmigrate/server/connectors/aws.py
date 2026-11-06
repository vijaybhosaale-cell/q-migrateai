"""AWS connector (read-only, boto3).

Credentials come from the standard AWS chain on this PC (`aws configure`, AWS_PROFILE, SSO), optionally
assuming a read-only role. Nothing is stored in the platform. Only list/describe/get calls are made:

  kms:ListKeys, kms:DescribeKey, kms:ListResourceTags          -> KMS keys (KeySpec, KeyUsage)
  acm:ListCertificates, acm:DescribeCertificate                -> certificates (KeyAlgorithm, InUseBy)
  elasticloadbalancing:DescribeLoadBalancers/Listeners/Tags    -> TLS listeners (SslPolicy, certificates)
  rds:DescribeDBInstances                                      -> encryption at rest (KmsKeyId)
  s3:ListAllMyBuckets, s3:GetEncryptionConfiguration, s3:GetBucketLocation, s3:GetBucketTagging
  cloudfront:ListDistributions                                 -> CDN TLS (ViewerCertificate)
  sts:GetCallerIdentity, sts:AssumeRole (optional)
"""
from __future__ import annotations

from qmigrate.server.connectors.base import CloudConnector
from qmigrate.server.connectors.inventory import Inventory, missing_package, short

KEYSPEC = {"SYMMETRIC_DEFAULT": "AES-256", "RSA_2048": "RSA-2048", "RSA_3072": "RSA-3072", "RSA_4096": "RSA-4096",
           "ECC_NIST_P256": "ECDSA-P256", "ECC_NIST_P384": "ECDSA-P384", "ECC_NIST_P521": "ECDSA-P384",
           "ECC_SECG_P256K1": "ECDSA-P256", "SM2": "ECDSA-P256", "HMAC_224": "SHA-256", "HMAC_256": "SHA-256",
           "HMAC_384": "SHA-384", "HMAC_512": "SHA-384", "ML_DSA_44": "ML-DSA-65", "ML_DSA_65": "ML-DSA-65",
           "ML_DSA_87": "ML-DSA-87"}
CERT_KEY = {"RSA_1024": "RSA-2048", "RSA_2048": "RSA-2048", "RSA_3072": "RSA-3072", "RSA_4096": "RSA-4096",
            "EC_prime256v1": "ECDSA-P256", "EC_secp384r1": "ECDSA-P384", "EC_secp521r1": "ECDSA-P384"}


def elb_policy_kex(policy: str | None) -> tuple[str, str]:
    """Key exchange implied by an ELB security policy name."""
    p = (policy or "").upper()
    if "PQ" in p:
        return "X25519+ML-KEM-768", "TLS 1.3 (post-quantum policy)"
    if "TLS13" in p:
        return "X25519", "TLS 1.2/1.3"
    if "2015" in p or "2016" in p or "TLS-1-0" in p or not p:
        return "RSA-2048", "TLS 1.0-1.2 (allows RSA key transport)"
    return "ECDHE-P256", "TLS 1.2"


def _tags(lst) -> dict:
    return {t.get("Key", t.get("TagKey")): t.get("Value", t.get("TagValue")) for t in (lst or [])}


class AwsConnector(CloudConnector):
    provider = "aws"
    title = "Amazon Web Services"

    def _session(self):
        try:
            import boto3
        except ImportError as exc:
            raise missing_package("AWS", "boto3") from exc
        session = boto3.Session(profile_name=self.config.get("profile") or None)
        role = (self.config.get("role_arn") or "").strip()
        if role:
            kwargs = {"RoleArn": role, "RoleSessionName": "qmigrate-readonly"}
            if self.config.get("external_id"):
                kwargs["ExternalId"] = self.config["external_id"]
            c = session.client("sts").assume_role(**kwargs)["Credentials"]
            session = boto3.Session(aws_access_key_id=c["AccessKeyId"], aws_secret_access_key=c["SecretAccessKey"],
                                    aws_session_token=c["SessionToken"])
        return session

    def _regions(self, session) -> list[str]:
        regions = [r.strip() for r in str(self.config.get("regions") or "").split(",") if r.strip()]
        return regions or [session.region_name or "eu-west-3"]

    def test(self) -> dict:
        try:
            s = self._session()
            who = s.client("sts").get_caller_identity()
            return {"ok": True, "status": "connected",
                    "message": f"Signed in to AWS account {who['Account']} as {who['Arn'].split('/')[-1]}; "
                               f"regions: {', '.join(self._regions(s))}."}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": "error", "message": f"AWS sign-in failed: {exc}. Run `aws configure` on this PC first."}

    def discover(self, run_index: int = 0) -> dict:
        s = self._session()
        if s.get_credentials() is None:
            raise RuntimeError("No AWS sign-in found on this PC. Install the AWS CLI, run `aws configure` with a "
                               "read-only access key, then click Test on this connection (see docs/CLOUD_SETUP.md).")
        inv = Inventory("AWS")
        for region in self._regions(s):
            self._kms(s, region, inv)
            self._acm(s, region, inv)
            self._elb(s, region, inv)
            self._rds(s, region, inv)
        self._s3(s, inv)
        self._cloudfront(s, inv)
        return inv.result()

    # ------------------------------------------------------------------ services
    def _kms(self, s, region, inv):
        kms = s.client("kms", region_name=region)
        for page in kms.get_paginator("list_keys").paginate():
            for k in page["Keys"]:
                meta = kms.describe_key(KeyId=k["KeyId"])["KeyMetadata"]
                if meta.get("KeyState") not in ("Enabled", "Disabled"):
                    continue
                spec = meta.get("KeySpec") or meta.get("CustomerMasterKeySpec") or "SYMMETRIC_DEFAULT"
                use = meta.get("KeyUsage", "ENCRYPT_DECRYPT")
                usage = {"SIGN_VERIFY": "signature", "KEY_AGREEMENT": "key_exchange",
                         "GENERATE_VERIFY_MAC": "hashing"}.get(use, "key_wrapping")
                alg = KEYSPEC.get(spec, "")
                if usage == "key_exchange" and alg.startswith("ECDSA"):
                    alg = "ECDHE-P256"
                tags = {}
                if meta.get("KeyManager") == "CUSTOMER":
                    try:
                        tags = _tags(kms.list_resource_tags(KeyId=k["KeyId"]).get("Tags"))
                    except Exception:  # noqa: BLE001
                        pass
                inv.add(f"AWS-KMS-{k['KeyId'][:8]}", "kms_key", alg, region=region,
                        application=meta.get("Description") or f"KMS key {k['KeyId'][:8]}",
                        owner="AWS managed" if meta.get("KeyManager") == "AWS" else "", tags=tags,
                        aliases=(k["KeyArn"], k["KeyId"]), usage=usage)

    def _acm(self, s, region, inv):
        acm = s.client("acm", region_name=region)
        for page in acm.get_paginator("list_certificates").paginate():
            for c in page["CertificateSummaryList"]:
                d = acm.describe_certificate(CertificateArn=c["CertificateArn"])["Certificate"]
                years = None
                if d.get("NotAfter"):
                    import datetime as dt
                    years = round(max((d["NotAfter"] - dt.datetime.now(dt.timezone.utc)).days / 365.25, 0), 1)
                aid = inv.add(f"AWS-CERT-{short(d.get('DomainName', c['CertificateArn'][-8:]), 30)}", "tls_certificate",
                              CERT_KEY.get(d.get("KeyAlgorithm", ""), ""), region=region,
                              application=d.get("DomainName", "certificate"), exposure="internet",
                              aliases=(c["CertificateArn"],), retention_years=years)
                for user in d.get("InUseBy", []):
                    inv.link(inv.resolve(user), aid, "trusts_cert")

    def _elb(self, s, region, inv):
        elb = s.client("elbv2", region_name=region)
        for page in elb.get_paginator("describe_load_balancers").paginate():
            for lb in page["LoadBalancers"]:
                listeners = elb.describe_listeners(LoadBalancerArn=lb["LoadBalancerArn"])["Listeners"]
                tls = [x for x in listeners if x.get("Protocol") in ("HTTPS", "TLS")]
                if not tls:
                    continue
                tags = {}
                try:
                    desc = elb.describe_tags(ResourceArns=[lb["LoadBalancerArn"]])["TagDescriptions"]
                    tags = _tags(desc[0]["Tags"]) if desc else {}
                except Exception:  # noqa: BLE001
                    pass
                alg, proto = elb_policy_kex(tls[0].get("SslPolicy"))
                aid = inv.add(f"AWS-LB-{short(lb['LoadBalancerName'])}", "load_balancer", alg, region=region,
                              application=lb.get("DNSName", lb["LoadBalancerName"]), tags=tags, protocol=proto,
                              exposure="internet" if lb.get("Scheme") == "internet-facing" else "internal",
                              aliases=(lb["LoadBalancerArn"],))
                for x in tls:
                    for cert in x.get("Certificates", []):
                        inv.link(aid, cert.get("CertificateArn"), "trusts_cert")

    def _rds(self, s, region, inv):
        rds = s.client("rds", region_name=region)
        for page in rds.get_paginator("describe_db_instances").paginate():
            for db in page["DBInstances"]:
                if not db.get("StorageEncrypted"):
                    inv.skipped.append(f"{db['DBInstanceIdentifier']}: storage not encrypted")
                    continue
                aid = inv.add(f"AWS-DB-{short(db['DBInstanceIdentifier'])}", "database", "AES-256", region=region,
                              application=f"{db.get('Engine', 'db')} {db['DBInstanceIdentifier']}",
                              tags=_tags(db.get("TagList")), exposure="internet" if db.get("PubliclyAccessible") else "internal",
                              aliases=(db.get("DBInstanceArn"),))
                inv.link(aid, db.get("KmsKeyId"), "uses_key")

    def _s3(self, s, inv):
        s3 = s.client("s3")
        for b in s3.list_buckets().get("Buckets", []):
            name = b["Name"]
            try:
                region = s3.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1"
                rules = s3.get_bucket_encryption(Bucket=name)["ServerSideEncryptionConfiguration"]["Rules"]
                sse = rules[0]["ApplyServerSideEncryptionByDefault"]
            except Exception:  # noqa: BLE001  (no encryption config readable)
                inv.skipped.append(f"{name}: encryption settings not readable")
                continue
            tags = {}
            try:
                tags = _tags(s3.get_bucket_tagging(Bucket=name).get("TagSet"))
            except Exception:  # noqa: BLE001
                pass
            aid = inv.add(f"AWS-S3-{short(name)}", "object_storage", "AES-256", region=region, application=name,
                          tags=tags, aliases=(f"arn:aws:s3:::{name}",))
            if sse.get("KMSMasterKeyID"):
                inv.link(aid, sse["KMSMasterKeyID"], "uses_key")

    def _cloudfront(self, s, inv):
        try:
            cf = s.client("cloudfront")
            items = cf.list_distributions().get("DistributionList", {}).get("Items", [])
        except Exception:  # noqa: BLE001
            return
        for d in items:
            vc = d.get("ViewerCertificate", {})
            proto = vc.get("MinimumProtocolVersion", "TLSv1.2_2021")
            alg = "X25519" if "2021" in proto or "2025" in proto else "ECDHE-P256"
            aid = inv.add(f"AWS-CDN-{d['Id']}", "load_balancer", alg, region="global", application=d.get("DomainName", d["Id"]),
                          exposure="internet", protocol=f"TLS ({proto})", aliases=(d.get("ARN"),))
            inv.link(aid, vc.get("ACMCertificateArn"), "trusts_cert")
