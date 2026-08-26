"""SLOW / INVENTORY / KERNEL collectors.

SLOW (every ~5min):  NVMe SMART, mdraid, NFS, systemd failed, MIG, NVLink, IPMI/BMC
INVENTORY (every ~24h): machine-id, DMI, lscpu/NUMA, GPU topo, PCI NUMA, lsblk,
                         NIC list, InfiniBand, timedatectl
KERNEL (every poll):   incremental XID / OOM / MCE / EDAC / AER event parsing
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from .config import get_settings
from .remote_scripts import INVENTORY_SCRIPT, KERNEL_SCRIPT, SLOW_SCRIPT
from .ssh_collector import _first_line, _split_sections, _to_float
from .ssh_transport import classify_ssh_error, connect_host, decrypt_text, run_script

settings = get_settings()
logger = logging.getLogger("gpumon.collectors")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ================================================================ SLOW

@dataclass
class SlowResult:
    ok: bool
    error: str = ""
    error_code: str = "OK"
    duration: float = 0.0

    nvme_smart: list = field(default_factory=list)     # [{device, temperature, critical_warning, ...}]
    mdraid: dict = field(default_factory=dict)         # {personalities, arrays:[{name, level, state, ...}]}
    nfs_mounts: list = field(default_factory=list)     # [{server, mount, type, options}]
    systemd_failed: list = field(default_factory=list) # [{unit, load, active, sub, description}]
    services: dict = field(default_factory=dict)       # {sshd: "active", docker: "inactive", ...}
    mig: list = field(default_factory=list)            # [{gpu_index, mode, items:[...]}]
    nvlink: dict = field(default_factory=dict)         # {states: {gpu_idx: [link states]}, caps: str}
    ipmi: list = field(default_factory=list)           # [{name, value, unit, status}]


def _parse_nvme_smart(devs_text: str, smart_text: str) -> list[dict]:
    # smart lines prefixed with device path
    per_dev: dict[str, dict] = {}
    for line in smart_text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(/dev/\S+)\s+(.*)$", line)
        if not m:
            continue
        dev, rest = m.group(1), m.group(2)
        d = per_dev.setdefault(dev, {"device": dev})
        # nvme smart-log format: "key                  : value" or "key : value"
        km = re.match(r"^([A-Za-z0-9_\s%()-]+?)\s*:\s*(.+)$", rest)
        if not km:
            continue
        key = km.group(1).strip().lower().replace(" ", "_")
        val = km.group(2).strip()
        if key == "critical_warning":
            # value is hex (e.g. "0x01"); the old regex parsed it as 0,
            # silently discarding real hardware warnings
            try:
                d["critical_warning"] = int(val.split()[0], 0)
            except (ValueError, IndexError):
                num = re.match(r"^(\d+)", val)
                d["critical_warning"] = int(num.group(1)) if num else 0
        elif key == "temperature":
            v = re.match(r"^(\d+)", val)
            if v:
                d["temperature"] = int(v.group(1))
        elif key == "available_spare":
            v = re.match(r"^(\d+)", val)
            if v:
                d["available_spare"] = int(v.group(1))
        elif key == "available_spare_threshold":
            v = re.match(r"^(\d+)", val)
            if v:
                d["available_spare_threshold"] = int(v.group(1))
        elif key == "percentage_used":
            v = re.match(r"^(\d+)", val)
            if v:
                d["percentage_used"] = int(v.group(1))
        elif key == "data_units_read":
            v = re.match(r"^([\d,]+)", val)
            if v:
                d["data_units_read"] = int(v.group(1).replace(",", ""))
        elif key == "data_units_written":
            v = re.match(r"^([\d,]+)", val)
            if v:
                d["data_units_written"] = int(v.group(1).replace(",", ""))
        elif key == "power_cycles":
            v = re.match(r"^(\d+)", val)
            if v:
                d["power_cycles"] = int(v.group(1))
        elif key == "power_on_hours":
            v = re.match(r"^([\d,]+)", val)
            if v:
                d["power_on_hours"] = int(v.group(1).replace(",", ""))
        elif key == "unsafe_shutdowns":
            v = re.match(r"^(\d+)", val)
            if v:
                d["unsafe_shutdowns"] = int(v.group(1))
        elif key == "media_errors":
            v = re.match(r"^([\d,]+)", val)
            if v:
                d["media_errors"] = int(v.group(1).replace(",", ""))
        elif key == "num_err_log_entries":
            v = re.match(r"^([\d,]+)", val)
            if v:
                d["num_err_log_entries"] = int(v.group(1).replace(",", ""))
    return list(per_dev.values())


def _parse_mdstat(text: str) -> dict:
    out = {"personalities": [], "arrays": [], "raw": text[:2000]}
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^Personalities\s*:\s*\[(.*)\]", line)
        if m:
            out["personalities"] = re.findall(r"raid\d+|linear|multipath|faulty", m.group(1))
            continue
        m = re.match(r"^(md\d+)\s*:\s*(.*)$", line)
        if m:
            name, rest = m.group(1), m.group(2)
            arr = {"name": name}
            level = re.search(r"(raid\d+|linear|multipath|faulty)", rest)
            if level:
                arr["level"] = level.group(1)
            status = re.search(r"\[(\d+)/(\d+)\]\s+\[([U_]+)\]", rest)
            if status:
                arr["active_disks"] = int(status.group(1))
                arr["total_disks"] = int(status.group(2))
                arr["state"] = status.group(3)
                if "_" in arr["state"]:
                    arr["degraded"] = True
            rec = re.search(r"recovery\s*=\s*(\d+(?:\.\d+)?)%", rest)
            if rec:
                arr["recovery_percent"] = float(rec.group(1))
            out["arrays"].append(arr)
    return out


def _parse_nfs(text: str) -> list[dict]:
    mounts = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        fs, mount, fstype = parts[0], parts[1], parts[2]
        if not re.search(r"nfs|lustre|ceph|gluster|gpfs|beegfs", fstype):
            continue
        server = fs.split(":")[0] if ":" in fs else ""
        mounts.append({
            "server": server,
            "export": fs.split(":", 1)[1] if ":" in fs else fs,
            "mount": mount,
            "type": fstype,
        })
    return mounts[:20]


def _parse_systemd_failed(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[0].endswith(".service"):
            out.append({
                "unit": parts[0],
                "load": parts[1],
                "active": parts[2],
                "sub": parts[3],
                "description": parts[4].strip() if len(parts) > 4 else "",
            })
    return out[:20]


def _parse_services(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out[parts[0]] = parts[1]
    return out


def _parse_mig(items_text: str, mode_text: str) -> list[dict]:
    # mode: "0, Disabled" / "0, Enabled" / "0, [N/A]" (consumer cards)
    modes: dict[int, str] = {}
    for line in mode_text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0].isdigit():
            mode = parts[1]
            if mode in ("[N/A]", "N/A", "Not Supported", "[Not Supported]"):
                continue  # MIG not supported on this GPU: don't list it
            modes[int(parts[0])] = mode
    result = []
    for idx, mode in sorted(modes.items()):
        result.append({
            "gpu_index": idx,
            "mode": mode,
            "items": [],
        })
    return result


def _parse_nvlink(sc_text: str, st_text: str) -> dict:
    states: dict[int, list[str]] = {}
    for line in st_text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0].isdigit():
            states[int(parts[0])] = [p for p in parts[1:] if p]
    return {"states": states, "raw": sc_text[:1000]}


def _parse_ipmi(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        # "Sensor Name | Value | Unit | Status"
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2 and parts[0]:
            out.append({
                "name": parts[0],
                "value": parts[1],
                "unit": parts[2] if len(parts) > 2 else "",
                "status": parts[3] if len(parts) > 3 else "",
            })
    return out[:60]


def collect_slow(host, port, username, password_enc="", private_key_enc="", passphrase_enc="",
                 server_key: str = "") -> SlowResult:
    t0 = time.time()
    r = SlowResult(ok=False)
    client = None
    try:
        client = connect_host(
            host, port, username,
            decrypt_text(password_enc), decrypt_text(private_key_enc), decrypt_text(passphrase_enc),
            server_key=server_key or f"{host}_{port}",
        )
        code, out, err = run_script(client, SLOW_SCRIPT, timeout=90)
        if not out.strip():
            r.error_code, r.error = "COLLECT_FAILED", f"empty output (exit {code}): {err[:200]}"
            return r
        sec = _split_sections(out)
        r.nvme_smart = _parse_nvme_smart(sec.get("NVMEDEVS", ""), sec.get("NVMESMART", ""))
        r.mdraid = _parse_mdstat(sec.get("MDSTAT", ""))
        r.nfs_mounts = _parse_nfs(sec.get("MOUNTS", ""))
        r.systemd_failed = _parse_systemd_failed(sec.get("SDFAILED", ""))
        r.services = _parse_services(sec.get("SDSTATE", ""))
        r.mig = _parse_mig(sec.get("MIG", ""), sec.get("MIGMODE", ""))
        r.nvlink = _parse_nvlink(sec.get("NVLINK", ""), sec.get("NVLINKST", ""))
        r.ipmi = _parse_ipmi(sec.get("IPMI", ""))
        r.duration = round(time.time() - t0, 2)
        r.ok = True
        return r
    except Exception as e:
        r.error_code, r.error = classify_ssh_error(e, host)
        return r
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


# ================================================================ INVENTORY

@dataclass
class InventoryResult:
    ok: bool
    error: str = ""
    error_code: str = "OK"
    duration: float = 0.0

    machine_id: str = ""
    dmi: dict = field(default_factory=dict)
    lscpu: dict = field(default_factory=dict)
    numa: dict = field(default_factory=dict)      # {nodes: [{id, cpus, mem_gb}]}
    gpu_topology: str = ""                        # raw nvidia-smi topo -m
    pci_numa: list = field(default_factory=list)  # [{addr, class, numa_node, vendor, device}]
    disks: list = field(default_factory=list)     # [{name, size, rota, type, serial, model}]
    nics: list = field(default_factory=list)      # [{name, mac, state, speed}]
    ip_addrs: list = field(default_factory=list)
    ib: dict = field(default_factory=dict)        # {adapters: [...], raw}
    time_info: dict = field(default_factory=dict)


def _parse_lscpu(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip()
    keep = {
        "Model name": "model_name",
        "Socket(s)": "sockets",
        "Core(s) per socket": "cores_per_socket",
        "Thread(s) per core": "threads_per_core",
        "CPU(s)": "cpus",
        "NUMA node(s)": "numa_nodes",
        "Architecture": "arch",
        "L3 cache": "l3_cache",
    }
    return {v: out.get(k, "") for k, v in keep.items()}


def _parse_numa(node_cpu_text: str, mem_text: str) -> dict:
    nodes = []
    # mem lines: /sys/devices/system/node/node0/meminfo: Node 0 MemTotal:  16312340 kB
    for line in mem_text.splitlines():
        m = re.match(r".*node(\d+)/meminfo:\s+Node\s+\d+\s+MemTotal:\s+(\d+)\s+kB", line)
        if m:
            nodes.append({"id": int(m.group(1)), "mem_gb": round(int(m.group(2)) / 1024 / 1024, 1), "cpus": ""})
    # cpu lists: node0 0-11,24-35
    for line in node_cpu_text.splitlines():
        m = re.match(r"^(node\d+)\s+(.+)$", line)
        if m:
            nid = int(m.group(1).replace("node", ""))
            for n in nodes:
                if n["id"] == nid:
                    n["cpus"] = m.group(2).strip()
    return {"nodes": nodes}


def _parse_pci_numa(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5:
            out.append({
                "addr": parts[0], "class": parts[1],
                "numa_node": int(parts[2]) if parts[2].lstrip("-").isdigit() else -1,
                "vendor": parts[3], "device": parts[4],
            })
    return out


def _parse_lsblk(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        # lsblk -P output: NAME="sda" SIZE="1.8T" ROTA="1" TYPE="disk" SERIAL="" MODEL="..."
        kv = dict(re.findall(r'(\w+)="([^"]*)"', line))
        if not kv.get("NAME"):
            continue
        out.append({
            "name": kv.get("NAME", ""), "size": kv.get("SIZE", ""),
            "rota": kv.get("ROTA", ""), "type": kv.get("TYPE", ""),
            "serial": kv.get("SERIAL", ""), "model": kv.get("MODEL", ""),
        })
    return out


def _parse_nics(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            out.append({
                "name": parts[0], "mac": parts[1], "state": parts[2],
                "speed": parts[3] if len(parts) > 3 else "",
            })
    return out


def _parse_ib(text: str) -> dict:
    if not text.strip():
        return {"adapters": []}
    adapters = []
    current = {}
    for line in text.splitlines():
        m = re.match(r"^CA\s+'([^']+)'", line)
        if m:
            if current:
                adapters.append(current)
            current = {"name": m.group(1)}
            continue
        if ":" in line and current:
            key, _, val = line.partition(":")
            current[key.strip()] = val.strip()
    if current:
        adapters.append(current)
    return {"adapters": adapters[:10]}


def _parse_timedate(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip().lower().replace(" ", "_")] = val.strip()
    return out


def collect_inventory(host, port, username, password_enc="", private_key_enc="", passphrase_enc="",
                      server_key: str = "") -> InventoryResult:
    t0 = time.time()
    r = InventoryResult(ok=False)
    client = None
    try:
        client = connect_host(
            host, port, username,
            decrypt_text(password_enc), decrypt_text(private_key_enc), decrypt_text(passphrase_enc),
            server_key=server_key or f"{host}_{port}",
        )
        code, out, err = run_script(client, INVENTORY_SCRIPT, timeout=120)
        if not out.strip():
            r.error_code, r.error = "COLLECT_FAILED", f"empty output (exit {code}): {err[:200]}"
            return r
        sec = _split_sections(out)
        r.machine_id = _first_line(sec.get("MACHINEID", ""))
        dmi = {}
        for line in sec.get("DMI", "").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                dmi[k.strip()] = v.strip()
        r.dmi = dmi
        r.lscpu = _parse_lscpu(sec.get("LSCPU", ""))
        numa_text = sec.get("NUMA", "")
        # has_cpu line first, then per-node cpulist lines
        r.numa = _parse_numa(numa_text, sec.get("NUMAMEM", ""))
        r.gpu_topology = _strip_ansi(sec.get("GPUTOPO", ""))[:4000]
        r.pci_numa = _parse_pci_numa(sec.get("PCINUMA", ""))
        r.disks = _parse_lsblk(sec.get("LSBLK", ""))
        r.nics = _parse_nics(sec.get("NICLIST", ""))
        r.ip_addrs = [l.strip() for l in sec.get("IPADDR", "").splitlines() if l.strip()][:10]
        r.ib = _parse_ib(sec.get("IBSTAT", ""))
        r.time_info = _parse_timedate(sec.get("TIMEDATE", ""))
        r.duration = round(time.time() - t0, 2)
        r.ok = True
        return r
    except Exception as e:
        r.error_code, r.error = classify_ssh_error(e, host)
        return r
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


# ================================================================ KERNEL EVENTS

# event type -> (severity, pattern list)
_KERNEL_PATTERNS = [
    # (event_type, severity, regex)
    ("GPU_XID", "critical", re.compile(r"NVRM: Xid (\d+).*?(?:on (GPU [\d:a-f]+))?(?:UUID[: ]+(\S+))?", re.I)),
    ("GPU_FALLEN_OFF_BUS", "critical", re.compile(r"GPU has fallen off the bus", re.I)),
    ("OOM_KILL", "critical", re.compile(r"(Out of memory|Killed process|oom-kill|invoked oom-killer)", re.I)),
    ("MCE_HARDWARE_ERROR", "critical", re.compile(r"(Machine check|Hardware error|mce:)", re.I)),
    ("EDAC_MEMORY_ERROR", "warning", re.compile(r"EDAC.*error", re.I)),
    ("PCIE_AER", "warning", re.compile(r"(pcieport|AER).*?(corrected|uncorrected|fatal)?\s*error", re.I)),
    ("IO_ERROR", "warning", re.compile(r"(I/O error|blk_update_request|EXT4-fs error|XFS .* error)", re.I)),
    ("NVME_ERROR", "warning", re.compile(r"nvme\d+.*?(timeout|resetting|controller reset|I/O)", re.I)),
    ("NFS_ERROR", "warning", re.compile(r"nfs.*?(not responding|timed out|stale)", re.I)),
    ("NIC_RESET", "warning", re.compile(r"(igb|ixgbe|mlx|bnxt|e1000e)\b.*?(reset|link down|NIC Link is Down)", re.I)),
    ("TCP_REQUESTED", "info", re.compile(r"TCP: request_sock_TCP", re.I)),
]


@dataclass
class KernelEvent:
    event_type: str
    severity: str
    message: str
    raw_message: str = ""
    gpu_uuid: str = ""
    xid: int = 0
    ts: str = ""  # as reported by remote journal/dmesg


def parse_kernel_log(text: str, boot_id: str = "") -> list[KernelEvent]:
    events: list[KernelEvent] = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        for etype, sev, rx in _KERNEL_PATTERNS:
            if rx.search(line):
                ev = KernelEvent(
                    event_type=etype, severity=sev,
                    message=line[:200], raw_message=line[:2000], ts="",
                )
                if etype == "GPU_XID":
                    m = re.search(r"Xid (\d+)", line)
                    if m:
                        ev.xid = int(m.group(1))
                    mu = re.search(r"GPU[-\s]([0-9a-f-]{36})", line)
                    if mu:
                        ev.gpu_uuid = mu.group(1)
                events.append(ev)
                break
    # one OOM incident emits several kernel lines; keep a single event and
    # prefer the "Killed process" line (it names the victim pid)
    oom_idx = [i for i, e in enumerate(events) if e.event_type == "OOM_KILL"]
    if len(oom_idx) > 1:
        keep = next((i for i in oom_idx if "Killed process" in events[i].message), oom_idx[0])
        events = [e for i, e in enumerate(events) if e.event_type != "OOM_KILL" or i == keep]
    return events[:100]


def collect_kernel(host, port, username, password_enc="", private_key_enc="", passphrase_enc="",
                   server_key: str = "") -> tuple[str, list[KernelEvent], str, float]:
    """Returns (boot_id, events, error_code, duration)."""
    t0 = time.time()
    client = None
    try:
        client = connect_host(
            host, port, username,
            decrypt_text(password_enc), decrypt_text(private_key_enc), decrypt_text(passphrase_enc),
            server_key=server_key or f"{host}_{port}",
        )
        _, out, _ = run_script(client, KERNEL_SCRIPT, timeout=30)
        sec = _split_sections(out)
        boot_id = _first_line(sec.get("BOOTID", ""))
        klog = sec.get("KLOG", "")
        events = parse_kernel_log(klog, boot_id)
        return boot_id, events, "OK", round(time.time() - t0, 2)
    except Exception as e:
        code, msg = classify_ssh_error(e, host)
        return "", [], code, round(time.time() - t0, 2)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
