"""One immutable physical dataset per N, seed pair and file layout."""
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from .common import file_hash, identity, read_json, write_json


def values(keys, seed, column):
    # Exact binary fractions of small integers; deterministic and independently
    # checkable in chunks, with no second full expected DataFrame in memory.
    salt = seed * 104729 + column * 15485863
    return ((keys * (2 * column + 3) + salt) % 16777213).astype("float64") / 1024.0


def generate(root, n, seeds, files):
    spec = {"n": n, "seeds": seeds, "files_per_table": files, "compression": "snappy",
            "generator": "PCG64-permutation+modular-binary-fractions-v1",
            "dtypes": {"chave": "int64", "values": "float64"}}
    dataset_id = identity(spec)
    target = Path(root) / dataset_id[:20]
    manifest_path = target / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if manifest["spec"] != spec:
            raise ValueError("Dataset manifest collision")
        for f in manifest["files"]:
            if file_hash(target / f["path"]) != f["sha256"]:
                raise ValueError(f"Input corruption: {f['path']}")
        return manifest
    if target.exists():
        raise RuntimeError(f"Incomplete dataset must be inspected manually: {target}")
    staging = target.with_name(target.name + ".generating")
    if staging.exists():
        raise RuntimeError(f"Interrupted generation must be inspected: {staging}")
    staging.mkdir(parents=True)
    records = []
    for table in ("a", "b"):
        folder = staging / table
        folder.mkdir()
        keys = np.random.Generator(np.random.PCG64(seeds[table])).permutation(n).astype("int64")
        for i, chunk in enumerate(np.array_split(keys, files)):
            frame = pd.DataFrame({"chave": chunk, **{
                f"{table}{c}": values(chunk, seeds[table], c) for c in (1, 2)}})
            path = folder / f"part-{i:04d}.parquet"
            frame.to_parquet(path, engine="pyarrow", compression="snappy", index=False)
            records.append({"path": f"{table}/{path.name}", "rows": len(frame),
                            "bytes": path.stat().st_size, "sha256": file_hash(path)})
        del keys, frame
    manifest = {"dataset_id": dataset_id, "directory": str(target), "spec": spec,
                "column_values_bytes_both_tables": n * 48,
                "parquet_bytes": sum(f["bytes"] for f in records), "files": records}
    write_json(staging / "manifest.json", manifest)
    staging.rename(target)
    return manifest


def validate(result, n, seeds, chunk_size=131072):
    expected = {"chave": "int64", "a1": "float64", "a2": "float64",
                "b1": "float64", "b2": "float64"}
    if len(result) != n or set(result.columns) != set(expected):
        raise AssertionError(f"Shape/columns mismatch: {result.shape}, {list(result.columns)}")
    if {c: str(result[c].dtype) for c in expected} != expected:
        raise AssertionError("Dtype mismatch")
    seen = np.zeros(n, dtype=bool)
    for start in range(0, n, chunk_size):
        part = result.iloc[start:start + chunk_size]
        keys = part["chave"].to_numpy()
        if keys.min() < 0 or keys.max() >= n:
            raise AssertionError("Key outside expected range")
        if len(np.unique(keys)) != len(keys) or seen[keys].any():
            raise AssertionError("Duplicate keys")
        seen[keys] = True
        for t in ("a", "b"):
            for c in (1, 2):
                if not np.array_equal(part[f"{t}{c}"].to_numpy(), values(keys, seeds[t], c)):
                    raise AssertionError(f"Value mismatch in {t}{c}")
    if not seen.all():
        raise AssertionError("Missing keys")
    return {"ok": True, "rows": n, "dtypes": expected, "comparison": "exact, order independent",
            "tolerance": 0, "extra_memory": "N-byte bitmap plus bounded chunks"}
