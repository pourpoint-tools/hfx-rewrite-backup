"""Instrumented local/HTTP access probes for the experiment, not a public reader."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from bisect import bisect_left
from collections.abc import Buffer
from pathlib import Path
from time import perf_counter
from typing import Any, cast
from urllib.parse import urljoin

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from experiments.data_interface.build import peak_rss
from experiments.data_interface.features import overlaps
from scripts.check_vector_access import HTTP, RangeFile


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


class ReadIntoFile(io.RawIOBase):
    """Add the standard readinto protocol for optional seekable read-ahead."""

    def __init__(self, stream: CountFile | RangeFile) -> None:
        super().__init__()
        self.stream = stream

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.stream.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.stream.seek(offset, whence)

    def readinto(self, buffer: Buffer, /) -> int:
        view = memoryview(buffer).cast("B")
        data = self.stream.read(len(view))
        view[: len(data)] = data
        return len(data)

    def close(self) -> None:
        self.stream.close()
        super().close()


class Access:
    def __init__(
        self,
        root: str,
        family: str,
        columns: list[str] | None,
        *,
        relationship: bool = False,
        graph_pre_buffer: bool = True,
        graph_grouped: bool = True,
        read_ahead_bytes: int = 0,
    ) -> None:
        if read_ahead_bytes < 0:
            raise ValueError("read-ahead bytes must not be negative")
        self.read_ahead_bytes = read_ahead_bytes
        self.buffered_files: dict[str, io.BufferedReader] = {}
        self.graph_pre_buffer = graph_pre_buffer
        self.graph_grouped = graph_grouped
        self.graph_max_buffer_bytes = 0
        self.root = root.rstrip("/") + "/"
        self.remote = root.startswith(("https://", "http://"))
        self.http = HTTP()
        self.files: dict[str, CountFile | RangeFile] = {}
        self.pafiles: dict[str, pa.PythonFile] = {}
        self.spatial_reader: ipc.RecordBatchFileReader | None = None
        self.graph_reader: pq.ParquetFile | None = None
        manifest_bytes = (
            self.http.get(urljoin(self.root, "manifest.json"))
            if self.remote
            else (Path(root) / "manifest.json").read_bytes()
        )
        self.manifest = json.loads(manifest_bytes)
        self.manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        self.relationship = relationship
        if self.manifest.get("experimental"):
            self.declaration = self.manifest["relationships" if relationship else "families"][family]
        else:
            if relationship:
                raise ValueError("baseline has no published reverse adjacency")
            self.declaration = (
                {
                    "data": self.manifest["catchments"],
                    "lookup": self.manifest["lookup"],
                    "directory": self.manifest["directory"],
                    "graph": self.manifest["graph"],
                }
                if family == "catchments"
                else self.manifest[family]
            )
        self.columns = columns
        self.directory = json.loads(self.read_bytes(self.declaration["directory"]))["batches"]
        self.maxima = [entry["max_id"] for entry in self.directory]
        self.lookup = None if relationship else ipc.open_file(self.open(self.declaration["lookup"]))
        if self.lookup is not None:
            metadata = self.lookup.schema.metadata or {}
            binding_key = (
                b"hfx:catchments_sha256"
                if family == "catchments" and not self.manifest.get("experimental")
                else b"hfx:data_sha256"
            )
            expected = self.manifest["artifacts"][self.declaration["data"]]["sha256"].encode()
            if metadata.get(binding_key) != expected:
                raise ValueError("lookup data binding differs")
        if (
            self.manifest.get("experimental")
            and not relationship
            and self.declaration.get("data_sha256") != self.manifest["artifacts"][self.declaration["data"]]["sha256"]
        ):
            raise ValueError("spatial/data binding differs")
        self.data_file = self.open(self.declaration["data"])
        self.data_file.seek(0)
        if self.data_file.read(8)[:6] != b"ARROW1":
            raise ValueError("invalid IPC file magic")
        self.schema = ipc.read_schema(ipc.read_message(self.data_file))
        names = None if columns is None else list(dict.fromkeys([*columns, "id"]))
        fields = None if names is None else [self.schema.get_field_index(name) for name in names]
        if fields is not None and (-1 in fields or not fields):
            raise ValueError("unknown projected column")
        self.reader = ipc.open_file(self.data_file, options=ipc.IpcReadOptions(included_fields=fields))
        self.spatial_directory = (
            json.loads(self.read_bytes(self.declaration["spatial"]))["batches"]
            if "spatial" in self.declaration
            else None
        )
        self.lookup_blocks: set[int] = set()
        self.data_blocks: set[int] = set()
        self.graph_blocks: set[int] = set()
        self.materialized_rows = 0
        self.materialized_bytes = 0
        self.requested_rows = 0

    def open(self, name: str) -> pa.PythonFile:
        if name not in self.files:
            if self.remote:
                self.files[name] = RangeFile(self.http, urljoin(self.root, name), self.manifest["artifacts"][name])
            else:
                path = Path(self.root) / name
                identity = self.manifest["artifacts"][name]
                if path.stat().st_size != identity["size_bytes"]:
                    raise ValueError("local artifact size differs")
                local = CountFile(path)
                width = min(65536, identity["size_bytes"])
                for offset, key in [(0, "head_sha256"), (identity["size_bytes"] - width, "tail_sha256")]:
                    local.seek(offset)
                    if hashlib.sha256(local.read(width)).hexdigest() != identity[key]:
                        local.stream.close()
                        raise ValueError("local bounded fingerprint differs")
                local.seek(0)
                self.files[name] = local
        if name not in self.pafiles:
            stream: CountFile | RangeFile | io.BufferedReader = self.files[name]
            if self.read_ahead_bytes and name.endswith(".arrow"):
                stream = io.BufferedReader(ReadIntoFile(self.files[name]), buffer_size=self.read_ahead_bytes)
                self.buffered_files[name] = stream
            self.pafiles[name] = pa.PythonFile(stream, mode="r")
        return self.pafiles[name]

    def read_bytes(self, name: str) -> bytes:
        stream = self.open(name)
        stream.seek(0)
        value = stream.read()
        expected = self.manifest["artifacts"][name]["sha256"]
        if hashlib.sha256(value).hexdigest() != expected:
            raise ValueError("directory fingerprint differs")
        return value

    def close(self) -> None:
        if self.graph_reader is not None:
            self.graph_reader.close()
        for file in self.pafiles.values():
            file.close()
        for file in self.files.values():
            if isinstance(file, CountFile):
                file.stream.close()
            file.close()

    def __enter__(self) -> Access:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def stats(self) -> dict[str, Any]:
        return {
            "http_requests": len(self.http.requests),
            "http_body_bytes": sum(request["bytes"] for request in self.http.requests),
            "local_read_calls": sum(f.reads for f in self.files.values() if isinstance(f, CountFile)),
            "local_read_bytes": sum(f.bytes for f in self.files.values() if isinstance(f, CountFile)),
            "lookup_blocks": sorted(self.lookup_blocks),
            "data_blocks": sorted(self.data_blocks),
            "graph_blocks": sorted(self.graph_blocks),
            "materialized_rows": self.materialized_rows,
            "materialized_bytes": self.materialized_bytes,
            "requested_rows": self.requested_rows,
            "graph_max_buffer_bytes": self.graph_max_buffer_bytes,
            "graph_pre_buffer": self.graph_pre_buffer,
            "graph_grouped": self.graph_grouped,
            "read_ahead_bytes": self.read_ahead_bytes,
            "read_ahead_capacity_bytes": len(self.buffered_files) * self.read_ahead_bytes,
            "retained_range_bytes": sum(
                sum(len(data) for _, data in f.regions) for f in self.files.values() if isinstance(f, RangeFile)
            ),
            "arrow_allocator_bytes": pa.total_allocated_bytes(),
            "process_peak_rss_bytes": peak_rss(),
        }

    def reset(self) -> None:
        self.graph_max_buffer_bytes = 0
        self.lookup_blocks.clear()
        self.data_blocks.clear()
        self.graph_blocks.clear()
        self.materialized_rows = self.materialized_bytes = self.requested_rows = 0

    def ids(self, requested: list[int]) -> tuple[pa.Table, list[int]]:
        values = np.asarray(requested, dtype=np.int64)
        if np.any(values <= 0):
            raise ValueError("IDs must be positive")
        self.requested_rows += len(requested)
        groups: dict[int, list[int]] = {}
        for value in np.unique(values).tolist():
            index = bisect_left(self.maxima, value)
            if index < len(self.directory) and self.directory[index]["min_id"] <= value:
                groups.setdefault(index, []).append(value)
        selected = []
        found = []
        addresses: dict[int, list[tuple[int, int]]] = {}
        loaded: dict[int, pa.RecordBatch] = {}
        for index, ids in groups.items():
            if self.relationship:
                batch = self.reader.get_batch(index)
            else:
                assert self.lookup is not None
                batch = self.lookup.get_batch(index)
                self.lookup_blocks.add(index)
            if self.relationship:
                loaded[index] = batch
                self.data_blocks.add(index)
                self.materialized_rows += batch.num_rows
                self.materialized_bytes += batch.nbytes
            source_ids = batch.column("id").to_numpy()
            positions = np.searchsorted(source_ids, ids)
            for value, position in zip(ids, positions, strict=True):
                if position < len(source_ids) and source_ids[position] == value:
                    if self.relationship:
                        addresses.setdefault(index, []).append((int(position), value))
                    else:
                        addresses.setdefault(int(batch.column("block")[int(position)].as_py()), []).append(
                            (int(batch.column("row")[int(position)].as_py()), value)
                        )
        for block, targets in addresses.items():
            batch = loaded[block] if self.relationship else self.reader.get_batch(block)
            if not self.relationship:
                self.data_blocks.add(block)
                self.materialized_rows += batch.num_rows
                self.materialized_bytes += batch.nbytes
            positions = np.asarray([row for row, _ in targets], dtype=np.int64)
            ids = np.asarray([value for _, value in targets], dtype=np.int64)
            if (
                np.any(positions < 0)
                or np.any(positions >= batch.num_rows)
                or not np.array_equal(batch.column("id").to_numpy()[positions], ids)
            ):
                raise ValueError("address ID mismatch")
            selected.append(batch.take(pa.array(positions, type=pa.int64())))
            found.append(ids)
        table = pa.Table.from_batches(selected, schema=self.reader.schema)
        received = np.concatenate(found) if found else np.array([], dtype=np.int64)
        order = np.argsort(received)
        sorted_ids = received[order]
        positions = np.searchsorted(sorted_ids, values)
        exists = positions < len(sorted_ids)
        if len(sorted_ids):
            exists &= sorted_ids[np.minimum(positions, len(sorted_ids) - 1)] == values
            table = table.take(pa.array(order[positions[exists]], type=pa.int64()))
        if self.columns is not None:
            table = table.select(self.columns)
        return table, np.unique(values[~exists]).tolist()

    def spatial(self, window: tuple[float, ...], *, level: int | None = None) -> list[int]:
        if not self.manifest.get("experimental") and "graph" in self.declaration:
            return self.graph_spatial(window, level=level)
        if self.spatial_reader is None:
            fields = [self.schema.get_field_index(name) for name in ("id", "level", "bbox")]
            self.spatial_reader = (
                self.reader
                if set(self.reader.schema.names) == {"id", "level", "bbox"}
                else ipc.open_file(self.data_file, options=ipc.IpcReadOptions(included_fields=fields))
            )
        reader = self.spatial_reader
        entries: list[dict[str, Any]] = self.spatial_directory or [
            {"batch": i} for i in range(reader.num_record_batches)
        ]
        found = []
        # Query expansion follows the independent float32 bound oracle.
        window = tuple(
            float(np.nextafter(np.float32(value), np.float32(-np.inf if i < 2 else np.inf)))
            for i, value in enumerate(window)
        )
        for entry in entries:
            if "bbox" in entry and not overlaps(entry["bbox"], window):
                continue
            if level is not None and "min_level" in entry and not entry["min_level"] <= level <= entry["max_level"]:
                continue
            batch = reader.get_batch(entry["batch"])
            self.data_blocks.add(entry["batch"])
            self.materialized_rows += batch.num_rows
            self.materialized_bytes += batch.nbytes
            bounds = cast(pa.StructArray, batch.column("bbox"))
            mask = np.ones(batch.num_rows, dtype=np.bool_)
            for name, value, less in [
                ("xmin", window[2], True),
                ("xmax", window[0], False),
                ("ymin", window[3], True),
                ("ymax", window[1], False),
            ]:
                array = bounds.field(name).to_numpy()
                mask &= array <= value if less else array >= value
            if level is not None:
                mask &= batch.column("level").to_numpy() == level
            found.extend(batch.column("id").to_numpy()[mask].tolist())
        return sorted(found)

    def graph_spatial(self, window: tuple[float, ...], *, level: int | None = None) -> list[int]:
        """Original graph discovery with same-instance Parquet metadata reuse."""
        from experiments.data_interface.baseline_graph_spatial import Bounds, conservative, select_graph

        if self.graph_reader is None:
            self.graph_reader = pq.ParquetFile(self.open(self.declaration["graph"]), pre_buffer=self.graph_pre_buffer)
        selected = select_graph(
            self.graph_reader,
            conservative(cast(Bounds, window)),
            None if level is None else (level,),
            grouped=self.graph_grouped,
        )
        self.graph_max_buffer_bytes = max(self.graph_max_buffer_bytes, selected["max_buffer_bytes"])
        self.graph_blocks.update(selected["groups"])
        self.materialized_rows += selected["rows"]
        self.materialized_bytes += selected["logical_bytes"]
        return sorted(selected["ids"].tolist())


def table_identity(table: pa.Table) -> str:
    sink = pa.BufferOutputStream()
    with ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table.combine_chunks())
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure published immediate relationship access")
    parser.add_argument("bundle")
    parser.add_argument("--family", choices=["catchments", "rivers", "river_nodes"], default="rivers")
    parser.add_argument("--ids", type=int, nargs="+", required=True)
    parser.add_argument("--relation", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    if not args.bundle.startswith(("http://", "https://")) and args.report.resolve().is_relative_to(
        Path(args.bundle).resolve()
    ):
        raise ValueError("report must be outside input bundle")
    started = perf_counter()
    with Access(args.bundle, args.family, ["id", args.relation], relationship=True) as access:
        report: dict[str, Any] = {
            "manifest_sha256": access.manifest_sha256,
            "opening_s": perf_counter() - started,
            "opening": access.stats(),
            "cache_policy": "metadata and bounded head/tail only; no selected-batch cache",
            "filesystem_cache": "uncontrolled",
            "phases": [],
        }
        for index in range(args.repeats):
            access.reset()
            before = access.stats()
            started = perf_counter()
            table, absent = access.ids(args.ids)
            elapsed = perf_counter() - started
            phase = {
                "phase": "first" if index == 0 else "repeated",
                "elapsed_s": elapsed,
                "absent": absent,
                "output_rows": table.num_rows,
                "output_logical_bytes": table.nbytes,
                "arrow_stream_sha256": table_identity(table),
                **access.stats(),
            }
            for key in ("http_requests", "http_body_bytes", "local_read_calls", "local_read_bytes"):
                phase[key] -= before[key]
            report["phases"].append(phase)
        report["requests"] = access.http.requests
    with args.report.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
