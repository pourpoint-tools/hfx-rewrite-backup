"""Counted native GeoParquet trial; independent source validation is outside timers."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any, cast
from urllib.parse import urljoin

import pyarrow as pa

from experiments.data_interface.geoparquet import GEO, GeoParquetAccess
from experiments.data_interface.record_probe import TRANSPORT, id_hash, source_records, validate_records
from scripts.check_vector_access import HTTP


def source_schema_table(table: pa.Table) -> pa.Table:
    metadata = dict(table.schema.metadata or {})
    if json.loads(metadata.pop(b"geo", b"null")) != GEO:
        raise ValueError("additive geo metadata differs")
    return table.replace_schema_metadata(metadata or None)


def measure(
    bundle: str,
    candidate: str,
    source: Path,
    columns: list[str],
    requested: list[int],
    repeats: int,
    window: dict[str, Any] | None = None,
    level: int | None = None,
    decode: bool = False,
) -> dict[str, Any]:
    started = perf_counter()
    transport = HTTP()
    declaration_bytes = (
        transport.get(urljoin(bundle.rstrip("/") + "/", "manifest.json"))
        if bundle.startswith("http")
        else (Path(bundle) / "manifest.json").read_bytes()
    )
    declaration = json.loads(declaration_bytes)
    if declaration["verification"]["status"] != "passed":
        raise ValueError("derivative verification missing")
    artifact = urljoin(bundle.rstrip("/") + "/", declaration["artifact"])
    access = GeoParquetAccess(artifact, candidate, declaration["binding"])
    try:
        access.http.requests[:0] = transport.requests  # Charge declaration discovery, not just feature opening.
        opening_s, opening = perf_counter() - started, access.stats()
        source_sha = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
        if access.manifest.get("input_manifest_sha256") != source_sha:
            raise ValueError("authoritative source binding differs")
        report: dict[str, Any] = {
            "opening_s": opening_s,
            "opening": opening,
            "declaration_sha256": hashlib.sha256(declaration_bytes).hexdigest(),
            "source_manifest_sha256": source_sha,
            "repeats": [],
            "phase": "spatial_discovery_and_fetch" if window else "record_fetch",
            "policy": "retained native footer; lazy locator; pre_buffer=True/use_threads=False; no application batch cache; filesystem/CDN uncontrolled; validation outside timers; geometry decode separate",
        }
        for repeat in range(repeats):
            before = access.stats()
            started = perf_counter()
            table, absent = (
                (access.spatial(tuple(window["bounds_epsg4326"]), columns, level), [])
                if window
                else access.ids(requested, columns)
            )
            acquisition_s = perf_counter() - started
            after = access.stats()
            phase = {
                key: after[key] - before[key]
                for key in (*TRANSPORT, "materialized_rows", "materialized_bytes", "materialized_geometry_bytes")
            }
            phase.update(
                {
                    "elapsed_s": acquisition_s,
                    "discovery_groups": access.discovery_groups,
                    "record_groups": access.last_groups,
                }
            )
            actual_ids = cast(list[int], table.column("id").to_pylist())
            if window:
                requested = sorted(actual_ids)
                oracle = window["all_tiers"] if level is None else window["by_independent_domain_tier"][str(level)]
                if len(requested) != oracle["count"] or id_hash(requested) != oracle["sorted_ids_sha256_le_i64"]:
                    raise ValueError("spatial IDs differ from source-only window witness")
                # Physical Morton order differs from sorted source witness; compare records in returned order.
                requested = actual_ids
            expected, missing = source_records(source, "rivers", requested, columns)
            validation = validate_records(source_schema_table(table), absent, expected, missing)
            decode_s = 0.0
            if decode and "geometry" in columns:
                import shapely

                started = perf_counter()
                geometries = shapely.from_wkb(table.column("geometry").to_numpy())
                decode_s = perf_counter() - started
                del geometries
            report["repeats"].append(
                {
                    "repeat": repeat,
                    "acquisition": phase,
                    "geometry_decode_s": decode_s,
                    "output_rows": table.num_rows,
                    "output_logical_bytes": table.nbytes,
                    "requested_wkb_bytes": sum(
                        len(value) for value in cast(list[bytes], table.column("geometry").to_pylist())
                    )
                    if "geometry" in columns
                    else 0,
                    "absent": absent,
                    "validation": validation,
                    "total_to_result_s": acquisition_s + decode_s + (opening_s if repeat == 0 else 0),
                }
            )
        report.update({"requests": access.http.requests, "final": access.stats()})
        return report
    finally:
        access.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--columns", nargs="+", default=["id", "level", "bbox"])
    parser.add_argument("--selection", choices=["clustered", "scattered", "absent"], default="scattered")
    parser.add_argument("--spatial-window")
    parser.add_argument("--level", type=int)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--decode-geometry", action="store_true")
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    if args.repeats < 1 or "id" not in args.columns:
        parser.error("positive repeats and id projection required")
    if any(
        args.report.resolve().is_relative_to(Path(root).resolve())
        for root in [str(args.source), *[p for p in (args.bundle, args.candidate) if not p.startswith("http")]]
    ):
        raise ValueError("report must be outside bundles")
    workloads = json.loads(args.workloads.read_bytes())
    if workloads["manifest_sha256"] != hashlib.sha256((args.source / "manifest.json").read_bytes()).hexdigest():
        raise ValueError("workload source differs")
    records = workloads["rivers_records"]
    requested = [max(records["scattered_ids"]) + 1] if args.selection == "absent" else records[args.selection + "_ids"]
    window = (
        workloads["rivers_graph"]["windows"]["empty_ocean" if args.spatial_window == "empty" else args.spatial_window]
        if args.spatial_window
        else None
    )
    report = measure(
        args.bundle,
        args.candidate,
        args.source,
        args.columns,
        requested,
        args.repeats,
        window,
        args.level,
        args.decode_geometry,
    )
    report.update(
        {
            "workloads_sha256": hashlib.sha256(args.workloads.read_bytes()).hexdigest(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
    )
    with args.report.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
