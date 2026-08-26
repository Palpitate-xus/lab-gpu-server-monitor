"""FAST-tier collector: host + GPU metrics, one SSH round trip per poll.

Parses the ==SECTION== protocol emitted by FAST_SCRIPT in remote_scripts.py.
Keeps the legacy public API: collect() / test_connection() / live_processes()
/ remote_command(), now built on ssh_transport with fault classification.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import paramiko

from .config import get_settings
from .remote_scripts import FAST_SCRIPT
from .ssh_transport import (
    classify_ssh_error,
    connect_host,
    decrypt_text,
    run_remote,
    run_script,
)

settings = get_settings()


@dataclass
class MetricResult:
    ok: bool
    error: str = ""
    error_code: str = "OK"
    collected_at: float = 0.0
    duration: float = 0.0
    ssh_latency: float = 0.0

    hostname: str = ""
    os: str = ""
    kernel: str = ""
    uptime_seconds: int = 0
    boot_id: str = ""
    host_ts: int = 0
    cpu_model: str = ""
    cpu_count: int = 0
    cpu_percent: float = 0.0
    cpu_iowait: float = 0.0
    cpu_freq_avg: float = 0.0
    cpu_temp_package: float = 0.0
    cores: list = field(default_factory=list)
    load1: float = 0.0
    load5: float = 0.0
    load15: float = 0.0

    mem_total_mb: float = 0.0
    mem_used_mb: float = 0.0
    mem_available_mb: float = 0.0
    mem_cached_mb: float = 0.0
    swap_total_mb: float = 0.0
    swap_used_mb: float = 0.0
    hugepages_total: int = 0
    hugepages_free: int = 0

    disk_io: list = field(default_factory=list)
    net_ifaces: list = field(default_factory=list)
    disks: list = field(default_factory=list)
    inodes: list = field(default_factory=list)

    sock_estab: int = 0
    sock_timewait: int = 0
    sock_closewait: int = 0
    fd_allocated: int = 0
    fd_max: int = 0
    pid_max: int = 0

    gpu_driver: str = ""
    gpus: list = field(default_factory=list)
    processes: list = field(default_factory=list)
    users: list = field(default_factory=list)


# ================================================================ parsing

def _split_sections(out: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in out.splitlines():
        m = re.match(r"^==([A-Z0-9_]+)==$", line.strip())
        if m:
            current = m.group(1)
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


def _to_float(v, default: float = 0.0) -> float:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return default


def _first_line(s: str) -> str:
    return s.strip().splitlines()[0].strip() if s and s.strip() else ""


# ---------------------------------------------------------------- cpu

def _parse_cpu_lines(text: str) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts or not parts[0].startswith("cpu"):
            continue
        try:
            result[parts[0]] = [_to_float(x) for x in parts[1:]]
        except Exception:
            continue
    return result


def _core_util(f1: list[float], f2: list[float]) -> float:
    total = sum(f2) - sum(f1)
    if total <= 0:
        return 0.0
    idle = (f2[3] - f1[3]) + ((f2[4] - f1[4]) if len(f2) > 4 and len(f1) > 4 else 0)
    return round(min(100.0, max(0.0, (1 - idle / total) * 100)), 1)


def _cpu_iowait(f1: list[float], f2: list[float]) -> float:
    total = sum(f2) - sum(f1)
    if total <= 0 or len(f2) < 5 or len(f1) < 5:
        return 0.0
    return round(min(100.0, max(0.0, (f2[4] - f1[4]) / total * 100)), 1)


def _parse_cpu(s1, s2, freq_text, temp_text, count):
    c1, c2 = _parse_cpu_lines(s1), _parse_cpu_lines(s2)
    overall, iowait = 0.0, 0.0
    if "cpu" in c1 and "cpu" in c2:
        overall = _core_util(c1["cpu"], c2["cpu"])
        iowait = _cpu_iowait(c1["cpu"], c2["cpu"])

    freqs: list[float] = []
    for line in freq_text.splitlines():
        line = line.strip()
        if not line:
            continue
        v = _to_float(line.split()[-1], 0)
        if v > 0:
            freqs.append(v)
    freq_avg = round(sum(freqs) / len(freqs), 0) if freqs else 0.0

    core_temps: dict[int, float] = {}
    package_temp = 0.0
    for line in temp_text.splitlines():
        if "=" not in line:
            continue
        name, _, val = line.partition("=")
        name = name.strip()
        v = _to_float(val, 0) / 1000.0
        if v <= 0 or v > 150:
            continue
        m = re.match(r"^Core\s+(\d+)$", name, re.I)
        if m:
            core_temps[int(m.group(1))] = round(v, 1)
        elif re.match(r"^(Package id 0|Tctl|Tdie|CPU)$", name, re.I):
            package_temp = max(package_temp, round(v, 1))

    cores = []
    for i in range(count):
        key = f"cpu{i}"
        util = _core_util(c1.get(key, []), c2.get(key, [])) if key in c1 and key in c2 else 0.0
        cores.append({
            "id": i,
            "util": util,
            "freq_mhz": round(freqs[i]) if i < len(freqs) else 0,
            "temp": core_temps.get(i, 0.0),
        })
    return overall, iowait, cores, package_temp


# ---------------------------------------------------------------- memory

def _parse_meminfo(text: str) -> dict[str, float]:
    info: dict[str, float] = {}
    for line in text.splitlines():
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        key = parts[0].strip()
        val = parts[1].strip().split()[0] if parts[1].strip() else "0"
        info[key] = _to_float(val)
    return info


def _memory(info: dict[str, float]) -> dict[str, float]:
    total = info.get("MemTotal", 0.0)
    available = info.get("MemAvailable", None)
    if available is None:
        free = info.get("MemFree", 0.0)
        cached = info.get("Cached", 0.0) + info.get("SReclaimable", 0.0) - info.get("Shmem", 0.0)
        available = free + info.get("Buffers", 0.0) + max(0.0, cached)
    used = max(0.0, total - available)
    cached_mb = (info.get("Buffers", 0.0) + info.get("Cached", 0.0) + info.get("SReclaimable", 0.0)) / 1024
    swap_total, swap_free = info.get("SwapTotal", 0.0), info.get("SwapFree", 0.0)
    return {
        "total_mb": total / 1024,
        "used_mb": used / 1024,
        "available_mb": available / 1024,
        "cached_mb": cached_mb,
        "swap_total_mb": swap_total / 1024,
        "swap_used_mb": max(0.0, swap_total - swap_free) / 1024,
    }


# ---------------------------------------------------------------- disk / net

_SKIP_DISK = re.compile(r"^(loop|ram|sr|fd|zram|dm-\d+|md\d+)")


def _parse_diskstats(text: str) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 14:
            continue
        out[parts[2]] = [
            _to_float(parts[3]),   # reads completed
            _to_float(parts[5]),   # sectors read
            _to_float(parts[7]),   # writes completed
            _to_float(parts[9]),   # sectors written
            _to_float(parts[13]) if len(parts) > 13 else 0.0,  # ms doing io
        ]
    return out


def _disk_rates(d1, d2, window: float) -> list[dict]:
    devices = sorted([n for n in d2 if n in d1 and not _SKIP_DISK.match(n)])
    result = []
    for name in devices[:16]:
        a, b = d1[name], d2[name]
        read_bps = (b[1] - a[1]) * 512 / window
        write_bps = (b[3] - a[3]) * 512 / window
        r_iops = (b[0] - a[0]) / window
        w_iops = (b[2] - a[2]) / window
        busy_ms = b[4] - a[4]
        busy_pct = min(100.0, busy_ms / (window * 1000) * 100)
        if read_bps < 1 and write_bps < 1 and busy_pct < 0.5:
            continue
        result.append({
            "device": name,
            "read_bps": round(read_bps, 1),
            "write_bps": round(write_bps, 1),
            "read_iops": round(r_iops, 1),
            "write_iops": round(w_iops, 1),
            "busy_percent": round(busy_pct, 1),
        })
    return result


def _parse_netdev(text: str) -> dict[str, tuple]:
    out: dict[str, tuple] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        iface, rest = line.split(":", 1)
        iface = iface.strip()
        if iface == "lo":
            continue
        parts = rest.split()
        if len(parts) < 16:
            continue
        # rx: bytes packets errs drop | tx at offset 8: bytes packets errs drop
        out[iface] = (
            _to_float(parts[0]), _to_float(parts[2]), _to_float(parts[3]),
            _to_float(parts[8]), _to_float(parts[10]), _to_float(parts[11]),
        )
    return out


def _parse_netlink(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            out[parts[0]] = {
                "state": parts[1],
                "carrier": parts[2],
                "speed": int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0,
            }
    return out


def _net_rates(n1, n2, window: float, link: dict) -> list[dict]:
    result = []
    for iface in sorted(n2.keys()):
        if iface not in n1:
            continue
        a, b = n1[iface], n2[iface]
        rx = (b[0] - a[0]) / window
        tx = (b[3] - a[3]) / window
        rx_err, rx_drop = b[1] - a[1], b[2] - a[2]
        tx_err, tx_drop = b[4] - a[4], b[5] - a[5]
        state = link.get(iface, {}).get("state", "")
        speed = link.get(iface, {}).get("speed", 0)
        if rx < 1 and tx < 1 and not (rx_err or rx_drop or tx_err or tx_drop):
            if state != "up":
                continue  # idle and not up: skip
            # keep up-but-idle ifaces only if they have link info (rare) -> skip too
            continue
        result.append({
            "iface": iface,
            "rx_bps": round(rx, 1),
            "tx_bps": round(tx, 1),
            "rx_err_rate": round(rx_err, 3),
            "rx_drop_rate": round(rx_drop, 3),
            "tx_err_rate": round(tx_err, 3),
            "tx_drop_rate": round(tx_drop, 3),
            "operstate": state,
            "speed_mbps": speed,
        })
    return result


# ---------------------------------------------------------------- df / inodes

_PSEUDO_FS = re.compile(
    r"^(tmpfs|devtmpfs|overlay|squashfs|udev|none|shm|loop|nsfs|tracefs|debugfs|configfs|"
    r"fusectl|fuse\.|hugetlbfs|mqueue|pstore|securityfs|bpf|cgroup|autofs|efivarfs|binfmt_misc|rpc_.*)"
)


def _parse_df(text: str) -> list[dict]:
    disks, seen = [], set()
    lines = [l for l in text.splitlines() if l.strip()]
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        fs, total_kb, used_kb, mount = parts[0], parts[1], parts[2], parts[5]
        if _PSEUDO_FS.match(fs) or mount.startswith("/snap"):
            continue
        if mount in seen:
            continue
        seen.add(mount)
        total_gb = _to_float(total_kb) / 1024 / 1024
        used_gb = _to_float(used_kb) / 1024 / 1024
        if total_gb <= 0:
            continue
        disks.append({
            "mount": mount,
            "device": fs,
            "total_gb": round(total_gb, 1),
            "used_gb": round(used_gb, 1),
            "percent": round(used_gb / total_gb * 100, 1),
        })
    disks.sort(key=lambda d: d["mount"])
    return disks


def _parse_dfi(text: str) -> list[dict]:
    out, seen = [], set()
    lines = [l for l in text.splitlines() if l.strip()]
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        fs, itotal, iused, mount = parts[0], parts[1], parts[2], parts[5]
        if mount in seen or _PSEUDO_FS.match(fs):
            continue
        seen.add(mount)
        t = _to_float(itotal)
        if t <= 0:
            continue
        u = _to_float(iused)
        out.append({
            "mount": mount,
            "inodes_total": int(t),
            "inodes_used": int(u),
            "inodes_percent": round(u / t * 100, 1),
        })
    out.sort(key=lambda d: d["mount"])
    return out


# ---------------------------------------------------------------- gpu

_NA = ("[n/a]", "n/a", "not supported", "[not supported]", "na", "[n/a] ")


def _gval(v: str) -> float:
    if v.strip().lower() in _NA:
        return 0.0
    return _to_float(v, 0.0)


def _is_na(v: str) -> bool:
    return v.strip().lower() in _NA


# throttle bitmask -> human reasons (NVIDIA NVML clock throttle reasons)
_THROTTLE_BITS = {
    0x00000001: "GPU_IDLE",
    0x00000002: "APPLICATIONS_CLOCKS",
    0x00000004: "SW_POWER_CAP",
    0x00000008: "HW_SLOWDOWN",
    0x00000010: "SYNC_BOOST",
    0x00000020: "SW_THERMAL_SLOWDOWN",
    0x00000040: "HW_THERMAL_SLOWDOWN",
    0x00000080: "HW_POWER_BRAKE_SLOWDOWN",
}


def _throttle_reasons(bitmask_str: str) -> list[str]:
    try:
        mask = int(bitmask_str, 0)
    except (TypeError, ValueError):
        return []
    if mask == 0:
        return []
    return [name for bit, name in _THROTTLE_BITS.items() if mask & bit]


def _parse_gpus(text: str) -> tuple[list[dict], str]:
    """G1 columns: index,uuid,name,util.gpu,util.mem,mem.used,mem.total,temp,power,limit,fan,driver"""
    gpus: list[dict] = []
    driver = ""
    if not text.strip() or "__NO_NVIDIA__" in text:
        return gpus, driver
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 12:
            driver = parts[11]
            gpus.append({
                "index": int(_gval(parts[0])),
                "uuid": parts[1],
                "name": parts[2],
                "utilization": _gval(parts[3]),
                "util_memory": _gval(parts[4]),
                "mem_used_mb": _gval(parts[5]),
                "mem_total_mb": _gval(parts[6]),
                "temperature": _gval(parts[7]),
                "power_draw": _gval(parts[8]),
                "power_limit": _gval(parts[9]),
                "fan_speed": _gval(parts[10]),
                # filled by later merges
                "clock_graphics": 0, "clock_memory": 0,
                "clock_graphics_max": 0, "clock_memory_max": 0,
                "encoder_sessions": 0, "decoder_sessions": 0,
                "pstate": "", "compute_mode": "",
                "serial": "", "pci_bus_id": "", "mem_temperature": 0.0,
                "throttle_mask": "", "throttle_reasons": [],
                "ecc_mode": "", "ecc_supported": False,
                "ecc_corrected_volatile": 0, "ecc_uncorrected_volatile": 0,
                "ecc_corrected_total": 0, "ecc_uncorrected_total": 0,
                "remapped_pending": 0, "remapped_failure": 0,
                "retired_pending": 0,
                "pcie_gen_current": 0, "pcie_gen_max": 0,
                "pcie_width_current": 0, "pcie_width_max": 0,
                "processes": [],
            })
    return gpus, driver


def _merge_gpu_health(text: str, gpus: list[dict]) -> None:
    """G2: index,serial,pci_bus_id,mem_temp,throttle_active,ecc_mode,ecc_cv,ecc_uv,ecc_ct,ecc_ut,
    remapped_pending,remapped_failure,retired_pending,pstate,pcie_gen_cur,pcie_gen_max,
    pcie_w_cur,pcie_w_max"""
    if not text.strip():
        return
    by_index = {g["index"]: g for g in gpus}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 18:
            continue
        try:
            idx = int(_gval(parts[0]))
        except ValueError:
            continue
        g = by_index.get(idx)
        if g is None:
            continue
        g["serial"] = parts[1]
        g["pci_bus_id"] = parts[2]
        g["mem_temperature"] = _gval(parts[3])
        g["throttle_mask"] = parts[4]
        g["throttle_reasons"] = _throttle_reasons(parts[4])
        ecc_mode = parts[5]
        g["ecc_mode"] = "" if _is_na(ecc_mode) else ecc_mode
        g["ecc_supported"] = not _is_na(ecc_mode)
        g["ecc_corrected_volatile"] = int(_gval(parts[6]))
        g["ecc_uncorrected_volatile"] = int(_gval(parts[7]))
        g["ecc_corrected_total"] = int(_gval(parts[8]))
        g["ecc_uncorrected_total"] = int(_gval(parts[9]))
        g["remapped_pending"] = int(_gval(parts[10]))
        g["remapped_failure"] = int(_gval(parts[11]))
        g["retired_pending"] = int(_gval(parts[12]))
        g["pstate"] = parts[13]
        g["pcie_gen_current"] = int(_gval(parts[14]))
        g["pcie_gen_max"] = int(_gval(parts[15]))
        g["pcie_width_current"] = int(_gval(parts[16]))
        g["pcie_width_max"] = int(_gval(parts[17]))


def _merge_gpu_clocks(text: str, gpus: list[dict]) -> None:
    """G3: index,clocks.g,clocks.m,max.g,max.m,enc,dec,compute_mode"""
    if not text.strip():
        return
    by_index = {g["index"]: g for g in gpus}
    for line in text.splitlines():
        line = line.strip()
        if not line or "Field " in line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        try:
            idx = int(_gval(parts[0]))
        except ValueError:
            continue
        g = by_index.get(idx)
        if g is None:
            continue
        g["clock_graphics"] = _gval(parts[1])
        g["clock_memory"] = _gval(parts[2])
        g["clock_graphics_max"] = _gval(parts[3])
        g["clock_memory_max"] = _gval(parts[4])
        g["encoder_sessions"] = int(_gval(parts[5]))
        g["decoder_sessions"] = int(_gval(parts[6]))
        g["compute_mode"] = parts[7]


def _merge_gpu_apps(apps_text: str, names_text: str, gpus: list[dict], ps_index: dict) -> None:
    names: dict[int, str] = {}
    for line in names_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            try:
                names[int(_to_float(parts[0]))] = parts[1]
            except (TypeError, ValueError):
                pass
    uuid_index = {g["uuid"]: g for g in gpus}
    for line in apps_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        uuid, pid_s, mem = parts[0], parts[1], parts[-1]
        try:
            pid = int(_to_float(pid_s))
        except (TypeError, ValueError):
            continue
        ps_proc = ps_index.get(pid)
        name = names.get(pid) or (ps_proc["command"] if ps_proc else "")
        entry = {
            "pid": pid,
            "mem_mb": _gval(mem),
            "user": ps_proc["user"] if ps_proc else "",
            "command": name[:80],
        }
        target = uuid_index.get(uuid)
        if target:
            target["processes"].append(entry)
        elif gpus:
            gpus[0]["processes"].append(entry)


# ---------------------------------------------------------------- ps / who / misc

def _parse_ps(text: str, limit: int = 500) -> list[dict]:
    procs: list[dict] = []
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    for line in lines[1:]:
        parts = line.split(None, 9)
        if len(parts) < 10:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        procs.append({
            "pid": pid,
            "ppid": ppid,
            "user": parts[2],
            "cpu": _to_float(parts[3]),
            "mem": _to_float(parts[4]),
            "rss_mb": round(_to_float(parts[5]) / 1024, 1),
            "vsz_mb": round(_to_float(parts[6]) / 1024, 1),
            "stat": parts[7],
            "etimes": int(_to_float(parts[8])),
            "command": parts[9][:120].strip(),
        })
        if len(procs) >= limit:
            break
    return procs


def _parse_who(text: str) -> list[dict]:
    users = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        users.append({
            "user": parts[0],
            "tty": parts[1],
            "from": parts[4] if len(parts) > 4 and parts[2] == "(" else "",
            "login": " ".join(parts[2:4]).strip("()"),
        })
    return users[:10]


def _parse_sockstat(text: str) -> dict[str, int]:
    out = {"estab": 0, "timewait": 0, "closewait": 0}
    for line in text.splitlines():
        m = re.search(r"ESTAB\s+(\d+)", line)
        if m:
            out["estab"] = int(m.group(1))
        m = re.search(r"TIMEWAIT\s+(\d+)", line, re.I)
        if m:
            out["timewait"] = int(m.group(1))
        # closewait not in sockstat; left 0 (could parse ss -s later)
    return out


# ================================================================ collect

def collect(host, port, username, password_enc="", private_key_enc="", passphrase_enc="",
            server_key: str = "") -> MetricResult:
    t0 = time.time()
    result = MetricResult(ok=False, collected_at=t0)
    client = None
    try:
        t_conn = time.time()
        client = connect_host(
            host, port, username,
            decrypt_text(password_enc), decrypt_text(private_key_enc), decrypt_text(passphrase_enc),
            server_key=server_key or f"{host}_{port}",
        )
        result.ssh_latency = round(time.time() - t_conn, 3)

        code, out, err = run_script(client, FAST_SCRIPT, timeout=settings.SSH_COMMAND_TIMEOUT)
        if not out.strip():
            result.error_code = "COLLECT_FAILED"
            result.error = f"empty output (exit {code}): {err.strip()[:300]}"
            return result
        sec = _split_sections(out)

        result.hostname = _first_line(sec.get("HOSTNAME", "")) or host
        result.os = _first_line(sec.get("OS", ""))
        result.kernel = _first_line(sec.get("KERNEL", ""))
        result.boot_id = _first_line(sec.get("BOOTID", ""))
        result.host_ts = int(_to_float(_first_line(sec.get("DATETIME", "0"))))

        uptime = (sec.get("UPTIME", "") or "").split()
        result.uptime_seconds = int(_to_float(uptime[0])) if uptime else 0

        load = (sec.get("LOADAVG", "") or "").split()
        if len(load) >= 3:
            result.load1, result.load5, result.load15 = _to_float(load[0]), _to_float(load[1]), _to_float(load[2])

        result.cpu_model = _first_line(sec.get("CPUMODEL", ""))[:120]
        result.cpu_count = int(_to_float(_first_line(sec.get("CPUCOUNT", "0"))))

        result.cpu_percent, result.cpu_iowait, result.cores, result.cpu_temp_package = _parse_cpu(
            sec.get("CPUSTAT1", ""), sec.get("CPUSTAT2", ""),
            sec.get("CPUFREQ", ""), sec.get("CPUTEMP", ""), result.cpu_count,
        )
        freqs = [c["freq_mhz"] for c in result.cores if c["freq_mhz"] > 0]
        result.cpu_freq_avg = round(sum(freqs) / len(freqs)) if freqs else 0.0

        info = _parse_meminfo(sec.get("MEMINFO", ""))
        mem = _memory(info)
        result.mem_total_mb = round(mem["total_mb"], 1)
        result.mem_used_mb = round(mem["used_mb"], 1)
        result.mem_available_mb = round(mem["available_mb"], 1)
        result.mem_cached_mb = round(mem["cached_mb"], 1)
        result.swap_total_mb = round(mem["swap_total_mb"], 1)
        result.swap_used_mb = round(mem["swap_used_mb"], 1)
        result.hugepages_total = int(info.get("HugePages_Total", 0))
        result.hugepages_free = int(info.get("HugePages_Free", 0))

        window = 1.0
        result.disk_io = _disk_rates(
            _parse_diskstats(sec.get("DISKSTATS1", "")),
            _parse_diskstats(sec.get("DISKSTATS2", "")),
            window,
        )
        link2 = _parse_netlink(sec.get("NETLINK2", ""))
        result.net_ifaces = _net_rates(
            _parse_netdev(sec.get("NETDEV1", "")),
            _parse_netdev(sec.get("NETDEV2", "")),
            window, link2,
        )
        result.disks = _parse_df(sec.get("DF", ""))
        result.inodes = _parse_dfi(sec.get("DFI", ""))

        sock = _parse_sockstat(sec.get("SOCKETS", ""))
        result.sock_estab = sock["estab"]
        result.sock_timewait = sock["timewait"]
        fd = (sec.get("FDNR", "") or "").split()
        if len(fd) >= 3:
            result.fd_allocated = int(_to_float(fd[0]))
            result.fd_max = int(_to_float(fd[2]))
        result.pid_max = int(_to_float(_first_line(sec.get("PIDMAX", "0"))))

        result.processes = _parse_ps(sec.get("PS", ""))
        result.users = _parse_who(sec.get("WHO", ""))

        gpus, driver = _parse_gpus(sec.get("GPU", ""))
        ps_index = {p["pid"]: p for p in result.processes}
        _merge_gpu_health(sec.get("GPUHEALTH", ""), gpus)
        _merge_gpu_clocks(sec.get("GPUCLOCK", ""), gpus)
        _merge_gpu_apps(sec.get("GPUAPPS", ""), sec.get("GPUAPPNAME", ""), gpus, ps_index)
        result.gpus = gpus
        result.gpu_driver = driver

        result.duration = round(time.time() - t0, 2)
        result.ok = True
        return result
    except Exception as e:
        result.error_code, result.error = classify_ssh_error(e, host)
        return result
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


# ================================================================ legacy API

def test_connection(host, port, username, password="", private_key="", passphrase="") -> tuple[bool, str]:
    try:
        client = connect_host(host, port, username, password, private_key, passphrase,
                              server_key=f"test_{host}_{port}")
        try:
            code, out, _ = run_remote(client, "echo ok", timeout=10)
            if out.strip() == "ok":
                return True, "Connection successful"
            return False, f"Connected but command failed (exit {code})"
        finally:
            client.close()
    except Exception as e:
        code, msg = classify_ssh_error(e, host)
        return False, msg


def live_processes(host, port, username, password_enc="", private_key_enc="", passphrase_enc="",
                   sort: str = "cpu", limit: int = 0) -> tuple[bool, list | str]:
    sort_map = {"cpu": "-pcpu", "mem": "-rss", "pid": "pid", "time": "-etimes"}
    s = sort_map.get(sort, "-pcpu")
    cmd = f"ps -eo pid,ppid,user:24,pcpu,pmem,rss:16,vsz:16,stat,etimes,args:256 --sort={s} 2>/dev/null"
    try:
        client = connect_host(
            host, port, username,
            decrypt_text(password_enc), decrypt_text(private_key_enc), decrypt_text(passphrase_enc),
            server_key=f"live_{host}_{port}",
        )
        try:
            _, out, _ = run_remote(client, cmd, timeout=15)
            return True, _parse_ps(out, limit=limit or 100000)
        finally:
            client.close()
    except Exception as e:
        _, msg = classify_ssh_error(e, host)
        return False, msg


def remote_command(host, port, username, password_enc="", private_key_enc="", passphrase_enc="",
                   command: str = "") -> tuple[bool, str]:
    try:
        client = connect_host(
            host, port, username,
            decrypt_text(password_enc), decrypt_text(private_key_enc), decrypt_text(passphrase_enc),
            server_key=f"live_{host}_{port}",
        )
        try:
            code, out, err = run_remote(client, command, timeout=15)
            msg = (out.strip() or err.strip())[:500]
            return code == 0, msg or f"exit {code}"
        finally:
            client.close()
    except Exception as e:
        _, msg = classify_ssh_error(e, host)
        return False, msg
