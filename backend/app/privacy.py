"""Response/storage minimization for process and infrastructure metadata."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


PROCESS_RESOURCE_FIELDS = (
    "pid",
    "ppid",
    "cpu",
    "mem",
    "rss_mb",
    "vsz_mb",
    "stat",
    "etimes",
    "mem_mb",
)


def minimize_process(process: dict[str, Any]) -> dict[str, Any]:
    """Keep operational resource fields while removing identity and argv."""
    return {key: process.get(key) for key in PROCESS_RESOURCE_FIELDS if key in process}


def minimize_processes(processes: list | None) -> list[dict[str, Any]]:
    return [minimize_process(p) for p in (processes or []) if isinstance(p, dict)]


def minimize_gpus(gpus: list | None) -> list[dict[str, Any]]:
    out = deepcopy(gpus or [])
    for gpu in out:
        if isinstance(gpu, dict):
            gpu["processes"] = minimize_processes(gpu.get("processes"))
    return out


def minimize_metric(metric: Any) -> dict[str, Any]:
    if isinstance(metric, dict):
        out = deepcopy(metric)
    else:
        out = {column.key: getattr(metric, column.key) for column in metric.__table__.columns}
    out["processes"] = minimize_processes(out.get("processes"))
    out["gpus"] = minimize_gpus(out.get("gpus"))
    # Logged-in user sessions and source addresses are not needed in metric
    # history responses; live admin-only endpoints remain available.
    out["users"] = []
    return out
