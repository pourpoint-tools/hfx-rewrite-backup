"""Time projected original scalar references and one reverse index, locally only."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc


def prepare(
    path: Path, column: str
) -> tuple[pa.Table, np.ndarray[Any, np.dtype[np.int64]], np.ndarray[Any, np.dtype[np.int64]], dict[str, float]]:
    started = perf_counter()
    schema = pa.ipc.open_file(str(path)).schema
    fields = [schema.get_field_index(name) for name in ("id", column)]
    if -1 in fields:
        raise ValueError("missing source column")
    reader = pa.ipc.open_file(str(path), options=pa.ipc.IpcReadOptions(included_fields=fields))
    table = reader.read_all().combine_chunks()
    read_s = perf_counter() - started
    started = perf_counter()
    valid = pc.is_valid(table[column])
    keys = np.asarray(pc.filter(table[column], valid).to_numpy(), dtype=np.int64)
    ids = np.asarray(pc.filter(table["id"], valid).to_numpy(), dtype=np.int64)
    order = np.lexsort((ids, keys))
    keys, ids = keys[order], ids[order]
    return table, keys, ids, {"original_projected_scan_s": read_s, "reverse_prepare_s": perf_counter() - started}


def reverse(
    keys: np.ndarray[Any, np.dtype[np.int64]], ids: np.ndarray[Any, np.dtype[np.int64]], target: int
) -> np.ndarray[Any, np.dtype[np.int64]]:
    low, high = np.searchsorted(keys, target, side="left"), np.searchsorted(keys, target, side="right")
    return ids[int(low) : int(high)].copy()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--column", required=True)
    parser.add_argument("--targets", type=int, nargs="+", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    if args.report.resolve().is_relative_to(args.source.resolve().parent):
        raise ValueError("report must be outside input bundle")
    manifest_bytes = (args.source.parent / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    source_identity = manifest["artifacts"][args.source.name]
    started = perf_counter()
    table, keys, ids, preparation = prepare(args.source, args.column)
    prepare_s = perf_counter() - started
    phases = []
    for target in args.targets:
        for repeat in range(args.repeats):
            started = perf_counter()
            result = reverse(keys, ids, target)
            elapsed = perf_counter() - started
            phases.append(
                {
                    "target": target,
                    "repeat": repeat,
                    "seconds": elapsed,
                    "count": len(result),
                    "output_bytes": result.nbytes,
                    "sorted_ids_sha256": hashlib.sha256(result.astype("<i8", copy=False).tobytes()).hexdigest(),
                }
            )
    report = {
        "source": str(args.source),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "source_artifact_identity": source_identity,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "column": args.column,
        "kind": "local_consumer_projected_original_reverse_index",
        "prepare_s": prepare_s,
        "prepare_phases": preparation,
        "source_rows": table.num_rows,
        "retained_arrow_bytes": table.nbytes,
        "retained_reverse_numeric_bytes": keys.nbytes + ids.nbytes,
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if platform.system() == "Darwin" else 1024),
        "pyarrow": pa.__version__,
        "numpy": np.__version__,
        "cache": "fresh process; filesystem uncontrolled; no geometry decode",
        "limitations": "local only; Python/native allocator overhead excluded from retained numeric buffers; temporary sort allocations only reflected in process lifetime RSS; no whole-file hash during consumer prepare (separately verified source)",
        "queries": phases,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
