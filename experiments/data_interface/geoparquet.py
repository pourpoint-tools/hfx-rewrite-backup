"""Lossless same-batch GeoParquet feasibility probe, not a supported converter."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from bisect import bisect_left
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any, cast
from urllib.parse import urljoin

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from experiments.data_interface.baseline_graph_spatial import conservative
from experiments.data_interface.build import peak_rss
from experiments.data_interface.probe import CountFile
from hfx.candidates import fingerprint
from scripts.check_vector_access import HTTP, Fingerprint, RangeFile

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


class GeoParquetAccess:
    """Retained experiment reader; candidate locators address unchanged groups/rows."""

    def __init__(self, artifact: str, candidate: str, binding: dict[str, Any]) -> None:
        self.http = HTTP()
        self.files: list[CountFile | RangeFile] = []
        self.pafiles: list[pa.PythonFile] = []
        self.candidate = candidate.rstrip("/") + "/"
        self.binding = binding
        manifest_bytes = (
            self.http.get(urljoin(self.candidate, "manifest.json"))
            if candidate.startswith("http")
            else (Path(candidate) / "manifest.json").read_bytes()
        )
        if hashlib.sha256(manifest_bytes).hexdigest() != binding["source_manifest_sha256"]:
            raise ValueError("candidate manifest binding differs")
        self.manifest = json.loads(manifest_bytes)
        self.declaration = self.manifest["families"]["rivers"]
        identity = self.manifest["artifacts"][self.declaration["data"]]
        if (
            identity["sha256"] != binding["source_artifact_sha256"]
            or self.declaration["data"] != binding["source_artifact"]
        ):
            raise ValueError("candidate source binding differs")
        self.reader = pq.ParquetFile(self.open(artifact, binding["artifact"]), pre_buffer=True)
        if [self.reader.metadata.row_group(i).num_rows for i in range(self.reader.num_row_groups)] != binding[
            "row_group_rows"
        ]:
            raise ValueError("locator row group mapping differs")
        self.lookup: ipc.RecordBatchFileReader | None = None
        self.directory: list[dict[str, Any]] = []
        self.last_groups: list[int] = []
        self.materialized_rows = self.materialized_bytes = self.materialized_geometry_bytes = 0
        self.discovery_groups: list[int] = []

    def open(self, location: str, identity: dict[str, Any]) -> pa.PythonFile:
        if location.startswith("http"):
            raw: CountFile | RangeFile = RangeFile(self.http, location, cast(Fingerprint, identity))
        else:
            path = Path(location)
            if path.stat().st_size != identity["size_bytes"]:
                raise ValueError("local artifact size differs")
            local = CountFile(path)
            width = min(65536, identity["size_bytes"])
            for offset, key in [(0, "head_sha256"), (identity["size_bytes"] - width, "tail_sha256")]:
                local.seek(offset)
                if hashlib.sha256(local.read(width)).hexdigest() != identity[key]:
                    raise ValueError("local bounded fingerprint differs")
            local.seek(0)
            raw = local
        self.files.append(raw)
        stream = pa.PythonFile(raw, mode="r")
        self.pafiles.append(stream)
        return stream

    def read_groups(self, groups: list[int], columns: list[str]) -> pa.Table:
        table = self.reader.read_row_groups(groups, columns=columns).select(columns)
        self.materialized_rows += table.num_rows
        self.materialized_bytes += table.nbytes
        if "geometry" in columns:
            self.materialized_geometry_bytes += table.column("geometry").nbytes
        return table

    def records(self, addresses: dict[int, list[tuple[int, int]]], columns: list[str]) -> pa.Table:
        groups = sorted(addresses)
        names = list(dict.fromkeys([*columns, "id"]))
        table = self.read_groups(groups, names)
        positions: list[int] = []
        expected_ids: list[int] = []
        offset = 0
        for group in groups:
            size = self.reader.metadata.row_group(group).num_rows
            for row, identity in addresses[group]:
                if row < 0 or row >= size:
                    raise ValueError("locator row out of bounds")
                positions.append(offset + row)
                expected_ids.append(identity)
            offset += size
        selected = table.take(pa.array(positions, type=pa.int64()))
        if selected.column("id").to_pylist() != expected_ids:
            raise ValueError("locator selected ID differs")
        self.last_groups = groups
        return selected.select(columns)

    def ids(self, requested: list[int], columns: list[str]) -> tuple[pa.Table, list[int]]:
        if any(value <= 0 for value in requested):
            raise ValueError("IDs must be positive")
        if self.lookup is None:
            name = self.declaration["lookup"]
            self.lookup = ipc.open_file(self.open(urljoin(self.candidate, name), self.manifest["artifacts"][name]))
            if (self.lookup.schema.metadata or {}).get(b"hfx:data_sha256") != self.binding[
                "source_artifact_sha256"
            ].encode():
                raise ValueError("candidate lookup binding differs")
            name = self.declaration["directory"]
            data = self.open(urljoin(self.candidate, name), self.manifest["artifacts"][name]).read()
            if hashlib.sha256(data).hexdigest() != self.manifest["artifacts"][name]["sha256"]:
                raise ValueError("directory binding differs")
            self.directory = json.loads(data)["batches"]
        maxima = [entry["max_id"] for entry in self.directory]
        # The candidate lookup remains authoritative for its original IPC SHA;
        # this receipt independently binds the unchanged (group,row) mapping.
        lookup_groups: dict[int, list[int]] = {}
        for value in sorted(set(requested)):
            index = bisect_left(maxima, value)
            if index < len(maxima) and self.directory[index]["min_id"] <= value:
                lookup_groups.setdefault(index, []).append(value)
        addresses: dict[int, list[tuple[int, int]]] = {}
        for index, wanted in lookup_groups.items():
            batch = self.lookup.get_batch(index)
            values = batch.column("id").to_numpy()
            for value in wanted:
                row = int(np.searchsorted(values, value))
                if row < len(values) and values[row] == value:
                    addresses.setdefault(batch.column("block")[row].as_py(), []).append(
                        (batch.column("row")[row].as_py(), value)
                    )
        names = list(dict.fromkeys([*columns, "id"]))
        table = self.records(addresses, names)
        positions = {value: row for row, value in enumerate(table.column("id").to_pylist())}
        absent = sorted(set(requested) - positions.keys())
        return table.take(
            pa.array([positions[value] for value in requested if value in positions], type=pa.int64())
        ).select(columns), absent

    def spatial(
        self, window: tuple[float, float, float, float], columns: list[str], level: int | None = None
    ) -> pa.Table:
        bbox = conservative(window)
        indices = {self.reader.metadata.schema.column(i).path: i for i in range(self.reader.metadata.num_columns)}
        groups = []
        for index in range(self.reader.num_row_groups):
            group = self.reader.metadata.row_group(index)
            stats = [group.column(indices[name]).statistics for name in BBOX_LEAVES]
            if any(stat is None or not stat.has_min_max for stat in stats):
                groups.append(index)
                continue
            numeric = cast(list[pq.Statistics], stats)
            lo_x, lo_y, hi_x, hi_y = [cast(float, stat.min if i < 2 else stat.max) for i, stat in enumerate(numeric)]
            if lo_x <= bbox[2] and lo_y <= bbox[3] and hi_x >= bbox[0] and hi_y >= bbox[1]:
                groups.append(index)
        self.discovery_groups = groups
        bounds = self.read_groups(groups, ["id", "level", "bbox"])
        addresses: dict[int, list[tuple[int, int]]] = {}
        offset = 0
        for group in groups:
            size = self.reader.metadata.row_group(group).num_rows
            piece = bounds.slice(offset, size)
            limits = cast(pa.StructArray, piece.column("bbox").combine_chunks())
            lo_x, lo_y, hi_x, hi_y = [limits.field(name).to_numpy() for name in ("xmin", "ymin", "xmax", "ymax")]
            mask = (lo_x <= bbox[2]) & (lo_y <= bbox[3]) & (hi_x >= bbox[0]) & (hi_y >= bbox[1])
            if level is not None:
                mask &= piece.column("level").to_numpy() == level
            ids = cast(list[int], piece.column("id").to_pylist())
            for row in np.flatnonzero(mask).tolist():
                addresses.setdefault(group, []).append((row, ids[row]))
            offset += size
        return self.records(addresses, columns)

    def stats(self) -> dict[str, Any]:
        return {
            "http_requests": len(self.http.requests),
            "http_body_bytes": sum(item["bytes"] for item in self.http.requests),
            "local_read_calls": sum(file.reads for file in self.files if isinstance(file, CountFile)),
            "local_read_bytes": sum(file.bytes for file in self.files if isinstance(file, CountFile)),
            "materialized_rows": self.materialized_rows,
            "materialized_bytes": self.materialized_bytes,
            "materialized_geometry_bytes": self.materialized_geometry_bytes,
            "discovery_groups": self.discovery_groups,
            "record_groups": self.last_groups,
            "retained_bounded_range_bytes": sum(
                sum(len(data) for _, data in raw.regions) for raw in self.files if isinstance(raw, RangeFile)
            ),
            "footer_bytes": self.reader.metadata.serialized_size,
        }

    def close(self) -> None:
        self.reader.close()
        for stream in self.pafiles:
            stream.close()
        for raw in self.files:
            if isinstance(raw, CountFile):
                raw.stream.close()
            raw.close()


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
