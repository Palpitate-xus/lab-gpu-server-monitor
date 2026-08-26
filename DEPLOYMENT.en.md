# Deployment Guide / 部署指南

[English](DEPLOYMENT.en.md) | [中文](DEPLOYMENT.md)

---

## Architecture at a Glance

```text
┌────────────────────────── Central Server (where you deploy Docker) ─────────────────────────┐
│  gpu-monitor container (FastAPI + scheduler + frontend static) ──→ MySQL (gpu_monitor db)    │
└──────────────┬──────────────────────────────────────────────────────────────────────────────┘
               │ outbound SSH (port 22 or custom)
     ┌─────────┼─────────┐
     ▼         ▼         ▼
  GPU server  GPU server  CPU server    ← monitored side: no agent required
```

Monitored servers only need: SSH enabled and a login account. All metrics are collected
over SSH with read-only commands; scripts run from stdin and never touch disk
(see README "Collection Security").

---

## 1. Prerequisites

### 1.1 Central Server

| Requirement | Notes |
|---|---|
| Docker + Docker Compose | v2 (`docker compose`) |
| Port 8300 (changeable) | Web UI and API |
| Outbound SSH to all monitored hosts | port 22 or custom |

### 1.2 Database (MySQL)

Use an existing MySQL 8.x instance, or start one:

```bash
docker run -d --name docker-mysql-1 \
  -e MYSQL_ROOT_PASSWORD=<root-password> \
  -e MYSQL_DATABASE=gpu_monitor \
  -e MYSQL_USER=gpumon \
  -e MYSQL_PASSWORD=<gpumon-password> \
  -p 3306:3306 mysql:8.0.39
```

The schema is created automatically by the app's migrations (`migrations/`,
idempotent, executed at startup) — **no manual table creation**.

> Prefer no MySQL? Set `DATABASE_URL=sqlite:///./data/gpu_monitor.db` in `.env`;
> data lands in the mounted volume `./data` with zero external dependencies.

### 1.3 Monitored GPU Servers

- `nvidia-smi` must work (driver installed)
- A dedicated low-privilege account is recommended:

```bash
# create the monitoring account on the monitored host
sudo useradd -m monitor
sudo passwd monitor            # or set up an SSH key
```

Optional hardening (strongly recommended): restrict the key in `authorized_keys`:

```
restrict,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA... monitor@central
```

No metric requires root; only `nvme smart-log` / `ipmitool` / `journalctl` may need
sudo — open them per single command (examples in README "Least sudo").

---

## 2. Deploy the Central Server

### 2.1 Clone the repository

```bash
git clone https://github.com/Palpitate-xus/lab-gpu-server-monitor.git
cd lab-gpu-server-monitor
```

### 2.2 Configure the secret key (required)

```bash
cp .env.example .env 2>/dev/null || true
# generate a key and write it into .env:
openssl rand -hex 32   # put the output into SECRET_KEY= in .env
```

`.env` (gitignored — never commit it):

```ini
SECRET_KEY=<output of openssl rand -hex 32>
DATABASE_URL=mysql+pymysql://gpumon:<gpumon-password>@<mysql-host>:3306/gpu_monitor?charset=utf8mb4
```

- MySQL running in Docker on the same host: use `172.17.0.1` (Docker bridge gateway)
- **SECRET_KEY encrypts SSH credentials and signs JWTs; losing or rotating it
  invalidates all stored server credentials — they must be re-entered**

### 2.3 Build the frontend (default flow in this repo)

```bash
cd frontend && pnpm install && pnpm build && cd ..
```

> The default Dockerfile assumes `frontend/dist` was built on the host (the author's
> machine cannot pull the node image from Docker Hub). With network access you can
> build in one step instead:
>
> ```bash
> docker build -f Dockerfile.multistage -t gpu-monitor:latest .
> ```
>
> Then replace `build: .` with `image: gpu-monitor:latest` in `docker-compose.yml`.

### 2.4 Start

```bash
docker compose up -d --build
```

On first start the app automatically: creates tables → creates the admin account
(`INIT_ADMIN_USERNAME/PASSWORD`, default `admin/admin123`) → starts the collection
scheduler.

### 2.5 Verify

```bash
curl http://127.0.0.1:8300/api/health        # {"status":"ok",...}
```

Open `http://<central-ip>:8300` in a browser, default `admin / admin123` —
**change the password immediately after logging in**.

---

## 3. Add Servers

1. Log in → "Servers" → "Add Server"
2. Fill in name / IP / SSH port / auth method (password, or private key + passphrase)
3. **Choose the type: GPU server / CPU server** (CPU servers skip all GPU panels and aggregations)
4. Click "Test Connection", then save once it passes

The first connection uses **TOFU**: the host key fingerprint is recorded under
`data/known_hosts/`; any later change raises an alert and stops collection
(anti-MITM). After confirming a reinstall, use "Reset Host Key" on the server's
detail page.

Data shows up in the cockpit within 30-60 seconds.

---

## 4. Upgrading

```bash
git pull
cd frontend && pnpm install && pnpm build && cd ..
docker compose up -d --build
```

Migrations run automatically (idempotent); data is preserved.

---

## 5. Operations Notes

| Item | Notes |
|---|---|
| Data retention | Configurable in Settings; 0 = keep forever |
| Backup | Back up the MySQL `gpu_monitor` database (or the SQLite file) + `./data/known_hosts/` |
| Logs | `docker logs -f gpu-monitor` |
| Change port | Edit the left side of `ports: - "8300:8000"` in `docker-compose.yml` |
| Reverse proxy | Nginx/Caddy can provide HTTPS; then set `TRUST_PROXY=yes` in `.env` (rate limiting honors X-Forwarded-For) |
| Cross-origin access | Same-origin by default; to allow cross-origin set a `CORS_ORIGINS=https://...` whitelist in `.env` |
| Key rotation | After changing `SECRET_KEY`, all SSH credentials must be re-entered (the UI shows `CRED_DECRYPT_FAILED`) |

---

## 6. FAQ

**Q: A newly added server keeps showing SSH unreachable?**
Check network/port/firewall. The error code distinguishes auth failure / DNS /
refused / timeout — follow the hint.

**Q: GPU cards show "No GPU detected"?**
Data appears only if `nvidia-smi` works on the monitored host; for CPU-only boxes,
choose the "CPU server" type when adding.

**Q: Forgot the admin password?**
Set `INIT_ADMIN_USERNAME/PASSWORD` in `.env` and recreate the user against an empty
database, or edit the MySQL users table directly (passwords are bcrypt). Simplest:
back up, `docker compose down`, wipe the database and start fresh
(the admin is only created on an empty database).

**Q: Login says "too many attempts, locked"?**
5 failures per IP/username locks for 10 minutes — wait, or restart the container
(the lock is in memory).

**Q: Monitor over a non-22 port?**
Enter the real port (e.g. 23333) in the "Port" field when adding the server.
