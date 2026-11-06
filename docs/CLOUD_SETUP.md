# Connect your own AWS, Azure or Google Cloud account

The three cloud connectors are **real and read-only**. They sign in with the cloud's own command-line
login on your PC, so Q-MigrateAI never stores a cloud password or key, and they only list and describe
resources. Nothing is created, changed or deleted in your cloud.

You need an account with a few resources in it. All three clouds have free or student offers. The test
resources below cost nothing or a few cents. **Delete them when you are done**, and set a budget alert.

| Cloud | Free offer | Sign-in command on your PC |
|---|---|---|
| AWS | [AWS Free Tier](https://aws.amazon.com/free/) | `aws configure` |
| Azure | [Azure for Students](https://azure.microsoft.com/free/students/) (no credit card, university e-mail) | `az login` |
| Google Cloud | [Free trial credit](https://cloud.google.com/free) | `gcloud auth application-default login` |

The AI models need at least **20 assets** in a workspace. A new cloud account has fewer, so add the cloud
connection to a workspace that also has **Public websites (real data)** (for example log in as
`admin@demofinance.example`). Each connection keeps its own assets; running one does not remove the others.

---

## AWS

1. **Install the AWS CLI**: https://aws.amazon.com/cli/ (Windows installer).
2. **Create a read-only user**: AWS console > IAM > Users > *Create user* `qmigrate-readonly` > *Attach policies directly*:
   `SecurityAudit` and `AWSCertificateManagerReadOnly`.
3. **Create an access key** for that user: *Security credentials* > *Create access key* > *Command Line Interface*.
4. On your PC, open a terminal and run `aws configure`. Paste the key and secret, region `eu-west-3` (Paris) or yours.
5. **Test resources** (cheap; region eu-west-3):
   - KMS > *Create key* > Symmetric (about $1/month while it exists; schedule deletion afterwards).
   - KMS > *Create key* > Asymmetric > Sign and verify > RSA_2048.
   - S3 > *Create bucket* > Default encryption: *SSE-KMS* with the symmetric key above.
   - Certificate Manager > *Request* a public certificate for any domain name (free; it is listed even while
     "Pending validation").
   - Optional (not free, about $16/month): an Application Load Balancer with an HTTPS listener. AWS offers
     post-quantum policies such as `ELBSecurityPolicy-TLS13-1-2-PQ-2025-09`, which the platform reports as hybrid ML-KEM.
6. **In Q-MigrateAI**: *Connect and discover* > *Amazon Web Services* > *Set up* > Regions `eu-west-3` > *Save*.
   Click **Test** (it shows your account number), then **Run discovery**.

## Azure

1. **Install the Azure CLI**: https://learn.microsoft.com/cli/azure/install-azure-cli-windows
2. Run `az login` (a browser opens). If you have several directories, note the Tenant ID.
3. **Roles**: Portal > Subscriptions > your subscription > *Access control (IAM)* > *Add role assignment* > **Reader**
   for your account. On each key vault, add **Key Vault Reader** (and *Key Vault Certificate User* if certificates are not listed).
4. **Test resources** (cheap):
   - *Key vaults* > *Create* (Standard tier, permission model *Azure role-based access control*). Give yourself
     *Key Vault Administrator* on it to create test items.
   - In the vault: *Keys* > *Generate* RSA 2048, and another EC P-256.
   - *Certificates* > *Generate* > Self-signed, subject `CN=test.example`.
   - *Storage accounts* > *Create* > Encryption: *Customer-managed key* > pick the RSA key.
5. **In Q-MigrateAI**: *Microsoft Azure* > *Set up* > paste the **Subscription ID** > *Save* > **Test** > **Run discovery**.

## Google Cloud

1. **Install the Google Cloud CLI**: https://cloud.google.com/sdk/docs/install
2. Run `gcloud auth application-default login` (a browser opens).
3. **Roles**: Console > IAM & Admin > IAM > *Grant access* to your account: **Viewer** and **Cloud KMS Viewer**.
   Enable the *Cloud Key Management Service (KMS) API*, and the *Compute Engine API* if you add certificates.
4. **Test resources** (cheap):
   - Security > Key Management > *Create key ring* (location `europe-west9`) > *Create key*: symmetric, and one
     asymmetric sign RSA 3072 (a few cents per month).
   - Cloud Storage > *Create bucket* > Encryption: *Cloud KMS key* > the symmetric key.
   - Network services > Load balancing > *Certificates* > *Create SSL certificate* > upload a self-signed certificate (free).
5. **In Q-MigrateAI**: *Google Cloud* > *Set up* > **Project ID** > *Save* > **Test** > **Run discovery**.

---

## What each connector reads

| | AWS | Azure | Google Cloud |
|---|---|---|---|
| Keys | KMS key spec and usage | Key Vault key type, size, curve | Cloud KMS algorithm and purpose |
| Certificates | ACM key algorithm, expiry, where used | Key Vault certificate (public part) | Compute SSL certificate (public PEM) |
| TLS endpoints | Load balancer listener security policy, CloudFront | Application Gateway TLS policy | HTTPS proxy SSL policy, external or internal |
| Data stores | RDS and S3 encryption key | Storage and SQL encryption key | Cloud SQL and Cloud Storage encryption key |
| Dependencies | store → KMS key, load balancer → certificate | store → Key Vault key, gateway → certificate | store → KMS key, proxy → certificate |

**Business context from tags**: add tags (AWS), tags (Azure) or labels (Google Cloud) to resources to set
`DataClassification` (public / internal / confidential / restricted or 1-5), `RetentionYears` and
`BusinessCriticality` (1-5). Without tags, sensible defaults per resource type are used.

**Limits**: TLS policies tell the platform which key exchanges a load balancer allows, not the one each client
negotiates; the mapping is in `aws.py`, `azure.py` and `gcp.py`. The connectors were tested against an AWS
imitation (moto) and recorded Azure / Google Cloud API answers; the first run on a real account may need small fixes.
