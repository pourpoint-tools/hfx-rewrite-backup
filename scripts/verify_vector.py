"""Independently verify every source row and released HFX 0.4.0 vector artifact.

Only int64 IDs and block offsets persist across bounded record-batch reads.
This is an offline publication check, not a consumer startup operation.
"""

from __future__ import annotations

import argparse
import json
import struct
from array import array
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from hfx.verify_candidates import _fingerprint, _require


def _field(data: bytes, table: int, slot: int) -> int:
    """Locate an optional FlatBuffer table field; zero means its default value."""
    vtable = table - struct.unpack_from("<i", data, table)[0]
    size = struct.unpack_from("<H", data, vtable)[0]
    position = 4 + slot * 2
    offset = struct.unpack_from("<H", data, vtable + position)[0] if position < size else 0
    return table + offset if offset else 0


def _indirect(data: bytes, position: int) -> int:
    return position + struct.unpack_from("<I", data, position)[0]


def _ipc_compression(path: Path, *, compressed: bool) -> None:
    """Inspect IPC metadata at footer block offsets without reading batch bodies.

    Field slots follow Arrow format/File.fbs and Message.fbs: Footer dictionary
    and record-batch Block vectors, Message.header, RecordBatch.compression, and
    BodyCompression's codec (LZ4_FRAME=0, ZSTD=1) and method (BUFFER=0).
    PyArrow exposes decoded batches, but not their physical compression metadata.
    """
    with path.open("rb") as stream:
        stream.seek(-10, 2)
        trailer = stream.read(10)
        _require(trailer[4:] == b"ARROW1", "invalid IPC file trailer")
        footer_size = struct.unpack_from("<I", trailer)[0]
        footer_start = stream.tell() - 10 - footer_size
        _require(footer_start >= 8, "invalid IPC footer size")
        stream.seek(footer_start)
        footer = stream.read(footer_size)
        root = _indirect(footer, 0)
        for slot in (2, 3):  # dictionary batches and record batches
            field = _field(footer, root, slot)
            if not field:
                continue
            vector = _indirect(footer, field)
            count = struct.unpack_from("<I", footer, vector)[0]
            for number in range(count):
                # Block is a 24-byte struct: offset:int64, metadataLength:int32,
                # four padding bytes, bodyLength:int64.
                offset, metadata_size = struct.unpack_from("<qi", footer, vector + 4 + number * 24)
                _require(
                    8 <= offset < footer_start and 0 < metadata_size <= footer_start - offset,
                    "invalid IPC block metadata bounds",
                )
                stream.seek(offset)
                prefix = stream.read(4)
                if prefix == b"\xff\xff\xff\xff":
                    prefix = stream.read(4)
                size = struct.unpack("<I", prefix)[0]
                _require(0 < size <= metadata_size - (stream.tell() - offset), "invalid IPC message metadata size")
                metadata = stream.read(size)
                message = _indirect(metadata, 0)
                header = _field(metadata, message, 2)
                _require(header != 0, "missing IPC batch header")
                batch = _indirect(metadata, header)
                if slot == 2:
                    batch = _indirect(metadata, _field(metadata, batch, 1))
                compression = _field(metadata, batch, 3)
                if not compressed:
                    _require(compression == 0, "lookup compression must be absent")
                    continue
                _require(compression != 0, "catchment compression must be Zstandard")
                settings = _indirect(metadata, compression)
                codec = _field(metadata, settings, 0)
                method = _field(metadata, settings, 1)
                _require(
                    codec != 0 and metadata[codec] == 1 and (not method or metadata[method] == 0),
                    "catchment compression must be Zstandard BUFFER",
                )


def _catchments(source: pq.ParquetFile, output: Path) -> tuple[array[int], list[int]]:
    _require(source.schema_arrow.field("id").type == pa.int64(), "source IDs must have int64 type")
    _ipc_compression(output, compressed=True)
    ids: array[int] = array("q")
    offsets = [0]
    incoming = iter(source.iter_batches(batch_size=4096))
    current = next(incoming, None)
    start = 0
    with pa.memory_map(str(output), "r") as mapped:
        reader = ipc.open_file(mapped)
        _require(reader.schema.equals(source.schema_arrow, check_metadata=True), "catchment schema differs from source")
        for number in range(reader.num_record_batches):
            batch = reader.get_batch(number)
            size = batch.num_rows
            _require(size > 0, "empty catchment batch")
            _require(current is not None, "catchments have extra rows")
            assert current is not None
            remaining = current.num_rows - start
            _require(size <= remaining, "catchment batch crosses source 4096-row boundary")
            expected = current.slice(start, size)
            _require(batch.equals(expected, check_metadata=True), "catchment values differ from source")
            # Evaluate the source slices, not potentially different IPC buffer layouts.
            _require(expected.nbytes <= 8388608 or size == 1, "catchment batch exceeds byte budget")
            if size < remaining:
                _require(current.slice(start, size + 1).nbytes > 8388608, "catchment batch is not maximal")
            values = expected.column(expected.schema.get_field_index("id")).to_pylist()
            _require(
                all(isinstance(value, int) and value > 0 for value in values),
                "source IDs must be positive non-null integers",
            )
            ids.extend(cast(list[int], values))
            offsets.append(offsets[-1] + size)
            start += size
            if start == current.num_rows:
                current = next(incoming, None)
                start = 0
        _require(current is None, "catchments are missing source rows")
    _require(len(ids) == source.metadata.num_rows and len(ids) > 0, "source row count differs or is empty")
    return ids, offsets


def _index(output: Path, data_hash: str, ids: array[int], offsets: list[int]) -> tuple[int, int]:
    schema = pa.schema(
        [
            pa.field("id", pa.int64(), nullable=False),
            pa.field("block", pa.int32(), nullable=False),
            pa.field("row", pa.int32(), nullable=False),
        ],
        metadata={b"hfx:format_version": b"0.4.0", b"hfx:catchments_sha256": data_hash.encode()},
    )
    _ipc_compression(output / "lookup.arrow", compressed=False)
    directory: list[dict[str, int]] = []
    count, previous = 0, 0
    with pa.memory_map(str(output / "lookup.arrow"), "r") as mapped:
        reader = ipc.open_file(mapped)
        _require(reader.schema.equals(schema, check_metadata=True), "lookup schema or catchment binding differs")
        for number in range(reader.num_record_batches):
            batch = reader.get_batch(number)
            _require(batch.num_rows == min(65536, len(ids) - count), "lookup batch size differs")
            _require(batch.num_rows > 0, "empty lookup batch")
            columns = [column.to_pylist() for column in batch.columns]
            for identifier, block, row in zip(*columns, strict=True):
                _require(
                    isinstance(identifier, int) and identifier > previous, "lookup IDs must be positive unique sorted"
                )
                _require(isinstance(block, int) and 0 <= block < len(offsets) - 1, "lookup block out of bounds")
                _require(
                    isinstance(row, int) and 0 <= row < offsets[block + 1] - offsets[block], "lookup row out of bounds"
                )
                _require(ids[offsets[block] + row] == identifier, "lookup address points to wrong ID")
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
    _require(count == len(ids), "lookup does not cover every source row")
    _require(
        json.loads((output / "lookup-directory.json").read_text()) == {"version": 1, "batches": directory},
        "directory differs from complete lookup",
    )
    return count, len(directory)


def verify(source: Path, output: Path, report: Path) -> dict[str, object]:
    """Write a new external receipt only after independent full verification passes."""
    source, output, report = source.resolve(), output.resolve(), report.resolve()
    _require(
        not source.is_relative_to(output) and not output.is_relative_to(source), "source and output must be disjoint"
    )
    _require(
        not any(report.is_relative_to(root) for root in (source, output)), "report must be outside source and output"
    )
    if report.exists():
        raise FileExistsError(report)
    original = cast(dict[str, object], json.loads((source / "manifest.json").read_text()))
    manifest = cast(dict[str, object], json.loads((output / "manifest.json").read_text()))
    _require(original.get("format_version") == "0.3.0", "expected HFX 0.3.0 source")
    auxiliary = cast(list[dict[str, object]], original.get("auxiliary", []))
    _require(
        all(item.get("schema") in {"hfx.aux.snap.v2", "hfx.aux.d8_raster.v2"} for item in auxiliary),
        "unsupported source auxiliary schema",
    )
    snaps = [item for item in auxiliary if item["schema"] == "hfx.aux.snap.v2"]
    vectors = {"graph.parquet"} | {name for item in snaps for name in cast(dict[str, str], item["artifacts"]).values()}
    copies = {name: name for name in vectors}
    copies["manifest.json"] = "source-manifest.json"
    for name in ("NOTICE", "CITATION.txt", "README.md"):
        if (source / name).exists():
            copies[name] = "source-README.md" if name == "README.md" else name
    names = set(copies) | {"catchments.parquet"}
    for name in names:
        path = source / name
        _require(
            not Path(name).is_absolute() and ".." not in Path(name).parts and path.resolve().is_relative_to(source),
            "unsafe source artifact path",
        )
        _require(path.is_file() and not path.is_symlink(), "missing or symlinked source artifact")
    print("Hashing source and output artifacts", flush=True)
    baseline = {name: _fingerprint(source / name) for name in sorted(names)}
    paths = list(output.rglob("*"))
    _require(not any(path.is_symlink() for path in paths), "output contains symlinks")
    actual = {
        path.relative_to(output).as_posix(): _fingerprint(path)
        for path in paths
        if path.is_file() and path != output / "manifest.json"
    }
    _require(actual == manifest.get("artifacts"), "artifact fingerprints or coverage differ")
    expected_names = set(copies.values()) | {"catchments.arrow", "lookup.arrow", "lookup-directory.json", "README.md"}
    _require(set(actual) == expected_names, "unexpected or missing artifacts")
    for name, target in copies.items():
        _require(actual.get(target) == baseline[name], f"copied source artifact differs: {target}")
    expected = dict(original)
    expected.update(
        {
            "format_version": "0.4.0",
            "auxiliary": snaps,
            "graph": "graph.parquet",
            "catchments": "catchments.arrow",
            "lookup": "lookup.arrow",
            "directory": "lookup-directory.json",
            "source_manifest": "source-manifest.json",
            "index_batch_rows": 65536,
            "catchment_batch_bytes": 8388608,
            "artifacts": actual,
        }
    )
    _require(manifest == expected, "released manifest differs from preserved source metadata and vector declarations")
    parquet = pq.ParquetFile(source / "catchments.parquet")
    _require(
        type(original.get("unit_count")) is int and original["unit_count"] == parquet.metadata.num_rows,
        "source unit count differs",
    )
    print(f"Comparing all {parquet.metadata.num_rows} source rows and lookup addresses", flush=True)
    ids, offsets = _catchments(parquet, output / "catchments.arrow")
    count, batches = _index(output, actual["catchments.arrow"]["sha256"], ids, offsets)
    _require({name: _fingerprint(source / name) for name in names} == baseline, "source changed during verification")
    receipt: dict[str, object] = {
        "status": "passed",
        "source": str(source),
        "output": str(output),
        "source_rows": len(ids),
        "source_artifacts": baseline,
        "artifacts": actual,
        "manifest": _fingerprint(output / "manifest.json"),
        "verified_index_rows": count,
        "index_batches": batches,
        "data_blocks": len(offsets) - 1,
        "total_bytes": sum(item["size_bytes"] for item in actual.values()) + (output / "manifest.json").stat().st_size,
        "checks": [
            "full artifact hashes and exact coverage",
            "copied source bytes and preserved vector metadata",
            "all source schema, rows, nulls and exact WKB",
            "maximal byte-budget batches and source boundaries",
            "all lookup IDs, addresses and directory ranges",
            "Zstandard catchment and uncompressed lookup IPC metadata",
            "source unchanged during verification",
        ],
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("x") as stream:
        stream.write(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.source, args.output, args.report), indent=2))


if __name__ == "__main__":
    main()
