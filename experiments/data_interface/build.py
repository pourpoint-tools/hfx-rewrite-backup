"""Build one immutable experimental bundle; bulk outputs stay outside Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import shutil
from pathlib import Path
from time import perf_counter
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa

from experiments.data_interface.features import build_features
from hfx.candidates import fingerprint

FAMILIES = {"catchments": "catchments.arrow", "rivers": "rivers.arrow", "river_nodes": "river-nodes.arrow"}


def peak_rss() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if platform.system() == "Darwin" else value * 1024)


def build(
    source: Path,
    output: Path,
    *,
    rows: int = 8192,
    budget: int = 8388608,
    families: list[str] | None = None,
    relationships: bool = True,
) -> dict[str, Any]:
    from experiments.data_interface.relationships import build_relationships

    started = perf_counter()
    output.mkdir(parents=True, exist_ok=False)
    original_bytes = (source / "manifest.json").read_bytes()
    if hashlib.sha256(original_bytes).hexdigest() != "b9a38083131dcf1a4c7c4e73ebe9a97dff2a4b7ef91a8df53f8bc38cadfa48db":
        raise ValueError("input is not pinned verified GRIT publication")
    original = json.loads(original_bytes)
    verification_started = perf_counter()
    # Full source verification belongs to producer build, not ordinary reader open.
    chosen = families or list(FAMILIES)
    needed = {FAMILIES[family] for family in chosen}
    if relationships:
        needed.update([*FAMILIES.values(), "graph.parquet", "river-graph.parquet"])
    for name in sorted(needed):
        if fingerprint(source / name) != original["artifacts"][name]:
            raise ValueError(f"source fingerprint differs: {name}")
    source_verification_s = perf_counter() - verification_started
    declarations = {}
    phases = []
    for family in chosen:
        phase = perf_counter()
        declarations[family] = build_features(source / FAMILIES[family], output, family, rows=rows, budget=budget)
        phases.append({"family": family, "elapsed_s": perf_counter() - phase, "process_peak_rss_bytes": peak_rss()})
        print(json.dumps(phases[-1]), flush=True)
    phase = perf_counter()
    adjacency = build_relationships(source, output, batch_rows=rows) if relationships else {}
    relationships_s = perf_counter() - phase
    for name in (
        "source-provenance.json",
        "NOTICE",
        "CITATION.txt",
        "README.md",
        "GRIT-original-LICENSE.md",
        "GRIT-original-README.pdf",
    ):
        if fingerprint(source / name) != original["artifacts"][name]:
            raise ValueError(f"source provenance fingerprint differs: {name}")
        shutil.copyfile(source / name, output / name)
    derived = {path.name: fingerprint(path) for path in sorted(output.iterdir()) if path.is_file()}
    remap = {FAMILIES[family]: declaration["data"] for family, declaration in declarations.items()}
    categories = [
        {**entry, "artifact": remap[entry["artifact"]]}
        for entry in original.get("categorical_columns", [])
        if entry["artifact"] in remap
    ]
    source_schema = {}
    for family in chosen:
        reader = pa.ipc.open_file(str(source / FAMILIES[family]))
        source_schema[family] = {
            "artifact": FAMILIES[family],
            "arrow_schema_sha256": hashlib.sha256(reader.schema.serialize().to_pybytes()).hexdigest(),
        }
    manifest: dict[str, Any] = {
        "experimental": True,
        "representation": "spatial-ipc-adjacency",
        "representation_version": 1,
        "input_manifest_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "input_artifacts": original["artifacts"],
        "families": declarations,
        "relationships": adjacency,
        "source_schemas": source_schema,
        "categorical_columns": categories,
        "catchment_connectivity": original.get("catchment_connectivity", []),
        "provenance": {
            "source_manifest": "source-manifest.json",
            "license": "GRIT CC BY-NC 4.0; retain original publication attribution/provenance",
        },
        "constants": {
            "feature_rows": rows,
            "feature_logical_bytes": budget,
            "morton_axis_bits": 16,
            "lookup_rows": 65536,
            "duckdb_memory_limit": "8GB",
            "duckdb_threads": 1,
            "duckdb_preserve_insertion_order": False,
            "feature_compression": "zstd",
            "relationship_compression": "none",
        },
        "versions": {
            "python": platform.python_version(),
            "pyarrow": pa.__version__,
            "numpy": np.__version__,
            "duckdb": duckdb.__version__,
        },
        "artifacts": derived,
    }
    (output / "source-manifest.json").write_bytes(original_bytes)
    manifest["artifacts"]["source-manifest.json"] = fingerprint(output / "source-manifest.json")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    report = {
        "source_verification_s": source_verification_s,
        "features": phases,
        "relationships_s": relationships_s,
        "elapsed_s": perf_counter() - started,
        "process_peak_rss_bytes": peak_rss(),
        "publication_bytes": sum(p.stat().st_size for p in output.iterdir() if p.is_file()),
        "manifest_sha256": hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest(),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--rows", type=int, default=8192)
    parser.add_argument("--budget", type=int, default=8388608)
    parser.add_argument("--family", choices=list(FAMILIES), action="append")
    parser.add_argument("--no-relationships", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    if any(args.report.resolve().is_relative_to(root.resolve()) for root in (args.source, args.output)):
        raise ValueError("report must be outside source and candidate bundles")
    report = build(
        args.source,
        args.output,
        rows=args.rows,
        budget=args.budget,
        families=args.family,
        relationships=not args.no_relationships,
    )
    with args.report.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
