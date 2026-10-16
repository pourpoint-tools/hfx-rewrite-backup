"""Explicit expensive producer verification, not ordinary consumer opening."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any

import pyarrow as pa

from experiments.data_interface.build import FAMILIES, peak_rss
from experiments.data_interface.features import verify_features
from experiments.data_interface.relationships import verify_relationships
from hfx.candidates import fingerprint


def verify_source_claims(source: Path, manifest: dict[str, Any], source_manifest: dict[str, Any]) -> None:
    remap = {FAMILIES[family]: declaration["data"] for family, declaration in manifest["families"].items()}
    expected_categories = [
        {**entry, "artifact": remap[entry["artifact"]]}
        for entry in source_manifest.get("categorical_columns", [])
        if entry["artifact"] in remap
    ]
    if manifest["categorical_columns"] != expected_categories:
        raise ValueError("categorical source meanings differ")
    expected_schemas = {}
    for family in manifest["families"]:
        with pa.OSFile(str(source / FAMILIES[family]), "rb") as stream:
            schema = pa.ipc.open_file(stream).schema
        expected_schemas[family] = {
            "artifact": FAMILIES[family],
            "arrow_schema_sha256": hashlib.sha256(schema.serialize().to_pybytes()).hexdigest(),
        }
    if manifest["source_schemas"] != expected_schemas:
        raise ValueError("source schema declarations differ")


def verify(source: Path, output: Path) -> dict[str, Any]:
    started = perf_counter()
    manifest = json.loads((output / "manifest.json").read_bytes())
    if hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest() != manifest["input_manifest_sha256"]:
        raise ValueError("input manifest differs")
    source_manifest = json.loads((source / "manifest.json").read_bytes())
    if manifest["input_artifacts"] != source_manifest["artifacts"]:
        raise ValueError("source artifact declarations differ")
    verify_source_claims(source, manifest, source_manifest)
    needed = {FAMILIES[family] for family in manifest["families"]}
    if manifest["relationships"]:
        needed.update([*FAMILIES.values(), "graph.parquet", "river-graph.parquet"])
    for name in needed:
        if fingerprint(source / name) != source_manifest["artifacts"][name]:
            raise ValueError(f"source artifact differs: {name}")
    for name, identity in manifest["artifacts"].items():
        if fingerprint(output / name) != identity:
            raise ValueError(f"derived artifact differs: {name}")
    for family, declaration in manifest["families"].items():
        verify_features(source / FAMILIES[family], output, declaration)
    relationships = verify_relationships(source, output, manifest["relationships"]) if manifest["relationships"] else {}
    return {
        "status": "passed",
        "elapsed_s": perf_counter() - started,
        "relationships": relationships,
        "process_peak_rss_bytes": peak_rss(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    if any(args.report.resolve().is_relative_to(root.resolve()) for root in (args.source, args.candidate)):
        raise ValueError("report must be outside source and candidate bundles")
    result = verify(args.source, args.candidate)
    with args.report.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
