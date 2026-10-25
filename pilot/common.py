import hashlib
import importlib.metadata
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    def safe(item):
        if isinstance(item, dict):
            return {str(k): safe(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [safe(v) for v in item]
        return item
    temp.write_text(json.dumps(safe(value), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    temp.replace(path)


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def versions():
    names = ["numpy", "pandas", "pyarrow", "dask", "distributed", "psutil", "matplotlib", "bokeh"]
    return {"python": platform.python_version(), **{n: importlib.metadata.version(n) for n in names}}


def roots():
    return tuple(Path(os.environ.get(k, v)) for k, v in [
        ("DATA_ROOT", "/data/inputs"), ("RESULTS_ROOT", "/data/experiments"),
        ("SCRATCH_ROOT", "/scratch")])


def cgroup_state():
    """Read actual kernel limits, not the Compose declaration. Supports cgroup v2/v1."""
    base = Path("/sys/fs/cgroup")
    def get(*paths):
        for p in paths:
            try:
                return (base / p).read_text().strip()
            except OSError:
                pass
        return None
    raw = get("cpu.max")
    cpus = None
    if raw:
        quota, period = raw.split()
        if quota != "max":
            cpus = int(quota) / int(period)
    else:
        q, p = get("cpu/cpu.cfs_quota_us"), get("cpu/cpu.cfs_period_us")
        if q and p and int(q) > 0:
            cpus = int(q) / int(p)
    mem = get("memory.max", "memory/memory.limit_in_bytes")
    return {"cpu_limit": cpus, "memory_limit_bytes": int(mem) if mem and mem != "max" else None,
            "cpu_max_raw": raw, "memory_events": get("memory.events"),
            "swap_max": get("memory.swap.max"), "platform": platform.platform(),
            "storage": {"inputs": str(roots()[0]), "results": str(roots()[1]),
                        "scratch": str(roots()[2])}}


def parse_memory(value):
    value = value.lower().strip()
    for suffix, scale in [("g", 2**30), ("m", 2**20), ("k", 2**10)]:
        if value.endswith(suffix):
            return int(float(value[:-1]) * scale)
    return int(value)


def verify_limits(state, allow_host=False):
    if allow_host:
        return "host check: no Docker resource equivalence; excluded from pilot"
    expected_cpu = float(os.environ.get("EXPECTED_CPUS", "2"))
    expected_mem = parse_memory(os.environ.get("EXPECTED_MEMORY", "3g"))
    if state["cpu_limit"] is None or abs(state["cpu_limit"] - expected_cpu) > .001:
        raise RuntimeError(f"Effective CPU limit differs: {state}; expected {expected_cpu}")
    if state["memory_limit_bytes"] != expected_mem:
        raise RuntimeError(f"Effective memory limit differs: {state}; expected {expected_mem}")
    return "kernel cgroup limits match expected budget"
