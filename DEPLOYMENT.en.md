# GPU Monitor Secure Deployment Guide

[English](DEPLOYMENT.en.md) | [中文](DEPLOYMENT.md)

This guide describes the production-safe path. See [Security Hardening](SECURITY_HARDENING.md)
for existing-install migration details.

## 1. Security boundary

```text
User --HTTPS--> Nginx/gateway --127.0.0.1:8300--> GPU Monitor
                                                 |--TLS/Unix socket--> MySQL
                                                 |--SSH--> monitored hosts
                                                 `--IPMI lanplus--> BMCs
```

- Compose publishes the app on loopback only. Never expose port 8300 directly.
- Non-loopback MySQL must use TLS, and port 3306 must not be public.
- Monitored hosts require no agent, but must use a dedicated low-privilege `gpumon` account.
  Root SSH is denied by default.
- Browsers must use HTTPS with `COOKIE_SECURE=yes`.

## 2. Prerequisites

- Docker Engine and Docker Compose v2;
- a trusted TLS certificate and DNS name;
- restricted egress from the monitor to required SSH/BMC networks;
- SQLite or a TLS-enabled MySQL 8.x database;
- working `nvidia-smi` on monitored GPU hosts.

Create the least-privilege account on each monitored host, for example:

```bash
sudo useradd --create-home --shell /bin/bash gpumon
sudo install -d -m 700 -o gpumon -g gpumon /home/gpumon/.ssh
```

Prefer an ED25519 key and apply `restrict`, `no-port-forwarding`, `no-agent-forwarding`,
`no-X11-forwarding`, and `no-pty` in `authorized_keys`. Add only explicitly required
`nvme`/`journalctl` commands to a precise sudo allowlist.

## 3. Create local configuration

```bash
git clone https://github.com/Palpitate-xus/lab-gpu-server-monitor.git
cd lab-gpu-server-monitor
cp .env.example .env
chmod 600 .env
mkdir -p data/known_hosts secrets
sudo chown -R 10001:10001 data secrets
chmod 700 data data/known_hosts secrets
```

Run the following three times. Each output must be used for exactly one setting:

```bash
openssl rand -hex 32
```

Minimal new-install `.env`:

```ini
JWT_SIGNING_KEY=<independent-random-value>
CREDENTIAL_ENCRYPTION_KEYS=<different-random-value>
ARCHIVE_ENCRYPTION_KEY=<third-independent-64-hex-value>

DATABASE_URL=sqlite:///./data/gpu_monitor.db
AUTO_MIGRATE=no

INIT_ADMIN_USERNAME=<initial-admin-name>
INIT_ADMIN_PASSWORD=<random-16-to-72-character-password>

COOKIE_SECURE=yes
COOKIE_SAMESITE=strict
TRUST_PROXY=no
TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128
REQUIRE_ADMIN_MFA=yes
REMOTE_PROCESS_CONTROL_ENABLED=no
ALLOW_ROOT_SSH=no
ARCHIVE_DIR=/app/archives
```

Leave `TRUST_PROXY=no` until you have verified the direct peer address the application actually
sees for Nginx. Then place that exact `/32` (or IPv6 `/128`) in `TRUSTED_PROXY_CIDRS` before setting
`TRUST_PROXY=yes`; do not trust a whole Docker or office subnet for convenience. Production HTTPS
mode refuses to start until this is configured, preventing login limits from collapsing every user
into one shared proxy identity. Uvicorn does not interpret forwarding headers itself—the application
resolves them only through this allowlist.

Startup rejects missing/public/reused secrets, weak MySQL runtime accounts, and plaintext
non-loopback MySQL. Never commit `.env`, `secrets/`, databases, or archives.

### MySQL

Do not publish MySQL with `-p 3306:3306`. Use `deploy/mysql-hardening.sql.example` to create:

- `gpumon_migrate`, a short-lived DDL account used only during maintenance;
- `gpumon_app`, a runtime account restricted to `SELECT/INSERT/UPDATE/DELETE`.

Place the CA and optional client certificate/key under `./secrets`, owned by
`10001:10001`, with the directory at 0700 and files at 0400:

```ini
DATABASE_URL=mysql+pymysql://gpumon_app:<URL-encoded-password>@db.internal:3306/gpu_monitor?charset=utf8mb4
DATABASE_SSL_CA=/run/secrets/gpu-monitor/mysql-ca.pem
DATABASE_SSL_CERT=/run/secrets/gpu-monitor/mysql-client.pem
DATABASE_SSL_KEY=/run/secrets/gpu-monitor/mysql-client.key
```

URL-encode `@:/?#%` in passwords. Bind MySQL only to an internal interface and firewall its source.

### Optional Redis cache

Leave `REDIS_URL=` empty for the single-worker deployment. A remote shared cache must use
`rediss://` with an authentication password of at least 16 characters. Certificate and hostname
verification are mandatory, and TLS override query parameters are rejected. Mount a private CA
read-only and set `REDIS_SSL_CA` when needed. Only a literal loopback address or Unix socket may
use plaintext transport. Cached values are size-bounded JSON; pickle is never used.

## 4. Run schema migrations explicitly

The web/scheduler process does not execute DDL. Run the maintenance service with a temporary
migration connection before starting the app:

```bash
# SQLite path inside the container
MIGRATION_DATABASE_URL='sqlite:////app/data/gpu_monitor.db' \
  docker compose --profile maintenance run --rm gpu-monitor-migrate

# MySQL: keep the password out of shell history
read -rsp 'Migration DATABASE_URL: ' MIGRATION_DATABASE_URL && echo
export MIGRATION_DATABASE_URL
docker compose --profile maintenance run --rm gpu-monitor-migrate
unset MIGRATION_DATABASE_URL
```

A migration failure returns nonzero. Do not start or restart production after a failed migration.

## 5. Build, start, and enable HTTPS

Compose uses a multi-stage build, frozen pnpm lock, and fully hashed Python lock:

```bash
export GPU_MONITOR_IMAGE="gpu-monitor:$(git rev-parse --short=12 HEAD)"
docker compose config --quiet
docker compose build --pull
docker compose up -d
docker compose ps
docker compose logs --since=10m gpu-monitor
```

The Wolfi and Node bases, Python wheels, and source-built `ipmitool` are protected by immutable
digests or hashes. Resolved Wolfi APK versions are captured in the CI CycloneDX SBOM; a weekly
rebuild detects repository drift and newly disclosed CVEs. Production must resolve the scanned
commit-SHA tag to a registry digest before deployment and must not rely on the tag alone.

Install `deploy/nginx-gpu-monitor.conf.example` after replacing its hostname and certificate paths:

```bash
sudo nginx -t
sudo systemctl reload nginx
curl --fail https://gpu-monitor.example.com/api/health
curl --fail https://gpu-monitor.example.com/api/ready
```

`/api/health` is liveness. `/api/ready` also checks the database, scheduler heartbeat, and real
write access to both the SSH host-key and archive directories. Browsers must use the HTTPS name,
never `http://<host>:8300`.

## 6. First login

There is no default account or password. A fresh database uses the one-time initial administrator
credentials from `.env`. After login:

1. enroll and verify the TOTP secret immediately;
2. replace the one-time password;
3. remove `INIT_ADMIN_USERNAME` and `INIT_ADMIN_PASSWORD` from the active `.env`, restart, and verify login;
4. create at least one additional administrator and normal Viewer accounts;
5. give MCP a dedicated Viewer account, never an administrator account.

Until enrollment succeeds, every privileged API returns 403.
Webhook URLs often contain bot tokens. They are encrypted with the credential key after save; the
management API returns only configured state and a redacted endpoint, never the full stored URL.

## 7. Add monitored servers

Open Servers, enter the target, port, `gpumon` user, and authentication material. First use applies
TOFU: the fingerprint is atomically persisted under `data/known_hosts`; failure to persist aborts
the connection. After a reinstall, verify the new fingerprint out of band before an administrator
resets trust. Reset requires password re-authentication and the exact out-of-band `SHA256:...`
fingerprint; the service fetches, compares, and atomically pins the new key instead of returning to TOFU.

Full live processes, inventory, and IPMI details are administrator-only. History does not retain
login identities, process users, or full argv. Remote kill/renice is disabled by default and still
requires an MFA-authenticated session plus password re-authentication if enabled. Process start identity is
rechecked before the command so a recycled PID cannot target another process.

## 8. Upgrade and rollback

Record exact versions and take encrypted backups first:

```bash
git rev-parse HEAD
docker image inspect "$GPU_MONITOR_IMAGE" --format '{{.Id}}'
umask 077
# Back up the database, known_hosts, encrypted .env, and archives.
```

Pull a reviewed commit, inspect the diff, build a commit-SHA candidate image, run section 4
migrations, then switch the container. Production `GPU_MONITOR_IMAGE` must name the scanned commit
tag or a registry digest; never deploy floating `latest` or an unreviewed worktree.

Rollback with the recorded commit and image digest. Migrations 012/013 only add security columns,
which older versions generally ignore; however, the old app still requires `SECRET_KEY`. Keep an
encrypted copy of the previous `.env` until the upgrade is accepted, and never commit it.

See `SECURITY_HARDENING.md` for migrating an existing single `SECRET_KEY`, scrubbing historical
process identity, and rotating the credential keyring.

## 9. MFA recovery

Prefer another enrolled administrator resetting the target from User Management; this also revokes
all target sessions. For a single-admin lost-device event, use the break-glass script on the trusted
host:

```bash
docker compose exec gpu-monitor python scripts/reset_admin_mfa.py --username target_admin
docker compose exec gpu-monitor python scripts/reset_admin_mfa.py --username target_admin --apply
```

Immediately log in, re-enroll MFA, and review the `user.mfa_breakglass_reset` audit entry.

## 10. Release gates

```bash
python -m pytest -q backend/tests
python -m pytest -q mcp_server/tests
cd frontend && pnpm test && pnpm audit --prod && pnpm build && cd ..
export GPU_MONITOR_IMAGE="gpu-monitor:$(git rev-parse --short=12 HEAD)"
docker compose config --quiet
```

CI also runs Ruff, Bandit, `pip-audit`, Gitleaks, a final-image High/Critical CVE gate, and creates a
CycloneDX SBOM. The source-built `ipmitool` component is added explicitly with its commit and binary
SHA-256. Do not release until image, TLS/firewall, database grants, backup restore, and SSH fingerprint
staging exercises all pass.
