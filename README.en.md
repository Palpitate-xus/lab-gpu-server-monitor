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
| **fast** | every cycle (default 30-60s) | CPU (incl. iowait/per-core), memory (HugePages), disk space + inodes, per-device IO, NIC rates/errors/drops/link state, full GPU set (utilization / VRAM / temp / memory temp / power / clocks / pstate / **throttle reasons / ECC / PCIe link / retired pages** / compute processes), process table, logged-in users, TCP/fd |
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
- **SECRET_KEY lives only in `.env` (gitignored)**, injected by compose via `env_file`;
  **rotating the key renders stored SSH credentials undecryptable** (error code
  `CRED_DECRYPT_FAILED`) and they must be re-entered on the server management page —
  by design, so old ciphertext can never be decrypted with an old key
- **SSH credentials**: stored Fernet-encrypted (AES-128-CBC + HMAC, key derived from SECRET_KEY);
  recommended: a dedicated `monitor` user + ED25519 key with
  `authorized_keys` restrictions (`no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty`)
- **Login passwords**: bcrypt cost=12

### Authentication & Access
- **Login rate limiting**: 5 failures per IP / per username locks for 10 minutes
  (429 with remaining-time message); success resets counters; failures are audit-logged
- **JWT validity 2 hours**; frontend auto-logout on 401
- **CORS disabled by default** (same-origin deployment, SPA served by the API);
  cross-origin deployments must configure an explicit `CORS_ORIGINS` whitelist;
  behind a reverse proxy set `TRUST_PROXY=yes` to trust X-Forwarded-For
- Process kill/renice, server CRUD, user management, rules, settings all require admin;
  viewer is read-only; sensitive operations are fully audit-logged

### Collection Security
- **Host key verification**: TOFU (trust on first use), any change aborts the connection
  and raises an alert (anti-MITM); admins can reset after confirming a server reinstall
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
- **Cockpit**: cluster health strip (click to drill down), GPU matrix heatmap,
  cluster trends, live alert ticker
- **Server detail**: health model tree (connectivity/CPU/memory/filesystem/network/GPU/kernel events),
  btop-style core grid, GPU cards (ECC/PCIe/throttle/risk tags), kernel event stream,
  NVMe/RAID/NFS, services/MIG/IPMI, inventory/NUMA topology tabs
- **GPU analysis**: cluster-wide idle-held detection (zombie VRAM) and failure-risk ranking
- **History**: retained forever by default (configurable via retention_days), trend charts 1/3/6/24h
- **Dark/light theme**: follow-system auto + manual three-state toggle
- **Online migrations**: idempotent MySQL/SQLite dual-dialect migrations (migrations/)

## Quick Start

```bash
# Build the frontend first (use this flow when Docker Hub is unreachable;
# with network access you can use Dockerfile.multistage directly)
cd frontend && pnpm install && pnpm build && cd ..
docker compose up -d --build
```

Open `http://<host>:8300`, default `admin / admin123` (**change it immediately**).

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| SECRET_KEY | change-me | JWT signing + credential encryption (**must change**; changing it invalidates stored credentials) |
| INIT_ADMIN_USERNAME / PASSWORD | admin/admin123 | admin account created on first start |
| POLL_INTERVAL_SECONDS | 60 | collection interval (changeable online on the settings page) |

The settings page also supports: data retention days (0 = forever), webhook URL and message template.

## Repository Layout

```
├── Dockerfile / Dockerfile.multistage / docker-compose.yml
├── backend/
│   ├── migrations/               # SQL migrations (idempotent, auto-executed)
│   └── app/
│       ├── main.py               # FastAPI + SPA hosting + migrations
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
