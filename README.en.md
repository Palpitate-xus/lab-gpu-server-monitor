# GPU Server Monitoring Platform

[English](README.en.md) | [中文](README.md)

A multi-server monitoring Docker app built on **Vue 3 + Element Plus + ECharts + FastAPI + SSH**,
with an **agentless architecture** (zero resident agents, zero listening ports on monitored servers).
Metric coverage is benchmarked against **btop** and extended with data-center-grade GPU health
monitoring (XID / ECC / PCIe / NVMe / RAID / kernel events / failure prediction).

```text
                 ┌────────────────┐
                 │ Central Server │  FastAPI + Scheduler + MySQL
                 └───────┬────────┘
                         │ SSH (key/password, TOFU hostkey)
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
      GPU Server 1   GPU Server 2   GPU Server N
      read-only command whitelist · LC_ALL=C · output capped · no files written
          │
     ==SECTION== delimited protocol (stdout)
          ▼
    Parse → MySQL → Dashboard/Alerts/Detectors
```

## Collection Tiers

| Tier | Frequency | Content |
|---|---|---|
| **fast** | every cycle (default 30-60s) | CPU (incl. iowait/per-core), memory (HugePages), disk space + inodes, per-device IO, NIC rates/errors/drops/link state, full GPU set (utilization / VRAM / temp / memory temp / power / clocks / pstate / **throttle reasons / ECC / PCIe link / retired pages** / compute resource use), minimized process resources, TCP/fd; login identities, process users, and full argv are not persisted |
| **kernel** | every cycle | `journalctl -k` incremental → **Xid / OOM / MCE / EDAC / PCIe AER / IO / NVMe / NFS / NIC reset** events (deduplicated by boot_id+hash) |
| **slow** | every 5 min | **NVMe SMART** (temperature / spare capacity / endurance / media errors / unexpected power loss), mdraid status, NFS mounts, systemd failed units, key services (sshd/docker/kubelet/slurmd/nvidia-persistenced), **MIG**, NVLink, IPMI/BMC sensors |
| **inventory** | every 24 h | machine-id, DMI/BIOS/serial, lscpu, **NUMA topology (node CPU/memory)**, `nvidia-smi topo -m`, PCI device NUMA affinity, disk/NIC inventory (serial/MAC as stable IDs), InfiniBand, NTP sync status |

## Built-in Health Detectors (13, independent of user rules)

`GPU_IDLE_VRAM_HELD` (idle-held/zombie: VRAM >30% with util ≈0 for 30 min),
`GPU_MISSING` (GPU UUID baseline comparison — fallen-off-the-bus detection), `GPU_ECC_UNCORRECTED`,
`GPU_XID`, `GPU_THERMAL_THROTTLE`, `NVME_HEALTH`, `RAID_DEGRADED`, `HOSTKEY_CHANGED`,
`SSH_FAULT` (distinguishes AUTH/DNS/REFUSED/TIMEOUT/HOSTKEY instead of a generic Offline),
`NFS_STALE`, `SERVICE_FAILED`, `OOM_KILL`, `STORAGE_BOTTLENECK`
(correlated diagnosis: GPU utilization drop + rising iowait + busy disk → suspected storage bottleneck).

**GPU risk score** (0-100, 24h window): weighted by Xid events ×20, uncorrected ECC ×5,
thermal throttling, high temperature, PCIe link degradation; ≥60 critical / ≥30 watch.
GPUs are identified **by UUID**; baselines record additions/disappearances automatically.

## Security Architecture

### Keys & Credentials
- JWTs, stored SSH/BMC/MFA secrets, and archives use independent
  `JWT_SIGNING_KEY`, `CREDENTIAL_ENCRYPTION_KEYS`, and `ARCHIVE_ENCRYPTION_KEY` values.
  Startup rejects missing/public/reused secrets.
- `CREDENTIAL_ENCRYPTION_KEYS` is an ordered keyring. The first key encrypts; later keys only
  decrypt. `scripts/rotate_credentials.py` safely re-encrypts existing values under the primary key.
- **SSH/BMC/MFA secrets** are Fernet authenticated-encrypted. Use a dedicated `gpumon` account +
  ED25519 key with
  `authorized_keys` restrictions (`no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty`)
- Login passwords use bcrypt; new/changed passwords require at least 15 characters. There is no
  built-in administrator password.
- Metric archives are encrypted with an independent AES-256-GCM key and written as 0600 files.

### Authentication & Access
- Administrators must enroll and verify TOTP MFA before any privileged API can be used.
- Browser JWTs live only in Secure, HttpOnly, SameSite cookies; mutating requests require a
  double-submit CSRF token. JWTs are not stored in localStorage.
- JWTs bind an immutable account identity and persistent token version. Logout, password/role
  changes, disablement, or deletion invalidate old tokens even after a process restart.
- Rate limits use bounded per-IP/account and per-IP buckets without a remotely exploitable global
  username lock.
- API documentation endpoints are permanently disabled in the production service.
- **Security headers**: CSP / X-Frame-Options DENY / nosniff / Referrer-Policy / Permissions-Policy / HSTS
- **Webhook SSRF guard**: HTTPS-only public destinations, DNS-pinned TLS connection, original-host
  certificate verification, and no redirects.
- Containers run as UID 10001 with a read-only root filesystem, no Linux capabilities, and
  CPU/memory/PID/log limits.
- frontend auto-logout on 401
- **CORS disabled by default** (same-origin deployment, SPA served by the API);
  cross-origin deployments must configure an explicit `CORS_ORIGINS` whitelist;
  forwarded headers are accepted only from `TRUSTED_PROXY_CIDRS`.
- Viewers cannot read management addresses, full IPMI/inventory, login/process identities, or live
  full argv. Live processes require admin. Remote kill/renice is off by default and, when enabled,
  requires both an MFA-authenticated session and password re-authentication.

### Collection Security
- **Host key verification**: TOFU records first-use fingerprints atomically in 0600 files; failure
  to persist aborts the connection. Any change aborts and alerts. Root SSH is denied by default.
- **Command whitelist**: all collection commands are built-in fixed templates —
  the frontend/users **cannot** inject shell
- **Zero footprint on monitored servers**: scripts run via stdin (`bash -s`),
  nothing written to disk, no background processes
- **Output capping**: 2MB per collector, `LC_ALL=C` fixed locale
- **Least sudo**: all metrics work without root; only `nvme smart-log` / `ipmitool` /
  `journalctl` may need per-command sudoers whitelist entries

## Platform Features

- **Login / user management**: JWT, admin/viewer roles, password change, disable, audit log
- **Server management**: password or SSH private key (+passphrase) auth, connection test;
  GPU vs CPU server type — CPU servers skip all GPU panels and aggregations
- **Process operations (admin)**: live process table (15s refresh, sortable, filterable), kill/renice
- **Alerts**: user rules (9 metrics) + built-in detector event stream, recovery records,
  acknowledgement, webhook
- **Cockpit**: cluster health strip (click to drill down), GPU matrix heatmap
  (sortable by server / utilization / memory / temperature), cluster trends, live alert ticker
- **Server detail**: health model tree (connectivity/CPU/memory/filesystem/network/GPU/kernel events),
  btop-style core grid, GPU cards (ECC/PCIe/throttle/risk tags), kernel event stream,
  NVMe/RAID/NFS, services/MIG/IPMI, inventory/NUMA topology tabs
- **GPU analysis**: cluster-wide idle-held detection (zombie VRAM) and failure-risk ranking
- **Public status page** (Uptime-Kuma style, `/status` without login): overall health
  banner, per-server uptime bars (7-90 days) + SSH latency + **per-GPU ring utilization
  gauges**; admin-configurable publish toggle, title, server selection, window, theme
  (configure in Settings → Status page)
- **History**: retained forever by default (configurable via retention_days), trend charts 1/3/6/24h
- **Dark/light theme**: follow-system auto + manual three-state toggle
- **Online migrations**: idempotent MySQL/SQLite dual-dialect migrations (migrations/)

## Quick Start

Full instructions: **[Deployment Guide](DEPLOYMENT.en.md)** ([中文](DEPLOYMENT.md)).

```bash
cp .env.example .env
chmod 600 .env
# Run this three times and place independent values in .env
openssl rand -hex 32
# Configure the initial admin/database/archive, run the explicit migration, then:
export GPU_MONITOR_IMAGE="gpu-monitor:$(git rev-parse --short=12 HEAD)"
docker compose up -d --build
```

Compose listens only on `127.0.0.1:8300`; use the documented HTTPS reverse proxy. There is no
default administrator account or password. A first-time administrator must enroll TOTP MFA before
privileged operations are accepted.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| JWT_SIGNING_KEY | none | independent JWT key, at least 32 characters |
| CREDENTIAL_ENCRYPTION_KEYS | none | ordered keyring: `current_key,old_key` |
| ARCHIVE_ENCRYPTION_KEY | none | 64-hex-character AES-256-GCM archive key |
| INIT_ADMIN_USERNAME / PASSWORD | none | fresh database only; password 16–72 characters |
| DATABASE_URL / DATABASE_SSL_CA | SQLite / none | non-loopback MySQL requires a CA and least-privilege runtime account |
| REDIS_URL / REDIS_SSL_CA | none | optional cache; non-loopback Redis requires authenticated, certificate-verified `rediss://` |
| REQUIRE_ADMIN_MFA | yes | require TOTP for administrator privileges |
| REMOTE_PROCESS_CONTROL_ENABLED | no | opt in to process actions, still requiring re-authentication |
| POLL_INTERVAL_SECONDS | 60 | collection interval (changeable online on the settings page) |

The settings page also supports data retention days (0 = forever), a webhook URL, and a message
template. Webhook URLs are encrypted at rest and their full tokens are never returned by the API.

## Repository Layout

```
├── Dockerfile / Dockerfile.multistage / docker-compose.yml
├── backend/
│   ├── migrations/               # SQL migrations run explicitly with a short-lived DDL account
│   └── app/
│       ├── main.py               # FastAPI + SPA hosting + secure startup validation
│       ├── remote_scripts.py     # four remote script sets: fast/slow/inventory/kernel
│       ├── ssh_transport.py      # SSH transport: TOFU hostkey, fault classification, stdin exec
│       ├── ssh_collector.py      # fast-tier parsing
│       ├── collectors_extra.py   # slow/inventory/kernel parsing
│       ├── health.py             # 13 built-in detectors + GPU risk score + health tree
│       ├── scheduler.py          # tiered scheduling (fast each cycle / slow 5min / inventory 24h)
│       ├── notifier.py           # webhook notifications
│       ├── migrate.py            # migration runner (MySQL/SQLite dual dialect)
│       └── api/                  # auth/users/servers/metrics/alerts/cockpit/enterprise
└── frontend/src/views/           # Login/Dashboard/Servers/ServerDetail/Users/Alerts/Settings/Cockpit/GpuAnalysis
```
