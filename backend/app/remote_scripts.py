"""Agentless GPU server monitoring — remote collection scripts.

Three tiered collectors, each ONE POSIX shell script over ONE SSH round trip
(run via stdin, LC_ALL=C, no files written, no agent left behind):

  FAST       every poll (~30-60s): cpu/mem/disk/net/gpu/processes/who
  SLOW       every ~5 min:         nvme smart / raid / nfs / systemd / mig / nvlink / services
  INVENTORY  every ~24h:           machine-id / dmi / lscpu / numa / gpu topo / ib / bmc / lsblk

Output uses a simple ==SECTION== delimiter protocol parsed centrally.
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

MAX_OUTPUT_BYTES = 2 * 1024 * 1024  # hard cap per collector

# ====================================================================== scripts
# NOTE: keep everything POSIX sh; no bashisms outside `bash -s` which we DO use
# (linux servers universally have bash; fall back to sh if missing is NOT
# attempted because parsing relies on $(...) which POSIX sh also has).

FAST_SCRIPT = r"""
export LC_ALL=C LANG=C
# ---------- gpu queries (validate incrementally; old drivers reject fields) ---
G1=$(timeout 10 nvidia-smi --query-gpu=index,gpu_uuid,name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw,power.limit,fan.speed,driver_version --format=csv,noheader,nounits 2>/dev/null || true)
G2=''
if [ -n "$G1" ]; then
  G2=$(timeout 10 nvidia-smi --query-gpu=index,serial,pci.bus_id,temperature.memory,clocks_throttle_reasons.active,ecc.mode.current,ecc.errors.corrected.volatile.total,ecc.errors.uncorrected.volatile.total,ecc.errors.corrected.aggregate.total,ecc.errors.uncorrected.aggregate.total,remapped_rows.pending,remapped_rows.failure,retired_pages.pending,pstate,pcie.link.gen.current,pcie.link.gen.max,pcie.link.width.current,pcie.link.width.max --format=csv,noheader,nounits 2>/dev/null || true)
  case "$G2" in
    *"Field "*|*"Not Supported"*|*"Invalid"*|*"No devices"*) G2='' ;;
  esac
fi
G3=''
if [ -n "$G1" ]; then
  G3=$(timeout 10 nvidia-smi --query-gpu=index,clocks.current.graphics,clocks.current.memory,clocks.max.graphics,clocks.max.memory,encoder.stats.sessionCount,compute_mode --format=csv,noheader,nounits 2>/dev/null || true)
  case "$G3" in
    *"Field "*|*"Not Supported"*|*"Invalid"*|*"No devices"*) G3='' ;;
  esac
fi
if [ -n "$G1" ] && [ -z "$G3" ]; then
  G3=$(timeout 10 nvidia-smi --query-gpu=index,clocks.current.graphics,clocks.current.memory,clocks.max.graphics,clocks.max.memory --format=csv,noheader,nounits 2>/dev/null || true)
  case "$G3" in
    *"Field "*|*"Not Supported"*|*"Invalid"*|*"No devices"*) G3='' ;;
  esac
fi
GPUAPPS=$(timeout 10 nvidia-smi --query-compute-apps=gpu_uuid,pid,used_memory --format=csv,noheader,nounits 2>/dev/null || true)
GPUAPPNAME=$(timeout 10 nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader,nounits 2>/dev/null || true)
DFOUT=$(timeout 5 df -kP -x tmpfs -x devtmpfs 2>/dev/null || timeout 5 df -kP -l 2>/dev/null || true)
DFIOUT=$(timeout 5 df -iP -x tmpfs -x devtmpfs 2>/dev/null || true)

echo "==HOSTNAME=="; hostname 2>/dev/null || uname -n
echo "==OS=="; ( . /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" ) || uname -s
echo "==KERNEL=="; uname -r
echo "==UPTIME=="; cat /proc/uptime 2>/dev/null
echo "==BOOTID=="; cat /proc/sys/kernel/random/boot_id 2>/dev/null
echo "==DATETIME=="; date +%s
echo "==LOADAVG=="; cat /proc/loadavg 2>/dev/null
echo "==CPUMODEL=="; grep -m1 -E '^(model name|Hardware)' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed 's/^ *//'
echo "==CPUCOUNT=="; ( nproc 2>/dev/null || grep -c '^processor' /proc/cpuinfo 2>/dev/null || echo 0 )
echo "==CPUFREQ=="; grep -E '^cpu MHz' /proc/cpuinfo 2>/dev/null | awk '{print $4}'
echo "==CPUTEMP=="; for f in /sys/class/hwmon/hwmon*/temp*_input; do [ -f "$f" ] || continue; lb="${f%_input}_label"; n=$(cat "$lb" 2>/dev/null); [ -n "$n" ] || n=$(basename "$f" _input); v=$(cat "$f" 2>/dev/null); [ -n "$v" ] && echo "$n=$v"; done
echo "==CPUSTAT1=="; grep '^cpu' /proc/stat 2>/dev/null
echo "==DISKSTATS1=="; cat /proc/diskstats 2>/dev/null
echo "==NETDEV1=="; cat /proc/net/dev 2>/dev/null
echo "==NETLINK1=="; for n in /sys/class/net/*; do [ -d "$n" ] || continue; i=$(basename "$n"); [ "$i" = lo ] && continue; echo "$i $(cat $n/operstate 2>/dev/null) $(cat $n/carrier 2>/dev/null) $(cat $n/speed 2>/dev/null)"; done
sleep 1
echo "==CPUSTAT2=="; grep '^cpu' /proc/stat 2>/dev/null
echo "==DISKSTATS2=="; cat /proc/diskstats 2>/dev/null
echo "==NETDEV2=="; cat /proc/net/dev 2>/dev/null
echo "==NETLINK2=="; for n in /sys/class/net/*; do [ -d "$n" ] || continue; i=$(basename "$n"); [ "$i" = lo ] && continue; echo "$i $(cat $n/operstate 2>/dev/null) $(cat $n/carrier 2>/dev/null) $(cat $n/speed 2>/dev/null)"; done
echo "==MEMINFO=="; cat /proc/meminfo 2>/dev/null
echo "==DF=="; echo "$DFOUT"
echo "==DFI=="; echo "$DFIOUT"
echo "==GPU=="; if [ -n "$G1" ]; then echo "$G1"; else echo "__NO_NVIDIA__"; fi
echo "==GPUHEALTH=="; echo "$G2"
echo "==GPUCLOCK=="; echo "$G3"
echo "==GPUAPPS=="; echo "$GPUAPPS"
echo "==GPUAPPNAME=="; echo "$GPUAPPNAME"
echo "==PS=="; ps -eo pid,ppid,user:24,pcpu,pmem,rss:16,vsz:16,stat,etimes,args:256 --sort=-pcpu 2>/dev/null | head -n 501
echo "==WHO=="; who -u 2>/dev/null | head -n 12
echo "==SOCKETS=="; cat /proc/net/sockstat 2>/dev/null
echo "==FDNR=="; cat /proc/sys/fs/file-nr 2>/dev/null
echo "==PIDMAX=="; cat /proc/sys/kernel/pid_max 2>/dev/null
true
"""

SLOW_SCRIPT = r"""
export LC_ALL=C LANG=C
# ---------- nvme smart ----------
echo "==NVMEDEVS=="; ls /dev/nvme[0-9]* 2>/dev/null | grep -v 'p[0-9]' || true
echo "==NVMESMART=="
for d in /dev/nvme[0-9]*; do
  case "$d" in *p[0-9]*) continue;; esac
  [ -b "$d" ] || continue
  if command -v nvme >/dev/null 2>&1; then
    timeout 10 nvme smart-log "$d" 2>/dev/null | head -n 40 | sed "s|^|$d |"
  elif command -v smartctl >/dev/null 2>&1; then
    timeout 10 smartctl -A "$d" 2>/dev/null | sed "s|^|$d |"
  fi
done
echo "==NVMETEMP=="; for f in /sys/class/nvme/nvme*/hwmon*/temp*_input /sys/class/nvme/nvme*/temp; do [ -f "$f" ] && echo "$f $(cat $f 2>/dev/null)"; done
# ---------- mdraid ----------
echo "==MDSTAT=="; cat /proc/mdstat 2>/dev/null
# ---------- nfs ----------
echo "==MOUNTS=="; grep -E 'nfs|lustre|ceph|glusterfs|gpfs|beegfs' /proc/mounts 2>/dev/null || true
echo "==PROCFSSTATS=="; cat /proc/net/fsstat nfs 2>/dev/null || true; cat /proc/fs/nfsfs/stats 2>/dev/null || true
# ---------- systemd ----------
echo "==SDFAILED=="; timeout 10 systemctl --failed --no-legend --plain 2>/dev/null | head -n 30 || true
echo "==SDSTATE=="; for s in sshd docker containerd kubelet slurmd nvidia-persistenced; do if command -v systemctl >/dev/null 2>&1; then echo "$s $(timeout 5 systemctl is-active $s 2>/dev/null)"; fi; done
# ---------- mig ----------
echo "==MIG=="; timeout 10 nvidia-smi mig --list-items 2>/dev/null | head -n 30 || true
echo "==MIGMODE=="; timeout 10 nvidia-smi --query-gpu=index,mig.mode.current --format=csv,noheader,nounits 2>/dev/null || true
# ---------- nvlink ----------
echo "==NVLINK=="; timeout 10 nvidia-smi nvlink -sc 2>/dev/null | head -n 60 || true
echo "==NVLINKST=="; timeout 10 nvidia-smi --query-gpu=index,nvlink.gpu.0.state,nvlink.gpu.1.state,nvlink.gpu.2.state,nvlink.gpu.3.state --format=csv,noheader,nounits 2>/dev/null | grep -v 'Field ' || true
# ---------- ipmi / bmc ----------
echo "==IPMI=="; timeout 10 ipmitool sdr 2>/dev/null | head -n 40 || true
true
"""

INVENTORY_SCRIPT = r"""
export LC_ALL=C LANG=C
echo "==MACHINEID=="; cat /etc/machine-id 2>/dev/null || true
echo "==DMI=="; for f in sys_vendor product_name product_serial product_uuid bios_version bios_date; do v=$(cat /sys/class/dmi/id/$f 2>/dev/null); [ -n "$v" ] && echo "$f=$v"; done
echo "==LSCPU=="; lscpu 2>/dev/null || true
echo "==NUMA=="; cat /sys/devices/system/node/has_cpu 2>/dev/null; ls /sys/devices/system/node/node*/cpulist 2>/dev/null | while read f; do echo "$(basename $(dirname $f)) $(cat $f)"; done
echo "==NUMAMEM=="; for n in /sys/devices/system/node/node*/meminfo; do [ -f "$n" ] && echo "$n: $(head -1 $n)"; done
echo "==GPULIST=="; timeout 10 nvidia-smi -L 2>/dev/null || true
echo "==GPUTOPO=="; timeout 15 nvidia-smi topo -m 2>/dev/null | head -n 30 || true
echo "==PCINUMA=="; for d in /sys/bus/pci/devices/*; do nn=$(cat $d/numa_node 2>/dev/null); cl=$(cat $d/class 2>/dev/null); case "$cl" in 0x0300*|0x0200*|0x0108*) echo "$(basename $d) $cl $nn $(cat $d/vendor 2>/dev/null) $(cat $d/device 2>/dev/null)";; esac; done
echo "==LSBLK=="; lsblk -d -n -o NAME,SIZE,ROTA,TYPE,SERIAL,MODEL 2>/dev/null || lsblk -d -n -o NAME,SIZE,TYPE 2>/dev/null || true
echo "==IPADDR=="; ip -o addr show scope global 2>/dev/null || true
echo "==NICLIST=="; for n in /sys/class/net/*; do [ -d "$n" ] || continue; i=$(basename "$n"); echo "$i $(cat $n/address 2>/dev/null) $(cat $n/operstate 2>/dev/null) $(cat $n/speed 2>/dev/null)"; done
echo "==IBSTAT=="; timeout 10 ibstat 2>/dev/null | head -n 60 || true
echo "==IBDEVINFO=="; timeout 10 ibdev2netdev 2>/dev/null | head -n 20 || true
echo "==TIMEDATE=="; timedatectl 2>/dev/null | head -n 8 || true
echo "==DMESGBOOT=="; dmesg 2>/dev/null | head -n 5 || true
echo "==UBUNTUVER=="; cat /etc/debian_version 2>/dev/null || true
echo "==ETHTOOLPER=="; for n in /sys/class/net/*; do i=$(basename "$n"); [ "$i" = "lo" ] && continue; sp=$(cat $n/speed 2>/dev/null); [ -n "$sp" ] && echo "$i $sp"; done
true
"""

# kernel events (fast-tier; incremental via since-boot-id + dmesg tail)
KERNEL_SCRIPT = r"""
export LC_ALL=C LANG=C
echo "==BOOTID=="; cat /proc/sys/kernel/random/boot_id 2>/dev/null
echo "==KLOG=="
if command -v journalctl >/dev/null 2>&1; then
  timeout 10 journalctl -k -n 400 --no-pager -o short-iso 2>/dev/null || true
else
  dmesg 2>/dev/null | tail -n 400 || true
  echo "__DMESG__"
fi
true
"""
