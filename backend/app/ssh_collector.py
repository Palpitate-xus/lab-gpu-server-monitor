"""Collect host + GPU metrics from a remote server over SSH.

Strategy: run ONE combined POSIX shell script per collection (single round trip),
emit tagged sections, parse them locally. btop-grade coverage:
per-core CPU (util / freq / temp), detailed memory, disk IO rates per device,
network rates per iface, full process table, GPU clocks / codecs / pstate,
logged-in users. All rate sections are sampled over the same 1s window.
"""

from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import paramiko

from .config import get_settings
from .security import decrypt_text

settings = get_settings()

REMOTE_SCRIPT = r"""
DFOUT=$(timeout 5 df -kP -x tmpfs -x devtmpfs 2>/dev/null || timeout 5 df -kP -l 2>/dev/null || true)
GPU_BASIC=$(timeout 10 nvidia-smi --query-gpu=index,gpu_uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit,fan.speed,driver_version --format=csv,noheader,nounits 2>/dev/null || true)
# extended query (clocks/pstate/codecs) — only on drivers that support every field;
# nvidia-smi prints usage errors to stdout, so validate the output looks like data
GPUEXT=''
if [ -n "$GPU_BASIC" ]; then
  GPUEXT=$(timeout 10 nvidia-smi --query-gpu=index,gpu_uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit,fan.speed,driver_version,clocks.current.graphics,clocks.current.memory,clocks.max.graphics,clocks.max.memory,encoder.stats.sessionCount,decoder.stats.sessionCount,pstate,compute_mode --format=csv,noheader,nounits 2>/dev/null || true)
  case "$GPUEXT" in
    *"Field "*|*"Not Supported"*|*"Invalid"*|*"") GPUEXT="" ;;
  esac
fi
GPUAPPS=$(timeout 10 nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits 2>/dev/null || true)
GPUAPPNAME=$(timeout 10 nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader,nounits 2>/dev/null || true)

echo "==HOSTNAME=="; hostname 2>/dev/null || uname -n
echo "==OS=="; ( . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" ) || uname -s
echo "==KERNEL=="; uname -r
echo "==UPTIME=="; cat /proc/uptime 2>/dev/null
echo "==DATETIME=="; date +%s
echo "==LOADAVG=="; cat /proc/loadavg 2>/dev/null
echo "==CPUMODEL=="; grep -m1 -E '^(model name|Hardware)' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed 's/^ *//'
echo "==CPUCOUNT=="; ( nproc 2>/dev/null || grep -c '^processor' /proc/cpuinfo 2>/dev/null || echo 0 )
echo "==CPUFREQ=="; grep -E '^cpu MHz' /proc/cpuinfo 2>/dev/null | awk '{print $4}'
echo "==CPUTEMP=="; for f in /sys/class/hwmon/hwmon*/temp*_input; do [ -f "$f" ] || continue; lb="${f%_input}_label"; n=$(cat "$lb" 2>/dev/null); [ -n "$n" ] || n=$(basename "$f" _input); v=$(cat "$f" 2>/dev/null); [ -n "$v" ] && echo "$n=$v"; done
echo "==CPUSTAT1=="; grep '^cpu' /proc/stat 2>/dev/null
echo "==DISKSTATS1=="; cat /proc/diskstats 2>/dev/null
echo "==NETDEV1=="; cat /proc/net/dev 2>/dev/null
sleep 1
echo "==CPUSTAT2=="; grep '^cpu' /proc/stat 2>/dev/null
echo "==DISKSTATS2=="; cat /proc/diskstats 2>/dev/null
echo "==NETDEV2=="; cat /proc/net/dev 2>/dev/null
echo "==MEMINFO=="; cat /proc/meminfo 2>/dev/null
echo "==DF=="; echo "$DFOUT"
echo "==GPU=="; if [ -n "$GPUEXT" ]; then echo "$GPUEXT"; elif [ -n "$GPU_BASIC" ]; then echo "$GPU_BASIC"; else echo "__NO_NVIDIA__"; fi
echo "==GPUCLOCK=="; if [ -n "$GPU_BASIC" ] && [ -z "$GPUEXT" ]; then timeout 10 nvidia-smi --query-gpu=index,clocks.current.graphics,clocks.current.memory,clocks.max.graphics,clocks.max.memory,pstate,compute_mode --format=csv,noheader,nounits 2>/dev/null | grep -v 'Field ' || true; fi
echo "==GPUAPPS=="; echo "$GPUAPPS"
echo "==GPUAPPNAME=="; echo "$GPUAPPNAME"
echo "==PS=="; ps -eo pid,ppid,user:24,pcpu,pmem,rss:16,vsz:16,stat,etimes,args:256 --sort=-pcpu 2>/dev/null | head -n 501
echo "==WHO=="; who -u 2>/dev/null | head -n 12
true
"""


@dataclass
class MetricResult:
    ok: bool
    error: str = ""
    collected_at: float = 0.0
    duration: float = 0.0

    hostname: str = ""
    os: str = ""
    kernel: str = ""
    uptime_seconds: int = 0
    host_ts: int = 0
    cpu_model: str = ""
    cpu_count: int = 0
    cpu_percent: float = 0.0
    cpu_freq_avg: float = 0.0
    cpu_temp_package: float = 0.0
    cores: list = field(default_factory=list)  # [{id, util, freq_mhz, temp}]
    load1: float = 0.0
    load5: float = 0.0
    load15: float = 0.0

    mem_total_mb: float = 0.0
    mem_used_mb: float = 0.0
    mem_available_mb: float = 0.0
    mem_cached_mb: float = 0.0
    swap_total_mb: float = 0.0
    swap_used_mb: float = 0.0

    disk_io: list = field(default_factory=list)  # [{device, read_bps, write_bps, read_iops, write_iops, busy_percent}]
    net_ifaces: list = field(default_factory=list)  # [{iface, rx_bps, tx_bps}]
    disks: list = field(default_factory=list)  # [{mount, device, total_gb, used_gb, percent}]

    gpu_driver: str = ""
    gpus: list = field(default_factory=list)
    processes: list = field(default_factory=list)
    users: list = field(default_factory=list)


# ------------------------------------------------------------------ helpers

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


# ------------------------------------------------------------------ cpu

def _parse_cpu_lines(text: str) -> dict[str, list[float]]:
    """Return {'cpu': [...], 'cpu0': [...], ...} from /proc/stat grep '^cpu'."""
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


def _parse_cpu(s1: str, s2: str, freq_text: str, temp_text: str, count: int) -> tuple[float, list, float]:
    c1 = _parse_cpu_lines(s1)
    c2 = _parse_cpu_lines(s2)

    overall = 0.0
    if "cpu" in c1 and "cpu" in c2:
        overall = _core_util(c1["cpu"], c2["cpu"])

    freqs: list[float] = []
    for line in freq_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # tolerate both "2500.000" (awk-extracted) and "cpu MHz : 2500.000"
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
        cores.append(
            {
                "id": i,
                "util": util,
                "freq_mhz": round(freqs[i]) if i < len(freqs) else 0,
                "temp": core_temps.get(i, 0.0),
            }
        )
    return overall, cores, package_temp


# ------------------------------------------------------------------ memory

def _parse_meminfo(text: str) -> dict[str, float]:
    info: dict[str, float] = {}
    for line in text.splitlines():
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        key = parts[0].strip()
        val = parts[1].strip().split()[0] if parts[1].strip() else "0"
        info[key] = _to_float(val)  # kB
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
    swap_total = info.get("SwapTotal", 0.0)
    swap_free = info.get("SwapFree", 0.0)
    return {
        "total_mb": total / 1024,
        "used_mb": used / 1024,
        "available_mb": available / 1024,
        "cached_mb": cached_mb,
        "swap_total_mb": swap_total / 1024,
        "swap_used_mb": max(0.0, swap_total - swap_free) / 1024,
    }


# ------------------------------------------------------------------ disk / net rates

_SKIP_DISK = re.compile(r"^(loop|ram|sr|fd|zram|dm-\d+|md\d+)")


def _parse_diskstats(text: str) -> dict[str, list[float]]:
    """name -> [reads, sectors_read, writes, sectors_written, ms_doing_io]"""
    out: dict[str, list[float]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 14:
            continue
        name = parts[2]
        # field indexes (0=major 1=minor 2=name): 3=reads_completed 5=sectors_read
        #   7=writes_completed 9=sectors_written 12=ios_in_progress 13=ms_doing_io
        out[name] = [
            _to_float(parts[3]),    # reads completed
            _to_float(parts[5]),    # sectors read
            _to_float(parts[7]),    # writes completed
            _to_float(parts[9]),    # sectors written
            _to_float(parts[13]) if len(parts) > 13 else 0.0,  # ms doing io
        ]
    return out


def _disk_rates(d1: dict[str, list[float]], d2: dict[str, list[float]], window: float) -> list[dict]:
    devices = []
    for name, a in d2.items():
        if name in d1 and not _SKIP_DISK.match(name):
            devices.append(name)
    devices.sort()
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
            continue  # skip fully idle devices to keep payload small
        result.append(
            {
                "device": name,
                "read_bps": round(read_bps, 1),
                "write_bps": round(write_bps, 1),
                "read_iops": round(r_iops, 1),
                "write_iops": round(w_iops, 1),
                "busy_percent": round(busy_pct, 1),
            }
        )
    return result


def _parse_netdev(text: str) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        iface, rest = line.split(":", 1)
        iface = iface.strip()
        if iface == "lo":
            continue
        parts = rest.split()
        if len(parts) < 9:
            continue
        out[iface] = (_to_float(parts[0]), _to_float(parts[8]))  # rx bytes, tx bytes
    return out


def _net_rates(n1: dict[str, tuple[float, float]], n2: dict[str, tuple[float, float]], window: float) -> list[dict]:
    result = []
    for iface in sorted(n2.keys()):
        if iface not in n1:
            continue
        rx = (n2[iface][0] - n1[iface][0]) / window
        tx = (n2[iface][1] - n1[iface][1]) / window
        if rx < 1 and tx < 1:
            continue  # skip idle ifaces
        result.append({"iface": iface, "rx_bps": round(rx, 1), "tx_bps": round(tx, 1)})
    return result


# ------------------------------------------------------------------ df

_PSEUDO_FS = re.compile(
    r"^(tmpfs|devtmpfs|overlay|squashfs|udev|none|shm|loop|nsfs|tracefs|debugfs|configfs|"
    r"fusectl|fuse\.|hugetlbfs|mqueue|pstore|securityfs|bpf|cgroup|autofs|efivarfs|binfmt_misc|rpc_.*)"
)


def _parse_df(text: str) -> list[dict]:
    disks: list[dict] = []
    seen = set()
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
        disks.append(
            {
                "mount": mount,
                "device": fs,
                "total_gb": round(total_gb, 1),
                "used_gb": round(used_gb, 1),
                "percent": round(used_gb / total_gb * 100, 1),
            }
        )
    disks.sort(key=lambda d: d["mount"])
    return disks


# ------------------------------------------------------------------ gpu

_NA = ("[n/a]", "n/a", "not supported", "[not supported]", "na")


def _gval(v: str) -> float:
    if v.strip().lower() in _NA:
        return 0.0
    return _to_float(v, 0.0)


def _parse_gpus(text: str) -> tuple[list[dict], str]:
    gpus: list[dict] = []
    driver = ""
    if not text.strip() or "__NO_NVIDIA__" in text:
        return gpus, driver
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 19:
            driver = parts[10]
            gpus.append(
                {
                    "index": int(_gval(parts[0])),
                    "uuid": parts[1],
                    "name": parts[2],
                    "utilization": _gval(parts[3]),
                    "mem_used_mb": _gval(parts[4]),
                    "mem_total_mb": _gval(parts[5]),
                    "temperature": _gval(parts[6]),
                    "power_draw": _gval(parts[7]),
                    "power_limit": _gval(parts[8]),
                    "fan_speed": _gval(parts[9]),
                    "clock_graphics": _gval(parts[11]),
                    "clock_memory": _gval(parts[12]),
                    "clock_graphics_max": _gval(parts[13]),
                    "clock_memory_max": _gval(parts[14]),
                    "encoder_sessions": int(_gval(parts[15])),
                    "decoder_sessions": int(_gval(parts[16])),
                    "pstate": parts[17],
                    "compute_mode": parts[18],
                    "processes": [],
                }
            )
        elif len(parts) >= 11:
            driver = parts[10]
            gpus.append(
                {
                    "index": int(_gval(parts[0])),
                    "uuid": parts[1],
                    "name": parts[2],
                    "utilization": _gval(parts[3]),
                    "mem_used_mb": _gval(parts[4]),
                    "mem_total_mb": _gval(parts[5]),
                    "temperature": _gval(parts[6]),
                    "power_draw": _gval(parts[7]),
                    "power_limit": _gval(parts[8]),
                    "fan_speed": _gval(parts[9]),
                    "clock_graphics": 0,
                    "clock_memory": 0,
                    "clock_graphics_max": 0,
                    "clock_memory_max": 0,
                    "encoder_sessions": 0,
                    "decoder_sessions": 0,
                    "pstate": "",
                    "compute_mode": "",
                    "processes": [],
                }
            )
    return gpus, driver


def _merge_gpu_apps(
    apps_text: str, names_text: str, gpus: list[dict], ps_index: dict[int, dict]
) -> None:
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
                continue
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


# ------------------------------------------------------------------ processes / who

def _merge_gpu_clocks(text: str, gpus: list[dict]) -> None:
    """Merge the standalone clocks/pstate query (index,cur_g,cur_m,max_g,max_m,pstate,mode)."""
    if not text.strip():
        return
    by_index = {g["index"]: g for g in gpus}
    for line in text.splitlines():
        line = line.strip()
        if not line or "Field " in line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            idx = int(_to_float(parts[0]))
        except (TypeError, ValueError):
            continue
        g = by_index.get(idx)
        if g is None:
            continue
        if not g.get("clock_graphics"):
            g["clock_graphics"] = _gval(parts[1])
            g["clock_memory"] = _gval(parts[2])
            g["clock_graphics_max"] = _gval(parts[3])
            g["clock_memory_max"] = _gval(parts[4])
        if not g.get("pstate"):
            g["pstate"] = parts[5]
        if len(parts) > 6 and not g.get("compute_mode"):
            g["compute_mode"] = parts[6]


def _parse_ps(text: str, limit: int = 500) -> list[dict]:
    procs: list[dict] = []
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    for line in lines[1:]:  # skip header
        parts = line.split(None, 9)
        if len(parts) < 10:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        procs.append(
            {
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
            }
        )
        if len(procs) >= limit:
            break
    return procs


def _parse_who(text: str) -> list[dict]:
    users = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            users.append(
                {
                    "user": parts[0],
                    "tty": parts[1],
                    "from": parts[4] if len(parts) > 4 and parts[2] == "(" else "",
                    "login": " ".join(parts[2:4]).strip("()"),
                }
            )
        except Exception:
            continue
    return users[:10]


# ------------------------------------------------------------------ ssh plumbing

def _load_pkey(private_key: str, passphrase: str) -> paramiko.PKey:
    password = passphrase or None
    last_err: Optional[Exception] = None
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        buf = io.StringIO(private_key)
        try:
            return cls.from_private_key(buf, password=password)
        except Exception as e:
            last_err = e
    raise ValueError(f"Cannot load private key: {last_err}")


def _connect(host, port, username, password, private_key, passphrase) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": settings.SSH_CONNECT_TIMEOUT,
        "banner_timeout": settings.SSH_CONNECT_TIMEOUT,
        "auth_timeout": settings.SSH_CONNECT_TIMEOUT,
        "allow_agent": False,
        "look_for_keys": False,
    }
    if private_key:
        kwargs["pkey"] = _load_pkey(private_key, passphrase)
    else:
        kwargs["password"] = password
    client.connect(**kwargs)
    return client


def run_remote(client: paramiko.SSHClient, command: str, timeout: int = 15) -> tuple[int, str, str]:
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def collect(
    host: str,
    port: int,
    username: str,
    password_enc: str = "",
    private_key_enc: str = "",
    passphrase_enc: str = "",
) -> MetricResult:
    """Connect over SSH, run the collection script, parse and return metrics."""
    t0 = time.time()
    result = MetricResult(ok=False, collected_at=t0)
    client: Optional[paramiko.SSHClient] = None
    try:
        client = _connect(
            host, port, username,
            decrypt_text(password_enc),
            decrypt_text(private_key_enc),
            decrypt_text(passphrase_enc),
        )
        _, out, err = run_remote(client, REMOTE_SCRIPT, timeout=settings.SSH_COMMAND_TIMEOUT)
        if not out.strip():
            result.error = f"empty output: {err.strip()[:300]}"
            return result

        sec = _split_sections(out)

        result.hostname = _first_line(sec.get("HOSTNAME", "")) or host
        result.os = _first_line(sec.get("OS", ""))
        result.kernel = _first_line(sec.get("KERNEL", ""))
        result.host_ts = int(_to_float(_first_line(sec.get("DATETIME", "0"))))

        uptime = (sec.get("UPTIME", "") or "").split()
        result.uptime_seconds = int(_to_float(uptime[0])) if uptime else 0

        load = (sec.get("LOADAVG", "") or "").split()
        if len(load) >= 3:
            result.load1, result.load5, result.load15 = (
                _to_float(load[0]), _to_float(load[1]), _to_float(load[2]))

        result.cpu_model = _first_line(sec.get("CPUMODEL", ""))[:120]
        result.cpu_count = int(_to_float(_first_line(sec.get("CPUCOUNT", "0"))))

        result.cpu_percent, result.cores, result.cpu_temp_package = _parse_cpu(
            sec.get("CPUSTAT1", ""), sec.get("CPUSTAT2", ""),
            sec.get("CPUFREQ", ""), sec.get("CPUTEMP", ""), result.cpu_count,
        )
        freqs = [c["freq_mhz"] for c in result.cores if c["freq_mhz"] > 0]
        result.cpu_freq_avg = round(sum(freqs) / len(freqs)) if freqs else 0.0

        mem = _memory(_parse_meminfo(sec.get("MEMINFO", "")))
        result.mem_total_mb = round(mem["total_mb"], 1)
        result.mem_used_mb = round(mem["used_mb"], 1)
        result.mem_available_mb = round(mem["available_mb"], 1)
        result.mem_cached_mb = round(mem["cached_mb"], 1)
        result.swap_total_mb = round(mem["swap_total_mb"], 1)
        result.swap_used_mb = round(mem["swap_used_mb"], 1)

        window = 1.0
        result.disk_io = _disk_rates(
            _parse_diskstats(sec.get("DISKSTATS1", "")),
            _parse_diskstats(sec.get("DISKSTATS2", "")),
            window,
        )
        result.net_ifaces = _net_rates(
            _parse_netdev(sec.get("NETDEV1", "")),
            _parse_netdev(sec.get("NETDEV2", "")),
            window,
        )
        result.disks = _parse_df(sec.get("DF", ""))

        result.processes = _parse_ps(sec.get("PS", ""))
        result.users = _parse_who(sec.get("WHO", ""))

        gpus, driver = _parse_gpus(sec.get("GPU", ""))
        ps_index = {p["pid"]: p for p in result.processes}
        _merge_gpu_apps(sec.get("GPUAPPS", ""), sec.get("GPUAPPNAME", ""), gpus, ps_index)
        _merge_gpu_clocks(sec.get("GPUCLOCK", ""), gpus)
        result.gpus = gpus
        result.gpu_driver = driver

        result.duration = round(time.time() - t0, 2)
        result.ok = True
        return result
    except paramiko.AuthenticationException:
        result.error = "SSH authentication failed"
        return result
    except paramiko.SSHException as e:
        result.error = f"SSH error: {e}"
        return result
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
        return result
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


def test_connection(host, port, username, password="", private_key="", passphrase="") -> tuple[bool, str]:
    """Plain-text credential connectivity test. Returns (ok, message)."""
    try:
        client = _connect(host, port, username, password, private_key, passphrase)
        try:
            code, out, _ = run_remote(client, "echo ok", timeout=10)
            if out.strip() == "ok":
                return True, "Connection successful"
            return False, f"Connected but command failed (exit {code})"
        finally:
            client.close()
    except paramiko.AuthenticationException:
        return False, "Authentication failed (check username/password/key)"
    except paramiko.SSHException as e:
        return False, f"SSH error: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def live_processes(
    host, port, username, password_enc="", private_key_enc="", passphrase_enc="",
    sort: str = "cpu", limit: int = 0,
) -> tuple[bool, list | str]:
    """Fetch a fresh full process table on demand (btop-style live view)."""
    sort_map = {"cpu": "-pcpu", "mem": "-rss", "pid": "pid", "time": "-etimes"}
    s = sort_map.get(sort, "-pcpu")
    cmd = f"ps -eo pid,ppid,user:24,pcpu,pmem,rss:16,vsz:16,stat,etimes,args:256 --sort={s} 2>/dev/null"
    try:
        client = _connect(
            host, port, username,
            decrypt_text(password_enc),
            decrypt_text(private_key_enc),
            decrypt_text(passphrase_enc),
        )
        try:
            _, out, _ = run_remote(client, cmd, timeout=15)
            procs = _parse_ps(out, limit=limit or 100000)
            return True, procs
        finally:
            client.close()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def remote_command(
    host, port, username, password_enc="", private_key_enc="", passphrase_enc="", command: str = "",
) -> tuple[bool, str]:
    """Execute a single admin command (kill / renice) over SSH."""
    try:
        client = _connect(
            host, port, username,
            decrypt_text(password_enc),
            decrypt_text(private_key_enc),
            decrypt_text(passphrase_enc),
        )
        try:
            code, out, err = run_remote(client, command, timeout=15)
            msg = (out.strip() or err.strip())[:500]
            return code == 0, msg or f"exit {code}"
        finally:
            client.close()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
