"""Lossless same-batch GeoParquet feasibility probe, not a supported converter."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from experiments.data_interface.build import peak_rss
from hfx.candidates import fingerprint

BBOX_LEAVES = [f"bbox.{name}" for name in ("xmin", "ymin", "xmax", "ymax")]
GEO = {
    "version": "1.1.0",
    "primary_column": "geometry",
    "columns": {
        "geometry": {
            "encoding": "WKB",
            "geometry_types": [],
            # HFX EPSG:4326 WKB coordinates are longitude/latitude; omitted CRS
            # means OGC:CRS84 (the same WGS84 coordinates in that axis order).
            "covering": {"bbox": {name: ["bbox", name] for name in ("xmin", "ymin", "xmax", "ymax")}},
        }
    },
}


def exact_array(left: pa.Array, right: pa.Array) -> bool:
    """Compare native values and valid float bits, ignoring undefined null storage."""
    if left.type != right.type or not left.is_valid().equals(right.is_valid()):
        return False
    if pa.types.is_struct(left.type):
        left_struct = cast(pa.StructArray, pc.filter(left, left.is_valid()))
        right_struct = cast(pa.StructArray, pc.filter(right, right.is_valid()))
        return all(exact_array(left_struct.field(i), right_struct.field(i)) for i in range(left.type.num_fields))
    if pa.types.is_floating(left.type):
        unsigned = {16: pa.uint16(), 32: pa.uint32(), 64: pa.uint64()}[left.type.bit_width]
        return pc.filter(left.view(unsigned), left.is_valid()).equals(pc.filter(right.view(unsigned), right.is_valid()))
    return left.equals(right)


def input_binding(source: Path) -> dict[str, Any]:
    manifest_path = source.parent / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    identity = fingerprint(source)
    if identity != manifest["artifacts"][source.name]:
        raise ValueError("source artifact binding differs")
    return {
        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "source_artifact": source.name,
        "source_artifact_sha256": identity["sha256"],
    }


def geo_schema(schema: pa.Schema) -> pa.Schema:
    if b"geo" in (schema.metadata or {}):
        raise ValueError("source already has geo metadata")
    if schema.field("geometry").type != pa.binary():
        raise ValueError("probe requires original binary WKB")
    bbox = schema.field("bbox")
    expected = pa.struct([pa.field(n, pa.float32(), False) for n in ("xmin", "ymin", "xmax", "ymax")])
    if bbox.nullable or bbox.type != expected:
        raise ValueError("probe requires native nonnull float32 bbox")
    return schema.with_metadata({**(schema.metadata or {}), b"geo": json.dumps(GEO).encode()})


def wkb_type(value: bytes) -> int:
    """Census top-level ISO WKB 2D/Z types without decoding or changing geometry."""
    if len(value) < 5 or value[0] not in (0, 1):
        raise ValueError("invalid WKB header")
    code = struct.unpack_from("<I" if value[0] == 1 else ">I", value, 1)[0]
    if code not in (*range(1, 8), *range(1001, 1008)):
        raise ValueError(f"unsupported GeoParquet 1.1 WKB type/dimension {code}")
    return code


def write_geoparquet(source: Path, output: Path) -> dict[str, Any]:
    if output.resolve().is_relative_to(source.parent.resolve()):
        raise ValueError("output must be outside source bundle")
    if output.exists():
        raise FileExistsError(output)
    started = perf_counter()
    binding = input_binding(source)
    rows: list[int] = []
    types: Counter[int] = Counter()
    with pa.memory_map(str(source), "r") as stream:
        reader = ipc.open_file(stream)
        schema = geo_schema(reader.schema)
        # No dictionary or statistics for WKB. ZSTD level None is Arrow's default.
        # Only bbox statistics are useful to this controlled spatial comparison.
        with (
            output.open("xb") as destination,
            pq.ParquetWriter(
                destination,
                schema,
                compression="zstd",
                compression_level=None,
                use_dictionary=False,
                write_statistics=BBOX_LEAVES,
                store_schema=True,
            ) as writer,
        ):
            for index in range(reader.num_record_batches):
                batch = reader.get_batch(index)
                rows.append(batch.num_rows)
                for value in batch.column("geometry"):
                    if not value.is_valid:
                        raise ValueError("unexpected null WKB")
                    types[wkb_type(value.as_py())] += 1
                writer.write_batch(batch.replace_schema_metadata(schema.metadata), row_group_size=batch.num_rows)
    return {
        **binding,
        "artifact": fingerprint(output),
        "row_group_rows": rows,
        "top_level_wkb_type_counts": dict(sorted(types.items())),
        "writer": {
            "compression": "zstd",
            "compression_level": "pyarrow default",
            "use_dictionary": False,
            "write_statistics": BBOX_LEAVES,
            "store_schema": True,
            "pyarrow": pa.__version__,
        },
        "elapsed_including_fingerprints_s": perf_counter() - started,
        "process_lifetime_peak_rss_bytes": peak_rss(),
    }


def verify_geoparquet(source: Path, output: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    started = perf_counter()
    binding = input_binding(source)
    if any(receipt.get(key) != value for key, value in binding.items()):
        raise ValueError("source binding differs")
    if fingerprint(output) != receipt["artifact"]:
        raise ValueError("output artifact differs")
    with pa.memory_map(str(source), "r") as stream, pq.ParquetFile(output) as parquet:
        reader = ipc.open_file(stream)
        expected_schema = geo_schema(reader.schema)
        if not expected_schema.equals(parquet.schema_arrow, check_metadata=True):
            raise ValueError("schema or metadata differs")
        if json.loads((parquet.metadata.metadata or {})[b"geo"]) != GEO:
            raise ValueError("GeoParquet metadata differs")
        if reader.num_record_batches != parquet.num_row_groups:
            raise ValueError("row group count differs")
        rows: list[int] = []
        types: Counter[int] = Counter()
        for index in range(reader.num_record_batches):
            original = reader.get_batch(index)
            group = parquet.read_row_group(index).combine_chunks()
            rows.append(original.num_rows)
            for value in original.column("geometry"):
                if not value.is_valid:
                    raise ValueError("unexpected null WKB")
                types[wkb_type(value.as_py())] += 1
            if original.num_rows != parquet.metadata.row_group(index).num_rows or original.num_rows != group.num_rows:
                raise ValueError(f"row group {index} boundary differs")
            for field in reader.schema:
                if not exact_array(original.column(field.name), cast(pa.Array, group.column(field.name).chunk(0))):
                    raise ValueError(f"row group {index} column {field.name} differs")
            for column_index in range(parquet.metadata.num_columns):
                column = parquet.metadata.row_group(index).column(column_index)
                if column.compression != "ZSTD" or "RLE_DICTIONARY" in column.encodings:
                    raise ValueError("column encoding differs")
                if column.is_stats_set != (column.path_in_schema in BBOX_LEAVES):
                    raise ValueError("column statistics differ")
        if rows != receipt["row_group_rows"]:
            raise ValueError("boundary receipt differs")
        if {int(key): value for key, value in receipt["top_level_wkb_type_counts"].items()} != dict(types):
            raise ValueError("WKB type census differs")
        return {
            "status": "passed",
            "rows": sum(rows),
            "row_group_rows": rows,
            "footer_bytes": parquet.metadata.serialized_size,
            "leaf_columns": parquet.metadata.num_columns,
            "elapsed_including_fingerprints_s": perf_counter() - started,
            "process_lifetime_peak_rss_bytes": peak_rss(),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists():
        raise FileExistsError(args.receipt)
    if args.receipt.resolve().is_relative_to(args.source.parent.resolve()):
        raise ValueError("receipt must be outside source bundle")
    receipt = write_geoparquet(args.source, args.output)
    # Preserve producer evidence even if independent output verification rejects.
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    result = verify_geoparquet(args.source, args.output, receipt)
    args.receipt.write_text(json.dumps({"build": receipt, "verification": result}, indent=2) + "\n")


if __name__ == "__main__":
    main()
