"""Full offline verification of experimental candidates; not a reader API.

Data comparisons stream in source order. Only int64 identifiers and block offsets
remain in memory. Receipts live outside bundles so artifact coverage stays exact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from array import array
from pathlib import Path
from typing import TypedDict, cast

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq


class Fingerprint(TypedDict):
    size_bytes: int
    sha256: str
    head_sha256: str
    tail_sha256: str


class Manifest(TypedDict):
    format_version: str
    experimental: bool
    candidate: str
    source_manifest: str
    catchments: str
    lookup: str
    directory: str
    index_batch_rows: int
    catchment_batch_bytes: int
    artifacts: dict[str, Fingerprint]


class CandidateReceipt(TypedDict):
    path: str
    verified_index_rows: int
    index_batches: int
    data_blocks: int
    total_bytes: int
    manifest: Fingerprint


class Receipt(TypedDict):
    status: str
    source_rows: int
    source: str
    source_artifacts: dict[str, Fingerprint]
    candidates: dict[str, CandidateReceipt]
    checks: list[str]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _fingerprint(path: Path) -> Fingerprint:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
        size = stream.tell()
        stream.seek(0)
        head = stream.read(65536)
        stream.seek(max(0, size - 65536))
        tail = stream.read(65536)
    return {
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "head_sha256": hashlib.sha256(head).hexdigest(),
        "tail_sha256": hashlib.sha256(tail).hexdigest(),
    }


def _files(root: Path) -> dict[str, Path]:
    return {path.relative_to(root).as_posix(): path for path in root.rglob("*") if path.is_file()}


def _bundle(root: Path, source: dict[str, Fingerprint], candidate: str) -> Manifest:
    manifest = cast(Manifest, json.loads((root / "manifest.json").read_text()))
    expected = {
        "format_version": "0.4.0",
        "experimental": True,
        "candidate": candidate,
        "source_manifest": "source-manifest.json",
        "lookup": "lookup.arrow",
        "directory": "lookup-directory.json",
        "catchments": "catchments.parquet" if candidate == "a-index" else "catchments.arrow",
    }
    for key, value in expected.items():
        _require(manifest.get(key) == value, f"{root}: invalid manifest {key}")
    files = _files(root)
    actual = {name: _fingerprint(path) for name, path in files.items() if name != "manifest.json"}
    _require(actual == manifest.get("artifacts"), f"{root}: artifact fingerprints or coverage differ")
    copied = {
        "source-manifest.json" if name == "manifest.json" else name: fingerprint
        for name, fingerprint in source.items()
        if candidate == "a-index" or name != "catchments.parquet"
    }
    for name, fingerprint in copied.items():
        _require(actual.get(name) == fingerprint, f"{root}: copied artifact differs: {name}")
    expected_names = set(copied) | {"lookup.arrow", "lookup-directory.json", manifest["catchments"]}
    _require(set(actual) == expected_names, f"{root}: unexpected artifacts")
    return manifest


def _index(root: Path, manifest: Manifest, ids: array[int], offsets: list[int]) -> tuple[int, int]:
    schema = pa.schema(
        [
            pa.field("id", pa.int64(), nullable=False),
            pa.field("block", pa.int32(), nullable=False),
            pa.field("row", pa.int32(), nullable=False),
        ],
        metadata={
            b"hfx:catchments_sha256": manifest["artifacts"][manifest["catchments"]]["sha256"].encode(),
            b"hfx:candidate": manifest["candidate"].encode(),
        },
    )
    directory: list[dict[str, int]] = []
    previous = 0
    count = 0
    limit = manifest["index_batch_rows"]
    _require(isinstance(limit, int) and limit > 0, "invalid index batch limit")
    with pa.memory_map(str(root / "lookup.arrow"), "r") as mapped:
        reader = ipc.open_file(mapped)
        _require(reader.schema.equals(schema, check_metadata=True), f"{root}: index schema differs")
        for number in range(reader.num_record_batches):
            batch = reader.get_batch(number)
            _require(0 < batch.num_rows <= limit, "invalid index batch size")
            columns = [column.to_pylist() for column in batch.columns]
            for identifier, block, row in zip(*columns, strict=True):
                _require(identifier is not None and identifier > previous, "index IDs not positive unique sorted")
                _require(block is not None and 0 <= block < len(offsets) - 1, "index block out of bounds")
                _require(row is not None and 0 <= row < offsets[block + 1] - offsets[block], "index row out of bounds")
                _require(ids[offsets[block] + row] == identifier, "index address points to wrong ID")
                previous = identifier
                count += 1
            directory.append(
                {
                    "batch": number,
                    "min_id": cast(int, columns[0][0]),
                    "max_id": cast(int, columns[0][-1]),
                    "rows": batch.num_rows,
                }
            )
    _require(count == len(ids), "index does not cover every source row")
    actual_directory = json.loads((root / "lookup-directory.json").read_text())
    _require(actual_directory == {"version": 1, "batches": directory}, "directory differs from complete index")
    return count, len(directory)


def verify(source: Path, a: Path, b: Path, report: Path | None = None) -> Receipt:
    """Verify all source rows, copied bytes, and every lookup address; raise on error."""
    source, a, b = source.resolve(), a.resolve(), b.resolve()
    report = report or Path(os.path.commonpath([a.parent, b.parent])) / "verification.json"
    report = report.resolve()
    _require(
        not any(report.is_relative_to(root) for root in (source, a, b)), "receipt must be outside bundles and source"
    )
    baseline = {name: _fingerprint(path) for name, path in _files(source).items()}
    am = _bundle(a, baseline, "a-index")
    bm = _bundle(b, baseline, "b-arrow")
    parquet = pq.ParquetFile(source / "catchments.parquet")
    a_offsets = [0]
    for group in range(parquet.num_row_groups):
        a_offsets.append(a_offsets[-1] + parquet.metadata.row_group(group).num_rows)
    ids: array[int] = array("q")
    b_offsets = [0]
    limit = bm["catchment_batch_bytes"]
    _require(isinstance(limit, int) and limit > 0, "invalid catchment byte limit")
    source_batches = iter(parquet.iter_batches(batch_size=4096))
    current = next(source_batches, None)
    source_offset = 0
    with pa.memory_map(str(b / "catchments.arrow"), "r") as mapped:
        reader = ipc.open_file(mapped)
        _require(reader.schema.equals(parquet.schema_arrow, check_metadata=True), "B schema differs from source")
        for number in range(reader.num_record_batches):
            batch = reader.get_batch(number)
            _require(batch.num_rows > 0, "empty B batch")
            _require(batch.nbytes <= limit or batch.num_rows == 1, "B batch exceeds byte limit")
            b_offsets.append(b_offsets[-1] + batch.num_rows)
            consumed = 0
            while consumed < batch.num_rows:
                _require(current is not None, "B has extra rows")
                assert current is not None
                size = min(current.num_rows - source_offset, batch.num_rows - consumed)
                expected = current.slice(source_offset, size)
                actual = batch.slice(consumed, size)
                _require(actual.equals(expected, check_metadata=True), "B values differ from source")
                id_values = expected.column(expected.schema.get_field_index("id")).to_pylist()
                _require(
                    all(isinstance(value, int) and value > 0 for value in id_values),
                    "source IDs must be positive integers",
                )
                ids.extend(cast(list[int], id_values))
                consumed += size
                source_offset += size
                if source_offset == current.num_rows:
                    current = next(source_batches, None)
                    source_offset = 0
        _require(current is None, "B is missing source rows")
    _require(len(ids) == parquet.metadata.num_rows, "source row count differs")
    a_count, a_batches = _index(a, am, ids, a_offsets)
    b_count, b_batches = _index(b, bm, ids, b_offsets)
    after = {name: _fingerprint(path) for name, path in _files(source).items()}
    _require(after == baseline, "source changed during verification")
    receipt: Receipt = {
        "status": "passed",
        "source_rows": len(ids),
        "source": str(source),
        "source_artifacts": baseline,
        "candidates": {
            "a-index": {
                "path": str(a),
                "verified_index_rows": a_count,
                "index_batches": a_batches,
                "data_blocks": len(a_offsets) - 1,
                "total_bytes": sum(item["size_bytes"] for item in am["artifacts"].values())
                + (a / "manifest.json").stat().st_size,
                "manifest": _fingerprint(a / "manifest.json"),
            },
            "b-arrow": {
                "path": str(b),
                "verified_index_rows": b_count,
                "index_batches": b_batches,
                "data_blocks": len(b_offsets) - 1,
                "total_bytes": sum(item["size_bytes"] for item in bm["artifacts"].values())
                + (b / "manifest.json").stat().st_size,
                "manifest": _fingerprint(b / "manifest.json"),
            },
        },
        "checks": [
            "all source and copied bytes",
            "all B schemas and ordered values",
            "all index addresses and IDs",
            "complete sorted directories",
            "source unchanged during verification",
        ],
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("a", type=Path)
    parser.add_argument("b", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.source, args.a, args.b, args.report), indent=2))


if __name__ == "__main__":
    main()
