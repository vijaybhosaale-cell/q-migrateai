"""Data sources: public websites (real, default), AWS, Azure and Google Cloud (real, read-only).

The cloud connectors (aws.py, azure.py, gcp.py) sign in with the cloud's own command-line login on
this PC (`aws configure`, `az login`, `gcloud auth application-default login`), so the platform never
stores a cloud password or key. They only list and describe resources.
"""
from __future__ import annotations

import os


from qmigrate.server.connectors.aws import AwsConnector  # noqa: E402,F401
from qmigrate.server.connectors.azure import AzureConnector  # noqa: E402,F401
from qmigrate.server.connectors.gcp import GcpConnector  # noqa: E402,F401


AWS_READ_ONLY_POLICY = {
    "Version": "2012-10-17",
    "Statement": [{
        "Sid": "QMigrateCryptoInventoryReadOnly",
        "Effect": "Allow",
        "Action": [
            "kms:ListKeys", "kms:ListAliases", "kms:DescribeKey", "kms:GetKeyRotationStatus",
            "acm:ListCertificates", "acm:DescribeCertificate",
            "elasticloadbalancing:DescribeLoadBalancers", "elasticloadbalancing:DescribeListeners",
            "elasticloadbalancing:DescribeSSLPolicies",
            "cloudfront:ListDistributions", "rds:DescribeDBInstances", "s3:GetEncryptionConfiguration",
            "s3:ListAllMyBuckets",
        ],
        "Resource": "*",
    }],
}

PROVIDERS = {
    "public": {
        "title": "Public websites (real data)", "status": "available",
        "summary": "Real, live data: checks the TLS key exchange (including post-quantum X25519MLKEM768), "
                   "certificate chain and hosting cloud of real organisations' public websites. Needs internet; no credentials.",
        "access": [
            "Choose a sector list (real banks and payment companies, or real hospitals and health agencies), "
            "the most popular websites from the Tranco research list, or type your own domains.",
            "Discovery makes one ordinary HTTPS connection per website, like a browser, and reads only public "
            "information: the certificate chain and the key exchange the server accepts.",
            "The hosting cloud (AWS, Azure, Google Cloud, Cloudflare) comes from the IP address lists those providers publish.",
        ],
        "fields": [
            {"key": "source", "label": "Websites to check", "type": "select", "options": ["finance", "health", "tranco", "custom"]},
            {"key": "top", "label": "How many websites (5-300)", "type": "number"},
            {"key": "domains", "label": "Your domains, comma-separated (for 'custom')", "type": "text",
             "placeholder": "example.com, example.org"},
        ],
    },
    "simulator": {
        "title": "Demo cloud (simulator)", "status": "available",
        "summary": "A realistic synthetic AWS / Azure / GCP estate for demos and training. Nothing real is scanned.",
        "access": ["No credentials needed."],
        "fields": [
            {"key": "profile", "label": "Industry profile", "type": "select", "options": ["generic", "bank", "hospital"]},
            {"key": "seed", "label": "Seed (same seed = same estate)", "type": "number"},
            {"key": "assets", "label": "Approximate number of assets", "type": "number"},
        ],
    },
    "aws": {
        "title": "Amazon Web Services", "status": "available",
        "summary": "Real, read-only: KMS keys, ACM certificates, load balancer TLS policies (including AWS post-quantum policies), "
                   "RDS and S3 encryption, CloudFront. Uses the AWS CLI login on this PC.",
        "access": [
            "In the AWS console, IAM > Users > Create user (for example qmigrate-readonly). Attach the AWS managed "
            "policies SecurityAudit and AWSCertificateManagerReadOnly (or the narrower read-only policy below).",
            "Create an access key for that user (IAM > Users > Security credentials > Create access key > CLI).",
            "On this PC install the AWS CLI and run: aws configure  (paste the key, choose your region, e.g. eu-west-3). "
            "The key stays in your AWS CLI settings; Q-MigrateAI never stores it.",
            "Here, type the regions to scan. Leave Profile empty unless you used aws configure --profile NAME. "
            "Optional: a Role ARN to assume (it must trust your user and require the External ID shown).",
        ],
        "policy": AWS_READ_ONLY_POLICY,
        "fields": [
            {"key": "regions", "label": "Regions (comma-separated)", "type": "text", "placeholder": "eu-west-3,us-east-1"},
            {"key": "profile", "label": "AWS CLI profile (optional)", "type": "text", "placeholder": "default"},
            {"key": "role_arn", "label": "Role ARN to assume (optional)", "type": "text", "placeholder": "arn:aws:iam::123456789012:role/QMigrateReadOnly"},
            {"key": "external_id", "label": "External ID (for the optional role)", "type": "readonly"},
        ],
    },
    "azure": {
        "title": "Microsoft Azure", "status": "available",
        "summary": "Real, read-only: Key Vault keys and certificates, Application Gateway TLS policies, Storage and SQL "
                   "encryption keys. Uses the Azure CLI login on this PC.",
        "access": [
            "In the Azure portal, give your account (or a dedicated one) the built-in role Reader on the subscription, "
            "and Key Vault Reader on each key vault (Access control (IAM) > Add role assignment).",
            "On this PC install the Azure CLI and run: az login  (a browser window opens to sign in). "
            "Q-MigrateAI uses that login and never stores a password or secret.",
            "Here, paste the Subscription ID (Portal > Subscriptions). Tenant ID is only needed if you have several directories.",
        ],
        "fields": [
            {"key": "subscription_id", "label": "Subscription ID", "type": "text", "placeholder": "00000000-0000-0000-0000-000000000000"},
            {"key": "tenant_id", "label": "Directory (tenant) ID (optional)", "type": "text"},
        ],
    },
    "gcp": {
        "title": "Google Cloud", "status": "available",
        "summary": "Real, read-only: Cloud KMS keys, SSL certificates, HTTPS load balancers and SSL policies, Cloud SQL and "
                   "Cloud Storage encryption keys. Uses the gcloud login on this PC.",
        "access": [
            "In the Google Cloud console, give your account the roles Viewer (roles/viewer) and Cloud KMS Viewer "
            "(roles/cloudkms.viewer) on the project (IAM & Admin > IAM > Grant access).",
            "On this PC install the Google Cloud CLI and run: gcloud auth application-default login  "
            "(a browser window opens to sign in). Q-MigrateAI uses that login and never stores a password or key.",
            "Here, type the Project ID (shown on the console dashboard).",
        ],
        "fields": [
            {"key": "project_id", "label": "Project ID", "type": "text", "placeholder": "my-project-123456"},
        ],
    },
}


# The synthetic simulator is switched off unless ENABLE_SIMULATOR=1 (used by the offline test suite).
if os.environ.get("ENABLE_SIMULATOR", "0").strip().lower() not in ("1", "true", "yes", "on"):
    PROVIDERS.pop("simulator")


def make_connector(provider: str, config: dict, simulator_url: str):
    from qmigrate.server.connectors.simulator import SimulatorConnector
    if provider == "public":
        from qmigrate.server.connectors.public_web import PublicWebConnector
        return PublicWebConnector(config)
    if provider == "simulator":
        return SimulatorConnector(config, simulator_url)
    return {"aws": AwsConnector, "azure": AzureConnector, "gcp": GcpConnector}[provider](config)
