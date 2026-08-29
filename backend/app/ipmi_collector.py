"""Out-of-band IPMI collection executed on the MONITOR host.

Runs the local ipmitool binary over lanplus against each server's BMC, so
hardware visibility survives OS crashes / shutdowns. The password is passed
via IPMITOOL_PASSWORD (never argv). All output sections are parsed loosely:
unknown vendors degrade to raw-ish key/value dumps instead of failing.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time

logger = logging.getLogger("gpumon.ipmi")

_CMD_TIMEOUT = 20  # per sub-command; lanplus retries are limited via -N/-R


def ipmitool_available() -> bool:
    return shutil.which("ipmitool") is not None


def _run(host: str, user: str, password: str, args: list[str]):
    cmd = ["ipmitool", "-I", "lanplus", "-H", host, "-U", user,
           "-N", "6", "-R", "1", "-E"] + args
    env = dict(os.environ, IPMITOOL_PASSWORD=password or "", LC_ALL="C")
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=_CMD_TIMEOUT, env=env)
    return p.returncode, p.stdout or "", (p.stderr or "").strip()


def _parse_kv(text: str) -> dict:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k:
                out[k] = v
    return out


def _parse_sdr(text: str) -> list[dict]:
    sensors = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 4 and parts[0]:
            sensors.append({
                "name": parts[0],
                "id": parts[1],
                "status": parts[2],
                "entity": parts[3],
                "reading": parts[4] if len(parts) > 4 else "",
            })
    return sensors


def _parse_sel(text: str) -> list[dict]:
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|", 3)]
        if len(parts) >= 4:
            entries.append({"record": parts[0], "date": parts[1],
                            "time": parts[2], "event": parts[3]})
        else:
            entries.append({"event": line.strip()})
    return entries


def _parse_fru(text: str) -> list[dict]:
    devices: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if "FRU Device Description" in k:
            cur = {"description": v}
            devices.append(cur)
        elif cur is not None:
            cur[k] = v
    return devices


def collect_ipmi(host: str, user: str, password: str) -> dict:
    """Collect every useful ipmitool section; never raises."""
    t0 = time.time()
    empty = {
        "ok": False, "error": "", "mc_info": {}, "chassis": {}, "power": {},
        "sensors": [], "sel": [], "sel_info": {}, "fru": [], "lan": {},
    }
    if not ipmitool_available():
        return {**empty, "error": "监控主机未安装 ipmitool",
                "duration": round(time.time() - t0, 2)}

    rc, out, err = _run(host, user, password, ["mc", "info"])
    if rc != 0:
        msg = (err or out or "BMC 连接失败").strip().splitlines()
        return {**empty, "error": (msg[-1] if msg else "BMC 连接失败")[:300],
                "duration": round(time.time() - t0, 2)}

    result = {**empty, "ok": True, "mc_info": _parse_kv(out)}
    sections = (
        ("chassis", ["chassis", "status"], _parse_kv, {}),
        ("power", ["dcmi", "power", "reading"], _parse_kv, {}),
        ("sensors", ["sdr", "elist", "full"], _parse_sdr, []),
        ("sel", ["sel", "list", "last", "100"], _parse_sel, []),
        ("sel_info", ["sel", "info"], _parse_kv, {}),
        ("fru", ["fru", "list"], _parse_fru, []),
        ("lan", ["lan", "print"], _parse_kv, {}),
    )
    for key, args, parser, fallback in sections:
        try:
            rc, out, err = _run(host, user, password, args)
            result[key] = parser(out) if rc == 0 else fallback
        except subprocess.TimeoutExpired:
            result[key] = fallback
            logger.warning("ipmi %s timed out for %s", " ".join(args), host)
        except Exception:
            result[key] = fallback
            logger.exception("ipmi %s failed for %s", " ".join(args), host)
    result["duration"] = round(time.time() - t0, 2)
    return result


# ---------------- derived summary (alerts / KPIs) ----------------

def summarize(result: dict) -> dict:
    """Extract the few values detectors and dashboards care about."""
    power_w = 0
    for k, v in (result.get("power") or {}).items():
        kl = k.lower()
        if "instantaneous" in kl and "power" in kl:
            digits = "".join(c for c in v.split("W")[0] if c.isdigit())
            power_w = int(digits) if digits else 0
            break
    chassis = result.get("chassis") or {}
    power_on = False
    for k, v in chassis.items():
        if "system power" in k.lower():
            power_on = v.strip().lower() == "on"
    psu_bad = [
        s["name"] for s in (result.get("sensors") or [])
        if s.get("status") not in ("ok", "")
        and any(t in s["name"].lower() for t in ("ps", "psu", "power supply"))
    ]
    fan_bad = [
        s["name"] for s in (result.get("sensors") or [])
        if s.get("status") not in ("ok", "") and "fan" in s["name"].lower()
    ]
    critical_kw = ("uncorrectable", "critical", "failure", "failed", "fatal",
                   "non-recoverable", "ierr", "machine check")
    sel_critical = [
        e for e in (result.get("sel") or [])
        if any(w in (e.get("event") or "").lower() for w in critical_kw)
    ]
    return {
        "power_w": power_w,
        "power_on": power_on,
        "psu_bad": psu_bad,
        "fan_bad": fan_bad,
        "sel_critical": sel_critical,
    }
