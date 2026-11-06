# Deploy on a Hetzner Cloud server (EU) with HTTPS

Result: **https://qmigrate.awhlle.com** running Caddy (automatic HTTPS) → engine → PostgreSQL, plus the simulator and
daily backups, all in Docker Compose on one Ubuntu server in Germany or Finland.

Time: about 45 minutes the first time.

## 0. Before you start

- A Hetzner Cloud account (https://console.hetzner.cloud).
- Access to the DNS settings of `awhlle.com` (where the domain was bought).
- On your laptop: an SSH client (Windows 10/11 has `ssh` in PowerShell) and the project folder.

**Price (check before ordering).** Hetzner raised cloud prices in 2026 and its cheapest "Cost-Optimized" CX and CAX
plans were shown as *currently not available* in August–September 2026. A **CPX22** (2 shared vCPU, 4 GB RAM, 80 GB
NVMe) was listed at about **€20/month excluding VAT** (plus about €0.50/month for the IPv4 address). If a CX or CAX plan
with 2 vCPU / 4 GB is available again when you order, it is cheaper and works the same way. Always confirm on Hetzner's
own pricing page.

## 1. Create the server

1. Hetzner Cloud console → **New project** → *Q-MigrateAI* → **Add server**.
2. **Location:** Falkenstein or Nuremberg (Germany) or Helsinki (Finland), so data stays in the EU.
3. **Image:** Ubuntu 24.04.
4. **Type:** shared vCPU, 2 vCPU / 4 GB RAM (for example CPX22).
5. **SSH key:** on your laptop run `ssh-keygen -t ed25519` (press Enter for the defaults), then paste the content of
   `C:\Users\<you>\.ssh\id_ed25519.pub` into Hetzner. Do not use password login.
6. **Firewall:** create one allowing inbound **TCP 22, 80, 443** only. Attach it to the server.
7. Create, and note the server's **public IPv4 address**, for example `203.0.113.10`.

## 2. Point the domain at the server

At your DNS provider, add an **A record**:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `qmigrate` | `203.0.113.10` (your server IP) | 300 |

Check from your laptop after a few minutes: `nslookup qmigrate.awhlle.com` must show the server IP.
Caddy cannot get the HTTPS certificate until this works.

## 3. Install Docker on the server

```bash
ssh root@203.0.113.10

apt update && apt -y upgrade
apt -y install ca-certificates curl unattended-upgrades
curl -fsSL https://get.docker.com | sh          # official Docker install script
docker compose version                          # should print a version

# a normal user for running the app
adduser --disabled-password --gecos "" qmigrate
usermod -aG docker qmigrate
mkdir -p /home/qmigrate/.ssh && cp ~/.ssh/authorized_keys /home/qmigrate/.ssh/ && chown -R qmigrate: /home/qmigrate/.ssh
```

Optional hardening: in `/etc/ssh/sshd_config` set `PermitRootLogin no` and `PasswordAuthentication no`, then
`systemctl restart ssh` (test logging in as `qmigrate` first).

## 4. Copy the project to the server

From your laptop, in the folder that contains `qmigrate-platform`:

```powershell
scp -r qmigrate-platform qmigrate@203.0.113.10:/home/qmigrate/
```

(Do not copy your laptop's `.venv` or `data` folders; they are not needed. Delete them from the copy or zip without them.)

## 5. Create the `.env` file with secrets

```bash
ssh qmigrate@203.0.113.10
cd ~/qmigrate-platform
cp .env.example .env
python3 -c "import secrets; [print(secrets.token_urlsafe(32)) for _ in range(4)]"   # four random values
nano .env
```

Fill in:

- `SITE_ADDRESS=qmigrate.awhlle.com` and `PUBLIC_URL=https://qmigrate.awhlle.com`
- `SECRET_KEY`, `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`: three **different** random values from above
- `DEMO_PASSWORD`: a password for the demo accounts (10+ characters with upper case, lower case and a digit), or
  `SEED_DEMO=0` if real customers will use this server
- SMTP settings if you want e-mail alerts (optional)

Then protect the file: `chmod 600 .env`. Never send `.env` by e-mail or put it in Git.

## 6. Start

```bash
docker compose up -d --build
docker compose ps                 # all services "running" / "healthy"
docker compose logs -f engine     # wait for "Application startup complete"; Ctrl+C to leave the log
```

Open **https://qmigrate.awhlle.com**. The first start trains the models for the demo companies (about one minute on a
small server). Caddy obtains the Let's Encrypt certificate automatically on the first visit.

## 7. Backups

The `backup` service writes `backups/qmigrate_<date>.sql.gz` every 24 hours and keeps 14 days
(`BACKUP_KEEP_DAYS` in `.env`).

- Copy backups off the server regularly (for example `scp` to your laptop, or enable Hetzner's server backups too).
- Restore a backup (replaces the current data):

```bash
docker compose stop engine
docker compose exec postgres psql -U postgres -c "DROP DATABASE qmigrate WITH (FORCE)" -c "CREATE DATABASE qmigrate"
gunzip -c backups/qmigrate_YYYY-MM-DD_HHMM.sql.gz | docker compose exec -T postgres psql -U postgres -d qmigrate
docker compose start engine
```

A backup taken from this stack was restored this way during testing (no errors, all tenants and assets back).

## 8. Updates

```bash
cd ~/qmigrate-platform
# copy the new project files over the old ones (keep .env and backups/), then:
docker compose up -d --build
docker image prune -f
```

## 9. Useful commands

| Task | Command |
|---|---|
| Status | `docker compose ps` |
| Logs | `docker compose logs -f engine` (or `caddy`, `postgres`, `backup`) |
| Restart | `docker compose restart engine` |
| Stop everything | `docker compose down` (data stays in Docker volumes) |
| Health check | `curl -s https://qmigrate.awhlle.com/api/health` |

## 10. Checklist before showing it to anyone

- [ ] `https://` padlock shows in the browser
- [ ] `/api/health` shows `"database":"postgres","rls_enforced":true`
- [ ] `.env` has no `change-me` values (the app refuses to start otherwise)
- [ ] Demo password changed from the laptop default, or `SEED_DEMO=0`
- [ ] Privacy policy reviewed (it is a template) and the privacy contact mailbox exists
- [ ] A backup file exists in `backups/` after the first day
