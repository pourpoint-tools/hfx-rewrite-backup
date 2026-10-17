"""Extend source-only GRIT witnesses; no candidate imports or benchmark timing."""

from __future__ import annotations

import argparse
import hashlib
import json
from bisect import bisect_left
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Any, TypedDict

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

PINNED_MANIFEST = "b9a38083131dcf1a4c7c4e73ebe9a97dff2a4b7ef91a8df53f8bc38cadfa48db"


class SelectedRow(TypedDict):
    ordinal: int
    id: int
    level: int


def summary(ids: np.ndarray[Any, Any]) -> dict[str, Any]:
    def digest(values: np.ndarray[Any, Any]) -> str:
        return hashlib.sha256(np.asarray(values, dtype="<i8").tobytes()).hexdigest()

    return {
        "count": int(len(ids)),
        "ordered_ids_sha256_le_i64": digest(ids),
        "sorted_ids_sha256_le_i64": digest(np.sort(ids)),
        "first_ids": ids[:8].tolist(),
        "last_ids": ids[-8:].tolist(),
    }


def medium_window(small: Sequence[float]) -> tuple[float, float, float, float]:
    """Use a 0.2-degree investigatory square, not a production selection threshold."""
    x = (small[0] + small[2]) / 2
    y = (small[1] + small[3]) / 2
    return x - 0.1, y - 0.1, x + 0.1, y + 0.1


def row_ordinals(rows: int, count: int) -> list[int]:
    if not 1 < count <= rows:
        raise ValueError("Expected at least two selections within source row count")
    return [index * (rows - 1) // (count - 1) for index in range(count)]


def selected_rows(reader: ipc.RecordBatchFileReader, ordinals: Sequence[int]) -> list[SelectedRow]:
    if not ordinals or list(ordinals) != sorted(set(ordinals)) or ordinals[0] < 0:
        raise ValueError("Expected sorted unique nonnegative source row ordinals")
    selected: list[SelectedRow] = []
    base = 0
    for index in range(reader.num_record_batches):
        batch = reader.get_batch(index)
        stop = base + batch.num_rows
        low = bisect_left(ordinals, base)
        high = bisect_left(ordinals, stop)
        for ordinal in ordinals[low:high]:
            row = ordinal - base
            selected.append(
                {"ordinal": ordinal, "id": int(batch["id"][row].as_py()), "level": int(batch["level"][row].as_py())}
            )
        base = stop
        if len(selected) == len(ordinals):
            return selected
    raise ValueError("Source row ordinal exceeds file")


def medium_witness(path: Path, bounds: tuple[float, float, float, float]) -> dict[str, Any]:
    expanded = [
        float(np.nextafter(np.float32(value), np.float32(-np.inf if index < 2 else np.inf)))
        for index, value in enumerate(bounds)
    ]
    columns = ["id", "level", "bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"]
    pieces: list[np.ndarray[Any, np.dtype[np.int64]]] = []
    tiers: dict[int, list[np.ndarray[Any, np.dtype[np.int64]]]] = {}
    graph = pq.ParquetFile(path)
    try:
        for batch in graph.iter_batches(columns=columns, use_threads=False):
            ids = np.asarray(batch["id"].to_numpy(), dtype=np.int64)
            levels = batch["level"].to_numpy()
            xlo, ylo, xhi, yhi = [batch[name].to_numpy() for name in columns[2:]]
            mask = (xlo <= expanded[2]) & (ylo <= expanded[3]) & (xhi >= expanded[0]) & (yhi >= expanded[1])
            pieces.append(ids[mask])
            for tier in np.unique(levels).tolist():
                tiers.setdefault(int(tier), []).append(ids[mask & (levels == tier)])
    finally:
        graph.close()
    return {
        "bounds_epsg4326": list(bounds),
        "expanded_float32_bounds": expanded,
        "all_tiers": summary(np.concatenate(pieces)),
        "by_independent_domain_tier": {
            str(tier): summary(np.concatenate(values)) for tier, values in sorted(tiers.items())
        },
        "derivation": "0.2 degree ordinary square centered on existing source-only small-window center",
    }


def many_witness(path: Path, rows: int, count: int) -> dict[str, Any]:
    clustered = list(range(count))
    dispersed = row_ordinals(rows, count)
    requested = sorted(set(clustered) | set(dispersed))
    with pa.OSFile(str(path), "rb") as source:
        source.seek(8)
        schema = ipc.read_schema(ipc.read_message(source))
        fields = [schema.get_field_index(name) for name in ["id", "level"]]
        reader = ipc.open_file(source, options=ipc.IpcReadOptions(included_fields=fields))
        by_ordinal = {row["ordinal"]: row for row in selected_rows(reader, requested)}
    result: dict[str, Any] = {}
    for label, ordinals in [("many_clustered", clustered), ("many_dispersed", dispersed)]:
        values = [by_ordinal[ordinal] for ordinal in ordinals]
        ids = np.asarray([row["id"] for row in values], dtype=np.int64)
        levels, counts = np.unique([row["level"] for row in values], return_counts=True)
        result[label] = {
            "selection": "first source rows"
            if label == "many_clustered"
            else "uniform source row ordinals including first/last; integer floor division",
            "row_ordinals": ordinals,
            "requested_ids": ids.tolist(),
            "source_levels": [row["level"] for row in values],
            "by_tier_count": {
                str(level): int(size) for level, size in zip(levels.tolist(), counts.tolist(), strict=True)
            },
            **summary(ids),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument("--catchment-records", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--count", type=int, default=4096, help="investigatory known-ID workload size, not a product cap"
    )
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    if args.report.resolve().is_relative_to(args.source.resolve()):
        raise ValueError("Report must be outside source bundle")
    started = perf_counter()
    raw = (args.source / "manifest.json").read_bytes()
    source_sha = hashlib.sha256(raw).hexdigest()
    if source_sha != PINNED_MANIFEST:
        raise ValueError("Expected pinned original manifest")
    manifest = json.loads(raw)
    original = json.loads(args.workloads.read_text())
    if original["manifest_sha256"] != source_sha:
        raise ValueError("Original workload source identity differs")
    result = deepcopy(original)
    catchment_records = json.loads(args.catchment_records.read_text())
    if catchment_records["manifest_sha256"] != source_sha:
        raise ValueError("Catchment record source identity differs")
    result["catchments_records"] = catchment_records
    phases: dict[str, float] = {}
    bindings: dict[str, Any] = {}
    for family in ["rivers", "catchments"]:
        declaration = (
            manifest[family]
            if family == "rivers"
            else {"data": manifest["catchments"], "graph": manifest["graph"], "count": manifest["unit_count"]}
        )
        graph = declaration["graph"]
        data = declaration["data"]
        phase = perf_counter()
        bounds = medium_window(result[family + "_graph"]["windows"]["small"]["bounds_epsg4326"])
        result[family + "_graph"]["windows"]["medium"] = medium_witness(args.source / graph, bounds)
        phases[family + "_medium_s"] = perf_counter() - phase
        phase = perf_counter()
        result[family + "_records"].update(many_witness(args.source / data, declaration["count"], args.count))
        phases[family + "_many_ids_s"] = perf_counter() - phase
        bindings[family] = {name: manifest["artifacts"][name] for name in [data, graph]}
    for key, value in original.items():
        if key.endswith("_graph"):
            assert all(result[key]["windows"][name] == witness for name, witness in value["windows"].items())
        elif key.endswith("_records"):
            assert all(result[key][name] == witness for name, witness in value.items())
        else:
            assert result[key] == value
    result["extension"] = {
        "scope": "source-only workload extension; not performance evidence or global reauthentication",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_workloads_sha256": hashlib.sha256(args.workloads.read_bytes()).hexdigest(),
        "input_catchment_records_sha256": hashlib.sha256(args.catchment_records.read_bytes()).hexdigest(),
        "versions": {"pyarrow": pa.__version__, "numpy": np.__version__},
        "source_bindings": bindings,
        "count_per_known_id_selection": args.count,
        "phases_s": phases,
        "elapsed_s": perf_counter() - started,
        "constants": {"medium_radius_degrees": 0.1, "known_id_count": args.count},
        "source_authentication": "exact pinned manifest; full artifacts verified separately by parent; this source-only scan does not rehash full artifacts",
    }
    with args.report.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "report": str(args.report),
                "extension": result["extension"],
                "medium": {
                    family: result[family + "_graph"]["windows"]["medium"]["all_tiers"]
                    for family in ["rivers", "catchments"]
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
