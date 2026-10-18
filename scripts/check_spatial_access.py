"""Selective local/HTTP production probe; not a traversal engine or integrity verifier.

Use a trusted, fully verified manifest. Bounded hashes detect endpoint mismatch,
not interior corruption. Fresh readers do not imply cold filesystem/CDN caches.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import resource
import sys
from bisect import bisect_left
from pathlib import Path
from time import perf_counter
from typing import Any, cast
from urllib.parse import urljoin

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from scripts.check_vector_access import HTTP, Fingerprint, RangeFile

BBOX_LEAVES = [f"bbox.{name}" for name in ("xmin", "ymin", "xmax", "ymax")]
Bounds = tuple[float, float, float, float]


def conservative(bbox: Bounds) -> Bounds:
    if not all(np.isfinite(bbox)) or bbox[0] > bbox[2] or bbox[1] > bbox[3]:
        raise ValueError("Expected finite ordered bbox")
    if any(abs(value) > np.finfo(np.float32).max for value in bbox):
        raise ValueError("bbox outside float32 range")
    return cast(
        Bounds,
        tuple(
            float(np.nextafter(np.float32(value), np.float32(-np.inf if i < 2 else np.inf)))
            for i, value in enumerate(bbox)
        ),
    )


class CountFile(io.RawIOBase):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.stream = path.open("rb")
        self.bytes = 0
        self.reads = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.stream.seek(offset, whence)

    def tell(self) -> int:
        return self.stream.tell()

    def read(self, size: int = -1) -> bytes:
        data = self.stream.read(size)
        self.bytes += len(data)
        self.reads += 1
        return data


class SpatialAccess:
    """Retained native readers for one production feature domain."""

    def __init__(self, bundle: str, domain: str) -> None:
        self.http = HTTP()
        self.files: list[CountFile | RangeFile] = []
        self.pafiles: list[pa.PythonFile] = []
        self.candidate = bundle.rstrip("/") + "/"
        raw = (
            self.http.get(urljoin(self.candidate, "manifest.json"))
            if bundle.startswith("http")
            else (Path(bundle) / "manifest.json").read_bytes()
        )
        self.manifest_sha256 = hashlib.sha256(raw).hexdigest()
        self.manifest = json.loads(raw)
        if (self.manifest["representation"], self.manifest["representation_version"]) != (
            "spatial-geoparquet-adjacency",
            1,
        ):
            raise ValueError("unsupported stored representation")
        self.domain = domain
        self.declaration = self.manifest["families"][domain]
        name = self.declaration["data"]
        identity = self.manifest["artifacts"][name]
        if identity["sha256"] != self.declaration["data_sha256"]:
            raise ValueError("feature artifact binding differs")
        self.reader = pq.ParquetFile(self.open(urljoin(self.candidate, name), identity), pre_buffer=True)
        self.lookup: ipc.RecordBatchFileReader | None = None
        self.directory: list[dict[str, Any]] = []
        self.relationship_reader: ipc.RecordBatchFileReader | None = None
        self.relationship_directory: list[dict[str, Any]] = []
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
        table = self.reader.read_row_groups(groups, columns=columns, use_threads=False).select(columns)
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
            if (self.lookup.schema.metadata or {}).get(b"hfx:data_sha256") != self.declaration["data_sha256"].encode():
                raise ValueError("candidate lookup binding differs")
            name = self.declaration["directory"]
            data = self.open(urljoin(self.candidate, name), self.manifest["artifacts"][name]).read()
            if hashlib.sha256(data).hexdigest() != self.manifest["artifacts"][name]["sha256"]:
                raise ValueError("directory binding differs")
            self.directory = json.loads(data)["batches"]
        maxima = [entry["max_id"] for entry in self.directory]
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

    def bulk(self, columns: list[str], reference: SpatialAccess | None = None) -> tuple[int, int, float]:
        """Stream 8192-row batches; time acquisition separately from exact comparison."""
        from hfx.spatial_features import exact_array

        rows = size = 0
        elapsed = 0.0
        self.last_groups = list(range(self.reader.num_row_groups))
        actual = self.reader.iter_batches(batch_size=8192, columns=columns, use_threads=False)
        expected = None
        if reference is not None:
            if self.manifest_sha256 != reference.manifest_sha256:
                raise ValueError("reference manifest differs")
            if not self.reader.schema_arrow.equals(reference.reader.schema_arrow, check_metadata=True):
                raise ValueError("reference schema differs")
            expected = reference.reader.iter_batches(batch_size=8192, columns=columns, use_threads=False)
        while True:
            started = perf_counter()
            batch = next(actual, None)
            elapsed += perf_counter() - started
            if batch is None:
                break
            rows += batch.num_rows
            size += batch.nbytes
            self.materialized_rows += batch.num_rows
            self.materialized_bytes += batch.nbytes
            if "geometry" in columns:
                self.materialized_geometry_bytes += batch.column("geometry").nbytes
            if expected is not None:
                wanted = next(expected, None)
                if wanted is None or not all(
                    exact_array(left, right) for left, right in zip(batch.columns, wanted.columns, strict=True)
                ):
                    raise ValueError("reference bulk records differ")
        if expected is not None and next(expected, None) is not None:
            raise ValueError("reference bulk row count differs")
        return rows, size, elapsed

    def neighbors(self, requested: list[int], column: str) -> list[int]:
        declaration = self.manifest["relationships"][self.domain]
        if column not in declaration["columns"]:
            raise ValueError("unknown relationship column")
        for domain, binding in declaration["feature_artifacts"].items():
            family = self.manifest["families"][domain]
            if binding != {key: family[key] for key in ("data", "data_sha256")}:
                raise ValueError("relationship feature binding differs")
        if self.relationship_reader is None or column not in self.relationship_reader.schema.names:
            name = declaration["data"]
            stream = self.open(urljoin(self.candidate, name), self.manifest["artifacts"][name])
            schema = ipc.open_file(stream).schema
            stream.seek(0)
            self.relationship_reader = ipc.open_file(
                stream,
                options=ipc.IpcReadOptions(included_fields=[schema.get_field_index(name) for name in ("id", column)]),
            )
            name = declaration["directory"]
            data = self.open(urljoin(self.candidate, name), self.manifest["artifacts"][name]).read()
            if hashlib.sha256(data).hexdigest() != self.manifest["artifacts"][name]["sha256"]:
                raise ValueError("relationship directory binding differs")
            self.relationship_directory = json.loads(data)["batches"]
        maxima = [entry["max_id"] for entry in self.relationship_directory]
        wanted: dict[int, list[int]] = {}
        for value in sorted(set(requested)):
            index = bisect_left(maxima, value)
            if index < len(maxima) and self.relationship_directory[index]["min_id"] <= value:
                wanted.setdefault(index, []).append(value)
        found: set[int] = set()
        for index, values in wanted.items():
            batch = self.relationship_reader.get_batch(index)
            ids = batch.column("id").to_numpy()
            self.materialized_rows += batch.num_rows
            self.materialized_bytes += batch.nbytes
            for value in values:
                row = int(np.searchsorted(ids, value))
                if row < len(ids) and ids[row] == value:
                    found.update(batch.column(column)[row].as_py())
        return sorted(found)

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
        }

    def close(self) -> None:
        self.reader.close()
        for stream in self.pafiles:
            stream.close()
        for raw in self.files:
            if isinstance(raw, CountFile):
                raw.stream.close()
            raw.close()


def _select(
    access: SpatialAccess, target: SpatialAccess, args: argparse.Namespace, columns: list[str]
) -> tuple[pa.Table, list[int]]:
    if args.relationship:
        return target.ids(access.neighbors(args.ids, args.relationship), columns)
    if args.ids is not None:
        return access.ids(args.ids, columns)
    return access.spatial(cast(Bounds, tuple(args.bounds)), columns, args.level), []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle")
    parser.add_argument("--domain", required=True, choices=["catchments", "rivers", "river_nodes"])
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--ids", type=int, nargs="+")
    selection.add_argument("--bounds", type=float, nargs=4)
    selection.add_argument("--bulk", action="store_true")
    parser.add_argument("--relationship", help="Immediate column to compose from --ids; target domain is declared")
    parser.add_argument("--columns", nargs="+", help="Omit to read full records")
    parser.add_argument("--level", type=int)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument(
        "--reference", type=Path, help="Fully verified local final bundle; comparison outside query timers"
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or (args.relationship and args.ids is None):
        parser.error("positive repeats and --ids for relationships required")
    if args.report.exists():
        raise FileExistsError(args.report)
    if not args.bundle.startswith("http") and args.report.resolve().is_relative_to(Path(args.bundle).resolve()):
        parser.error("report must be outside bundle")
    started = perf_counter()
    access = SpatialAccess(args.bundle, args.domain)
    target = access
    try:
        if args.relationship:
            binding = access.manifest["relationships"][args.domain]["columns"][args.relationship]
            if binding["target_domain"] != args.domain:
                target = SpatialAccess(args.bundle, binding["target_domain"])
        readers = [access] if target is access else [access, target]
        metrics = (
            "http_requests",
            "http_body_bytes",
            "local_read_calls",
            "local_read_bytes",
            "materialized_rows",
            "materialized_bytes",
            "materialized_geometry_bytes",
        )

        def totals() -> dict[str, int]:
            return {key: sum(reader.stats()[key] for reader in readers) for key in metrics}

        opening_s = perf_counter() - started
        report: dict[str, Any] = {
            "domain": args.domain,
            "manifest_sha256": access.manifest_sha256,
            "query": {
                "ids": args.ids,
                "bounds": args.bounds,
                "bulk": args.bulk,
                "relationship": args.relationship,
                "level": args.level,
            },
            "opening_s": opening_s,
            "opening": totals(),
            "repeats": [],
            "limitations": "Trusted manifest; bounded hashes are not full integrity verification. HTTP body bytes, not wire bytes. Fresh readers are not cold caches. Retained footers and lazy locators; no application feature cache. Bulk streams 8192-row batches; native buffering is not a process-memory bound. Peak RSS is process lifetime, not per query. Spatial results are bbox candidates, not exact intersections. Reference comparison is same-query transfer equality, not an independent semantic oracle. Reference work is outside query timers/counters; bulk times each next batch and compares outside acquisition timing; process peak RSS includes them.",
        }
        columns = args.columns or target.reader.schema_arrow.names
        report["columns"] = columns
        report["pyarrow_version"] = pa.__version__
        for repeat in range(args.repeats):
            before = totals()
            started = perf_counter()
            bulk_reference = SpatialAccess(str(args.reference), args.domain) if args.bulk and args.reference else None
            try:
                if args.bulk:
                    table, missing, bulk = None, [], access.bulk(columns, bulk_reference)
                else:
                    table, missing = _select(access, target, args, columns)
                    bulk = None
            finally:
                if bulk_reference is not None:
                    bulk_reference.close()
            if bulk is not None:
                rows, logical_bytes, bulk_elapsed = bulk
            else:
                assert table is not None
                rows, logical_bytes = table.num_rows, table.nbytes
            elapsed = bulk_elapsed if bulk is not None else perf_counter() - started
            after = totals()
            reference_status = "equal_verified_local_result" if bulk_reference is not None else "not_requested"
            if args.reference and not args.bulk:
                from hfx.spatial_features import exact_array

                reference = SpatialAccess(str(args.reference), args.domain)
                reference_target = reference
                try:
                    if reference.manifest_sha256 != access.manifest_sha256:
                        raise ValueError("reference manifest differs")
                    if target.domain != access.domain:
                        reference_target = SpatialAccess(str(args.reference), target.domain)
                    expected, absent = _select(reference, reference_target, args, columns)
                    if missing != absent:
                        raise ValueError("reference result differs")
                    assert table is not None
                    if not table.schema.equals(expected.schema, check_metadata=True) or not all(
                        exact_array(left.combine_chunks(), right.combine_chunks())
                        for left, right in zip(table.columns, expected.columns, strict=True)
                    ):
                        raise ValueError("reference records differ")
                    reference_status = "equal_verified_local_result"
                finally:
                    if reference_target is not reference:
                        reference_target.close()
                    reference.close()
            del table
            report["repeats"].append(
                {
                    "repeat": repeat,
                    "elapsed_s": elapsed,
                    "total_to_result_s": elapsed + (opening_s if repeat == 0 else 0),
                    "acquisition": {key: after[key] - before[key] for key in metrics},
                    "reference": reference_status,
                    "rows": rows,
                    "logical_bytes": logical_bytes,
                    "absent": missing,
                    "record_groups": target.last_groups,
                    "discovery_groups": access.discovery_groups,
                }
            )
        report["peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
            1 if sys.platform == "darwin" else 1024
        )
        report["requests"] = [request for reader in readers for request in reader.http.requests]
        report["final"] = totals()
        with args.report.open("x") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
    finally:
        if target is not access:
            target.close()
        access.close()


if __name__ == "__main__":
    main()
