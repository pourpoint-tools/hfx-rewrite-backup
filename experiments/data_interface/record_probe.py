"""Focused record/spatial measurements, with source-only validation outside timed phases."""

from __future__ import annotations

import argparse
import hashlib
import json
from bisect import bisect_left
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc

from experiments.data_interface.probe import Access, table_identity

TRANSPORT = ("http_requests", "http_body_bytes", "local_read_calls", "local_read_bytes")


def source_records(root: Path, family: str, ids: list[int], columns: list[str] | None) -> tuple[pa.Table, list[int]]:
    """Independent bounded original lookup: equality matches, not candidate addresses."""
    manifest = json.loads((root / "manifest.json").read_text())
    declaration = (
        {"data": manifest["catchments"], "lookup": manifest["lookup"], "directory": manifest["directory"]}
        if family == "catchments"
        else manifest[family]
    )
    directory = json.loads((root / declaration["directory"]).read_text())["batches"]
    maxima = [entry["max_id"] for entry in directory]
    groups: dict[int, list[int]] = {}
    for identity in sorted(set(ids)):
        index = bisect_left(maxima, identity)
        if index < len(directory) and directory[index]["min_id"] <= identity:
            groups.setdefault(index, []).append(identity)
    addresses: dict[int, list[tuple[int, int]]] = {}
    with (
        pa.OSFile(str(root / declaration["lookup"]), "rb") as lookup_file,
        pa.OSFile(str(root / declaration["data"]), "rb") as data_file,
    ):
        lookup = ipc.open_file(lookup_file)
        full = ipc.open_file(data_file)
        names = full.schema.names if columns is None else columns
        included = sorted({full.schema.get_field_index(name) for name in [*names, "id"]})
        if -1 in included:
            raise ValueError("unknown source column")
        data = ipc.open_file(data_file, options=ipc.IpcReadOptions(included_fields=included))
        for index, wanted in groups.items():
            batch = lookup.get_batch(index)
            matches = np.flatnonzero(np.isin(batch["id"].to_numpy(), wanted)).tolist()
            for position in matches:
                identity = int(batch["id"][position].as_py())
                block, row = int(batch["block"][position].as_py()), int(batch["row"][position].as_py())
                addresses.setdefault(block, []).append((row, identity))
        pieces, found = [], []
        for block, targets in addresses.items():
            batch = data.get_batch(block)
            for row, identity in targets:
                if batch["id"][row].as_py() != identity:
                    raise ValueError("original lookup identity mismatch")
            pieces.append(batch.take(pa.array([row for row, _ in targets], type=pa.int64())))
            found.extend(identity for _, identity in targets)
        table = pa.Table.from_batches(pieces, schema=data.schema)
        positions = {identity: position for position, identity in enumerate(found)}
        table = table.take(
            pa.array([positions[identity] for identity in ids if identity in positions], type=pa.int64())
        )
        return table.select(names), sorted(set(ids) - positions.keys())


def validate_records(actual: pa.Table, absent: list[int], expected: pa.Table, missing: list[int]) -> dict[str, Any]:
    if absent != missing:
        raise ValueError("absent IDs differ from original lookup")
    if not actual.schema.equals(expected.schema, check_metadata=True) or not actual.equals(expected):
        raise ValueError("source records differ: values, nulls, native types, schema metadata or WKB")
    actual_hash, expected_hash = table_identity(actual), table_identity(expected)
    return {
        "semantic_equal": True,
        "arrow_stream_sha256": actual_hash,
        "source_arrow_stream_sha256": expected_hash,
        "stream_bytes_equal": actual_hash == expected_hash,
        "serialization_note": None
        if actual_hash == expected_hash
        else "Logical equality passed; investigate Arrow null-buffer/serialization differences.",
    }


def phase_stats(access: Access, before: dict[str, Any]) -> dict[str, Any]:
    result = access.stats()
    for key in TRANSPORT:
        result[key] -= before[key]
    for key in ("lookup_blocks", "data_blocks", "graph_blocks"):
        result[key + "_count"] = len(result[key])
    return result


def id_hash(ids: list[int]) -> str:
    return hashlib.sha256(np.asarray(ids, dtype="<i8").tobytes()).hexdigest()


def measure(
    bundle: str,
    source: Path,
    family: str,
    columns: list[str] | None,
    requests: list[list[int]],
    repeats: int,
    window: dict[str, Any] | None = None,
    level: int | None = None,
    *,
    graph_pre_buffer: bool = True,
    graph_grouped: bool = True,
    read_ahead_bytes: int = 0,
) -> dict[str, Any]:
    started = perf_counter()
    with Access(
        bundle,
        family,
        columns,
        graph_pre_buffer=graph_pre_buffer,
        graph_grouped=graph_grouped,
        read_ahead_bytes=read_ahead_bytes,
    ) as access:
        opening_s = perf_counter() - started
        opening = access.stats()
        source_sha = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
        if access.manifest.get("input_manifest_sha256", access.manifest_sha256) != source_sha:
            raise ValueError("bundle source manifest binding differs")
        report: dict[str, Any] = {
            "bundle": bundle,
            "family": family,
            "columns": columns,
            "manifest_sha256": access.manifest_sha256,
            "source_manifest_sha256": source_sha,
            "opening_s": opening_s,
            "opening": opening,
            "repeats": [],
            "cache_policy": "same Access; head/tail and reader metadata retained; no application selected-batch cache; "
            "optional IPC read-ahead retains bounded serialized data; Parquet pre-buffer uses Arrow defaults",
            "reader_options": {
                "graph_pre_buffer": graph_pre_buffer,
                "graph_grouped": graph_grouped,
                "read_ahead_bytes": read_ahead_bytes,
            },
            "filesystem_cache": "uncontrolled, not cold; original-source validation between repeats can warm source files",
            "process_setup": "interpreter/import startup excluded",
            "accounting": "materialized rows/bytes are feature or spatial graph batches, excluding lookup batches; output bytes are Arrow logical nbytes",
            "peak_rss": "cumulative process high-water, including validation",
            "measurement": "open + discovery + fetch + decode; validation, hashing, JSON excluded; fresh process required for reopen",
        }
        for repeat in range(repeats):
            results: list[dict[str, Any]] = []
            for requested in requests:
                discovery_s = 0.0
                discovery: dict[str, Any] | None = None
                if window is not None:
                    access.reset()
                    before = access.stats()
                    started = perf_counter()
                    requested = access.spatial(tuple(window["bounds_epsg4326"]), level=level)
                    discovery_s = perf_counter() - started
                    discovery = {"elapsed_s": discovery_s, **phase_stats(access, before)}
                access.reset()
                before = access.stats()
                started = perf_counter()
                table, absent = access.ids(requested)
                fetch_s = perf_counter() - started
                fetch = {"elapsed_s": fetch_s, **phase_stats(access, before)}
                decode_s = 0.0
                decoded = None
                if "geometry" in table.column_names:
                    import shapely

                    started = perf_counter()
                    geometries = shapely.from_wkb(table["geometry"].to_numpy())
                    decode_s = perf_counter() - started
                    decoded = len(geometries)
                    del geometries
                # All independent source reads, equality checks and hashes are deliberately outside timers.
                if window is not None:
                    oracle = window["all_tiers"] if level is None else window["by_independent_domain_tier"][str(level)]
                    if len(requested) != oracle["count"] or id_hash(requested) != oracle["sorted_ids_sha256_le_i64"]:
                        raise ValueError("spatial candidates differ from independent bbox oracle")
                expected, missing = source_records(source, family, requested, columns)
                validation = validate_records(table, absent, expected, missing)
                results.append(
                    {
                        "requested_rows": len(requested),
                        "unique_requested_rows": len(set(requested)),
                        "requested_ids_sha256_le_i64": id_hash(requested),
                        "absent": absent,
                        "output_rows": table.num_rows,
                        "output_logical_bytes": table.nbytes,
                        "requested_wkb_bytes": sum(
                            len(value) for value in table["geometry"].to_pylist() if value is not None
                        )
                        if "geometry" in table.column_names
                        else 0,
                        "spatial_discovery": discovery,
                        "record_fetch": fetch,
                        "geometry_decode_s": decode_s,
                        "decoded_geometries": decoded,
                        "operation_to_result_s": discovery_s + fetch_s + decode_s,
                        "total_to_result_s": discovery_s
                        + fetch_s
                        + decode_s
                        + (opening_s if repeat == 0 and not results else 0),
                        "opening_included": repeat == 0 and not results,
                        "validation": validation,
                    }
                )
                del table, expected
            report["repeats"].append(
                {
                    "repeat": repeat,
                    "operations": results,
                    "total_to_result_s": sum(result["operation_to_result_s"] for result in results)
                    + (opening_s if repeat == 0 else 0),
                }
            )
        report["requests"] = access.http.requests
        report["final"] = access.stats()
    report["closed"] = all(file.closed for file in access.files.values())
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--family", choices=["rivers", "catchments", "river_nodes"], default="rivers")
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument(
        "--catchment-records", type=Path, default=Path(__file__).with_name("results") / "catchments-records.json"
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--operation", choices=["records", "spatial"], default="records")
    parser.add_argument("--selection", choices=["clustered", "scattered", "overlap", "absent"], default="scattered")
    parser.add_argument(
        "--spatial-window",
        choices=["small", "elongated", "large_amazon", "empty", "source_batch_boundary"],
        default="small",
    )
    parser.add_argument("--level", type=int)
    parser.add_argument(
        "--node-spatial-oracle", type=Path, default=Path(__file__).with_name("results") / "source-node-spatial.json"
    )
    projection = parser.add_mutually_exclusive_group()
    projection.add_argument("--columns", nargs="+", default=None)
    projection.add_argument("--full", action="store_true")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--graph-pre-buffer", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--graph-grouped",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="pre-buffer selected graph groups together and stream projected batches",
    )
    parser.add_argument("--read-ahead-bytes", type=int, default=0, help="optional per-IPC-file serialized buffer")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    if args.report.exists():
        raise FileExistsError(args.report)
    if args.report.resolve().is_relative_to(args.source.resolve()) or (
        not args.bundle.startswith(("http://", "https://"))
        and args.report.resolve().is_relative_to(Path(args.bundle).resolve())
    ):
        raise ValueError("report must be outside data bundles")
    workloads = json.loads(args.workloads.read_text())
    records = (
        workloads.get("catchments_records") or json.loads(args.catchment_records.read_text())
        if args.family == "catchments"
        else workloads["nodes_records" if args.family == "river_nodes" else "rivers_records"]
    )
    clustered, scattered = records["clustered_ids"], records["scattered_ids"]
    selections = {
        "clustered": [clustered],
        "scattered": [scattered],
        "overlap": [clustered, [*clustered[len(clustered) // 2 :], *scattered, clustered[0]]],
        "absent": [[max(scattered) + 1]],
    }
    window = None
    if args.operation == "spatial":
        if args.family == "river_nodes":
            node_oracle = json.loads(args.node_spatial_oracle.read_text())
            if node_oracle["manifest_sha256"] != workloads["manifest_sha256"]:
                raise ValueError("node spatial oracle source manifest differs")
            window = {
                "bounds_epsg4326": node_oracle["window"]["bbox"],
                "all_tiers": {
                    "count": node_oracle["count"],
                    "sorted_ids_sha256_le_i64": node_oracle["sorted_ids_sha256_le_i64"],
                },
                "by_independent_domain_tier": node_oracle["by_tier"],
            }
        else:
            name = "empty_ocean" if args.spatial_window == "empty" else args.spatial_window
            window = workloads[args.family + "_graph"]["windows"][name]
    source_sha = hashlib.sha256((args.source / "manifest.json").read_bytes()).hexdigest()
    if workloads["manifest_sha256"] != source_sha or records.get("manifest_sha256", source_sha) != source_sha:
        raise ValueError("oracle source manifest identity differs")
    report = measure(
        args.bundle,
        args.source,
        args.family,
        None if args.full else (args.columns or ["id", "level", "bbox"]),
        [[]] if window else selections[args.selection],
        args.repeats,
        window,
        args.level,
        graph_pre_buffer=args.graph_pre_buffer,
        graph_grouped=args.graph_grouped,
        read_ahead_bytes=args.read_ahead_bytes,
    )
    if args.operation == "records" and args.selection == "absent":
        for repeat in report["repeats"]:
            operation = repeat["operations"][0]
            if operation["output_rows"] != 0 or operation["absent"] != selections["absent"][0]:
                raise ValueError("absent workload must resolve no rows in either source or candidate")
    report["selection"] = args.spatial_window if window else args.selection
    report["level"] = args.level
    if window is not None and args.family == "river_nodes":
        report["selection"] = "first_source_node"
        report["node_spatial_oracle_sha256"] = hashlib.sha256(args.node_spatial_oracle.read_bytes()).hexdigest()
    report["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["workloads_sha256"] = hashlib.sha256(args.workloads.read_bytes()).hexdigest()
    with args.report.open("x") as output:
        output.write(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
