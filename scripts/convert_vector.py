"""Convert a downloaded HFX 0.3.0 vector source into a new immutable 0.4.0 bundle."""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.parquet as pq

from hfx.candidates import fingerprint, write_catchments, write_index, write_json


def convert(source: Path, output: Path) -> None:
    """Stream catchments; hardlink unchanged vectors on the same filesystem."""
    source, output = source.resolve(), output.resolve()
    if source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError("source and output must be disjoint")
    if output.exists():
        raise FileExistsError(output)
    manifest = cast(dict[str, object], json.loads((source / "manifest.json").read_text()))
    if manifest["format_version"] != "0.3.0":
        raise ValueError("expected HFX 0.3.0 source")
    auxiliary = cast(list[dict[str, object]], manifest.get("auxiliary", []))
    if any(item["schema"] not in {"hfx.aux.snap.v2", "hfx.aux.d8_raster.v2"} for item in auxiliary):
        raise ValueError("unsupported source auxiliary schema")
    snaps = [item for item in auxiliary if item["schema"] == "hfx.aux.snap.v2"]
    vectors = {"graph.parquet"} | {name for item in snaps for name in cast(dict[str, str], item["artifacts"]).values()}
    copies = {"manifest.json": "source-manifest.json"}
    for name in ("NOTICE", "CITATION.txt", "README.md"):
        if (source / name).exists():
            copies[name] = "source-README.md" if name == "README.md" else name
    names = vectors | set(copies) | {"catchments.parquet"}
    for name in names:
        path = source / name
        if Path(name).is_absolute() or ".." in Path(name).parts or not path.resolve().is_relative_to(source):
            raise ValueError("unsafe source artifact path")
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"source artifact is missing or symlinked: {name}")
    print("Hashing source vectors", flush=True)
    before = {name: fingerprint(source / name) for name in sorted(names)}
    parquet = pq.ParquetFile(source / "catchments.parquet")
    if parquet.metadata.num_rows != manifest["unit_count"]:
        raise ValueError("source unit count differs")
    if parquet.schema_arrow.field("id").type != pa.int64():
        raise ValueError("source IDs must be int64")
    output.mkdir(parents=True)
    for name in sorted(vectors):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(source / name, target)
    for name, target_name in copies.items():
        shutil.copyfile(source / name, output / target_name)
    print(
        f"Converting {parquet.metadata.num_rows} catchments; free bytes: {shutil.disk_usage(output).free}", flush=True
    )
    blocks = write_catchments(parquet, output / "catchments.arrow", 8388608)
    data_identity = fingerprint(output / "catchments.arrow")
    directory = write_index(output / "lookup.arrow", blocks, data_identity["sha256"], "", 65536, format_version="0.4.0")
    write_json(output / "lookup-directory.json", directory)
    (output / "README.md").write_text(
        "# HFX 0.4.0 vector bundle\n\n"
        "Catchments were converted from HFX 0.3.0 Parquet to Zstandard-compressed "
        "Arrow IPC batches with an ID-sorted lookup and range directory. "
        "IDs, attributes, nulls, schema metadata and exact WKB are preserved. "
        "Graph and snap files retain their source bytes.\n\n"
        "The manifest describes the delivered vector artifacts. source-manifest.json "
        "and source-README.md document the source publication, including its raster "
        "declarations and historical publication instructions.\n\n"
        "Source attribution and license terms are retained in NOTICE and CITATION.txt. "
        "For GRIT, the derivative remains CC BY-NC 4.0: "
        "https://creativecommons.org/licenses/by-nc/4.0/. Credit Wortmann et al. "
        "(2025), Global River Topology vector datasets, doi:10.5281/zenodo.17435232.\n\n"
        "GRIT upstream areas use partitioned drainage area at DAG bifurcations. "
        "Watershed accumulation uses the graph and level-1 reaches; summing upstream "
        "area values across a flow set does not give watershed area. The source "
        "documents 44 reaches with null up_area_km2. These values are preserved.\n"
    )
    artifacts = {
        path.relative_to(output).as_posix(): data_identity if path.name == "catchments.arrow" else fingerprint(path)
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    after = {name: fingerprint(source / name) for name in sorted(names)}
    if before != after:
        raise ValueError("source changed during conversion; discard output")
    manifest.update(
        {
            "format_version": "0.4.0",
            "auxiliary": snaps,
            "source_manifest": "source-manifest.json",
            "graph": "graph.parquet",
            "catchments": "catchments.arrow",
            "lookup": "lookup.arrow",
            "directory": "lookup-directory.json",
            "index_batch_rows": 65536,
            "catchment_batch_bytes": 8388608,
            "artifacts": artifacts,
        }
    )
    write_json(output / "manifest.json", manifest)
    print(
        f"Produced {len(blocks)} batches, {sum(item['size_bytes'] for item in artifacts.values())} artifact bytes; free bytes: {shutil.disk_usage(output).free}. Run independent verification before upload.",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    convert(args.source, args.output)


if __name__ == "__main__":
    main()
