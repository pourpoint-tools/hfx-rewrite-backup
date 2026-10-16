"""Candidate associations + bbox candidates + records; not exact geographic selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from contextlib import ExitStack
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import numpy as np
import pyarrow as pa

from experiments.data_interface.probe import Access
from experiments.data_interface.record_probe import id_hash, phase_stats, source_records, validate_records


def measure(
    bundle: str,
    source: Path,
    catchment: int,
    association: str,
    window: dict[str, Any],
    oracle: dict[str, Any],
    repeats: int,
    geometry: bool = False,
) -> dict[str, Any]:
    shapely_version = None
    if geometry:
        import shapely

        shapely_version = shapely.__version__
    columns = ["id", "bbox", "source_length"] + (["geometry"] if geometry else [])
    source_sha = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    with ExitStack() as stack:
        started = perf_counter()
        relations = stack.enter_context(Access(bundle, "catchments", ["id", association], relationship=True))
        relation_open_s = perf_counter() - started
        started = perf_counter()
        rivers = stack.enter_context(Access(bundle, "rivers", columns))
        river_open_s = perf_counter() - started
        for access in (relations, rivers):
            if not access.manifest.get("experimental") or access.manifest.get("input_manifest_sha256") != source_sha:
                raise ValueError("candidate must bind to exact original source manifest")
        report: dict[str, Any] = {
            "source_manifest_sha256": source_sha,
            "candidate_manifest_sha256": rivers.manifest_sha256,
            "catchment": catchment,
            "association": association,
            "geometry": geometry,
            "shapely_version": shapely_version,
            "repeats": [],
            "opening": {
                "association_s": relation_open_s,
                "rivers_s": river_open_s,
                "association": relations.stats(),
                "rivers": rivers.stats(),
            },
            "scope": "candidate composition only; bbox overlap and explicit association intersection, not exact intersection/containment",
            "comparison": "original consumer reverse-association preparation measured separately, not hidden outside this timer",
            "cache": "same Access per repeat, bounded ranges/metadata only, no selected-batch cache; filesystem uncontrolled, not cold",
            "memory": "Arrow logical tables and numeric arrays reported separately; Python lists/objects excluded; process peak is cumulative including validation",
            "timing": "phase sums exclude validation/hash/JSON and interpreter imports; first sum includes opening; fresh process for reopen",
        }
        for repeat in range(repeats):
            phases: dict[str, Any] = {}
            relations.reset()
            before = relations.stats()
            started = perf_counter()
            relation_table, absent = relations.ids([catchment])
            associated = np.sort(cast(pa.ListArray, relation_table[association].combine_chunks()).flatten().to_numpy())
            phases["association"] = {"elapsed_s": perf_counter() - started, **phase_stats(relations, before)}
            rivers.reset()
            before = rivers.stats()
            started = perf_counter()
            discovered = np.asarray(rivers.spatial(tuple(window["bounds_epsg4326"])), dtype=np.int64)
            phases["discovery"] = {"elapsed_s": perf_counter() - started, **phase_stats(rivers, before)}
            started = perf_counter()
            selected = np.intersect1d(associated, discovered)
            phases["intersection"] = {"elapsed_s": perf_counter() - started}
            rivers.reset()
            before = rivers.stats()
            started = perf_counter()
            table, missing = rivers.ids(selected.tolist())
            phases["records"] = {"elapsed_s": perf_counter() - started, **phase_stats(rivers, before)}
            phases["decode"] = {"elapsed_s": 0.0, "count": None}
            if geometry:
                started = perf_counter()
                decoded = shapely.from_wkb(table["geometry"].to_numpy())
                phases["decode"] = {"elapsed_s": perf_counter() - started, "count": len(decoded)}
                del decoded
            # Independent source expectations and hashes never run inside timed phases.
            spatial_oracle = window["all_tiers"]
            if absent or missing or relation_table.num_rows != 1:
                raise ValueError("absent catchment or river IDs")
            if len(associated) != oracle["count"] or id_hash(associated.tolist()) != oracle["sorted_ids_sha256"]:
                raise ValueError("association differs from archived original-source oracle")
            if (
                len(discovered) != spatial_oracle["count"]
                or id_hash(discovered.tolist()) != spatial_oracle["sorted_ids_sha256_le_i64"]
            ):
                raise ValueError("discovery differs from independent original bbox oracle")
            expected, source_missing = source_records(source, "rivers", selected.tolist(), columns)
            validation = validate_records(table, missing, expected, source_missing)
            report["repeats"].append(
                {
                    "repeat": repeat,
                    "phases": phases,
                    "total_to_result_s": sum(phase["elapsed_s"] for phase in phases.values())
                    + (relation_open_s + river_open_s if repeat == 0 else 0),
                    "association_count": len(associated),
                    "association_ids_sha256_le_i64": id_hash(associated.tolist()),
                    "discovery_ids_sha256_le_i64": id_hash(discovered.tolist()),
                    "discovery_count": len(discovered),
                    "selected_count": len(selected),
                    "selected_ids_sha256_le_i64": id_hash(selected.tolist()),
                    "validation": validation,
                    "retained": {
                        "relation_table_logical_bytes": relation_table.nbytes,
                        "result_table_logical_bytes": table.nbytes,
                        "association_array_bytes": associated.nbytes,
                        "discovery_array_bytes": discovered.nbytes,
                        "intersection_array_bytes": selected.nbytes,
                    },
                    "final_association": relations.stats(),
                    "final_rivers": rivers.stats(),
                }
            )
            del relation_table, associated, discovered, selected, table, expected
        report["http_requests"] = {"association": relations.http.requests, "rivers": rivers.http.requests}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument("--oracles", type=Path, required=True)
    parser.add_argument("--catchment", type=int, required=True)
    parser.add_argument("--association", choices=["local_river_ids", "component_river_ids"], required=True)
    parser.add_argument("--window", choices=["small", "large_amazon"], default="small")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--geometry", action="store_true")
    args = parser.parse_args()
    if args.catchment <= 0 or args.repeats < 1:
        parser.error("catchment ID and repeats must be positive")
    if args.report.exists():
        raise FileExistsError(args.report)
    for root in [args.source, *([] if args.bundle.startswith(("http://", "https://")) else [Path(args.bundle)])]:
        if args.report.resolve().is_relative_to(root.resolve()):
            raise ValueError("report must be outside input bundles")
    workloads = json.loads(args.workloads.read_text())
    if workloads["manifest_sha256"] != hashlib.sha256((args.source / "manifest.json").read_bytes()).hexdigest():
        raise ValueError("workload source manifest differs")
    relation = {"local_river_ids": "local_catchment_id", "component_river_ids": "component_catchment_id"}[
        args.association
    ]
    oracle = next(
        (
            row
            for row in json.loads(args.oracles.read_text())["relationship_operations"]
            if row["relation"] == relation and row["target_id"] == args.catchment
        ),
        None,
    )
    if oracle is None:
        parser.error("catchment/association requires an independent archived source oracle")
    result = measure(
        args.bundle,
        args.source,
        args.catchment,
        args.association,
        workloads["rivers_graph"]["windows"][args.window],
        oracle,
        args.repeats,
        args.geometry,
    )
    result.update(
        {
            "bundle": args.bundle,
            "window": args.window,
            "versions": {
                "python": platform.python_version(),
                "pyarrow": pa.__version__,
                "numpy": np.__version__,
                "shapely": result["shapely_version"],
            },
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "record_probe_sha256": hashlib.sha256(Path(__file__).with_name("record_probe.py").read_bytes()).hexdigest(),
            "workloads_sha256": hashlib.sha256(args.workloads.read_bytes()).hexdigest(),
            "oracles_sha256": hashlib.sha256(args.oracles.read_bytes()).hexdigest(),
        }
    )
    with args.report.open("x") as output:
        output.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
