"""Produce local experimental HFX selective-access alternatives (not a reader)."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import TypedDict

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from hfx.vector_storage import Directory, budget_batches, write_address_index


def write_index(
    path: Path,
    blocks: list[pa.Array],
    data_hash: str,
    candidate: str,
    batch_rows: int,
    *,
    format_version: str | None = None,
) -> Directory:
    """Sort physical addresses on disk, preserving the catchment lookup binding."""
    return write_address_index(
        path,
        blocks,
        {
            b"hfx:catchments_sha256": data_hash.encode(),
            **(
                {b"hfx:format_version": format_version.encode()}
                if format_version
                else {b"hfx:candidate": candidate.encode()}
            ),
        },
        batch_rows,
    )


def write_catchments(source: pq.ParquetFile, path: Path, budget: int) -> list[pa.Array]:
    """Preserve row order and exact Arrow values; bound logical bytes per IPC batch."""
    if budget <= 0:
        raise ValueError("catchment byte budget must be positive")
    blocks: list[pa.Array] = []
    with ipc.new_file(str(path), source.schema_arrow, options=ipc.IpcWriteOptions(compression="zstd")) as writer:
        for batch in budget_batches(source.iter_batches(batch_size=4096), budget):
            writer.write_batch(batch)
            # Copy IDs out of buffers retained by the incoming geometry batch.
            blocks.append(pa.array(batch.column(batch.schema.get_field_index("id")).to_pylist(), type=pa.int64()))
    return blocks


class Fingerprint(TypedDict):
    size_bytes: int
    sha256: str
    head_sha256: str
    tail_sha256: str


def fingerprint(path: Path) -> Fingerprint:
    """Full publication digest plus bounded startup mismatch checks (not integrity proof)."""
    size = path.stat().st_size
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        stream.seek(0)
        head = hashlib.sha256(stream.read(65536)).hexdigest()
        stream.seek(max(0, size - 65536))
        tail = hashlib.sha256(stream.read()).hexdigest()
    return {"size_bytes": size, "sha256": digest, "head_sha256": head, "tail_sha256": tail}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def build(
    source: Path,
    candidate_a: Path,
    candidate_b: Path,
    *,
    index_batch_rows: int = 65536,
    catchment_batch_bytes: int = 8 * 1024 * 1024,
) -> None:
    """Create two new bundles. Existing destinations and overlapping trees are refused."""
    source, candidate_a, candidate_b = source.resolve(), candidate_a.resolve(), candidate_b.resolve()
    paths = [source, candidate_a, candidate_b]
    if any(a.is_relative_to(b) for a in paths for b in paths if a != b) or len(set(paths)) != 3:
        raise ValueError("source and destinations must be disjoint")
    for destination in [candidate_a, candidate_b]:
        if destination.exists():
            raise FileExistsError(destination)
    if index_batch_rows <= 0 or catchment_batch_bytes <= 0:
        raise ValueError("batch budgets must be positive")
    originals = sorted(p for p in source.rglob("*") if p.is_file())
    if any(p.is_symlink() for p in source.rglob("*")):
        raise ValueError("source symlinks are not supported")
    reserved = {"source-manifest.json", "catchments.arrow", "lookup.arrow", "lookup-directory.json"}
    if any((source / name).exists() for name in reserved):
        raise ValueError("source contains reserved candidate artifact names")
    metadata = json.loads((source / "manifest.json").read_text())
    if metadata["format_version"] != "0.3.0":
        raise ValueError("expected a reference HFX 0.3.0 source bundle")
    before = {str(p.relative_to(source)): fingerprint(p) for p in originals}
    parquet = pq.ParquetFile(source / "catchments.parquet")
    if parquet.metadata.num_rows != metadata["unit_count"]:
        raise ValueError("source manifest unit count differs from catchments")
    if parquet.schema_arrow.field("id").type != pa.int64():
        raise ValueError("source IDs must have int64 type")
    for destination, candidate in [(candidate_a, "a-index"), (candidate_b, "b-arrow")]:
        destination.mkdir(parents=True)
        print(f"Writing {candidate}: {destination}", flush=True)
        for original in originals:
            relative = original.relative_to(source)
            if candidate == "b-arrow" and str(relative) == "catchments.parquet":
                continue
            target = destination / ("source-manifest.json" if str(relative) == "manifest.json" else relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
        if candidate == "a-index":
            data_name = "catchments.parquet"
            blocks = [
                parquet.read_row_group(i, columns=["id"])["id"].combine_chunks() for i in range(parquet.num_row_groups)
            ]
        else:
            data_name = "catchments.arrow"
            blocks = write_catchments(parquet, destination / data_name, catchment_batch_bytes)
        data_identity = fingerprint(destination / data_name)
        directory = write_index(
            destination / "lookup.arrow", blocks, data_identity["sha256"], candidate, index_batch_rows
        )
        write_json(destination / "lookup-directory.json", directory)
        artifacts = {
            str(p.relative_to(destination)): (data_identity if p.name == data_name else fingerprint(p))
            for p in sorted(destination.rglob("*"))
            if p.is_file()
        }
        write_json(
            destination / "manifest.json",
            {
                "format_version": "0.4.0",
                "experimental": True,
                "candidate": candidate,
                "source_manifest": "source-manifest.json",
                "catchments": data_name,
                "lookup": "lookup.arrow",
                "directory": "lookup-directory.json",
                "index_batch_rows": index_batch_rows,
                "catchment_batch_bytes": catchment_batch_bytes,
                "artifacts": artifacts,
            },
        )
        print(f"Completed {candidate}: {sum(len(ids) for ids in blocks)} units, {len(blocks)} data blocks", flush=True)
    after = {str(p.relative_to(source)): fingerprint(p) for p in source.rglob("*") if p.is_file()}
    if before != after:
        raise ValueError("source changed during production; do not use these candidates")
    print("Source hashes unchanged. Run independent verification before use.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("candidate_a", type=Path)
    parser.add_argument("candidate_b", type=Path)
    parser.add_argument("--index-batch-rows", type=int, default=65536)
    parser.add_argument("--catchment-batch-bytes", type=int, default=8 * 1024 * 1024)
    args = parser.parse_args()
    build(
        args.source,
        args.candidate_a,
        args.candidate_b,
        index_batch_rows=args.index_batch_rows,
        catchment_batch_bytes=args.catchment_batch_bytes,
    )


if __name__ == "__main__":
    main()
