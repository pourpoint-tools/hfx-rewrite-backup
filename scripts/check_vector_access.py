"""One-shot selective HTTP probe, not a supported reader API.

Use a trusted manifest on an immutable endpoint. Bounded hashes detect mismatch;
they do not authenticate interiors. ETags pin versions, not SHA-256 identities.
"""

from __future__ import annotations

import argparse
import io
import json
import struct
from bisect import bisect_left
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import NotRequired, TypedDict, cast
from urllib.parse import quote, urljoin, urlparse

import pyarrow as pa
import pyarrow.parquet as pq
import urllib3


class Fingerprint(TypedDict):
    size_bytes: int
    sha256: str
    head_sha256: str
    tail_sha256: str


class Declaration(TypedDict):
    data: str
    lookup: str
    directory: str


class Manifest(TypedDict):
    format_version: str
    catchments: str
    lookup: str
    directory: str
    graph: str
    rivers: NotRequired[Declaration]
    river_nodes: NotRequired[Declaration]
    artifacts: dict[str, Fingerprint]


class Entry(TypedDict):
    batch: int
    min_id: int
    max_id: int
    rows: int


class Directory(TypedDict):
    version: int
    batches: list[Entry]


class Transfer(TypedDict):
    url: str
    start: int | None
    end: int | None
    bytes: int
    etag: str


class HTTP:
    def __init__(self) -> None:
        self.etags: dict[str, str] = {}
        self.requests: list[Transfer] = []
        self.pool = urllib3.PoolManager(retries=False, timeout=30)

    def close(self) -> None:
        self.pool.clear()

    def get(self, url: str, span: tuple[int, int, int] | None = None) -> bytes:
        headers = {"Accept-Encoding": "identity", "User-Agent": "hfx-vector-verification/0.4.0"}
        if url in self.etags:
            headers["If-Match"] = self.etags[url]
        if span:
            start, end, size = span
            headers["Range"] = f"bytes={start}-{end}"
        response = self.pool.request(
            "GET", url, headers=headers, preload_content=False, decode_content=False, redirect=False
        )
        try:
            if response.headers.get("Content-Encoding", "identity") != "identity":
                raise ValueError("Content-Encoding must preserve original bytes")
            etag = response.headers.get("ETag", "")
            if len(etag) < 2 or not etag.startswith('"') or not etag.endswith('"'):
                raise ValueError("A strong ETag is required")
            if url in self.etags and self.etags[url] != etag:
                raise ValueError("ETag changed during access")
            if span:
                if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{size}":
                    raise ValueError("Invalid 206 Content-Range")
                limit = end - start + 1
            else:
                if response.status != 200:
                    raise ValueError("Expected HTTP 200")
                limit = 16 * 1024 * 1024
            data = response.read(limit + 1)
            if len(data) > limit or (span and len(data) != limit):
                raise ValueError("Unexpected response length")
            self.etags[url] = etag
            self.requests.append(
                {
                    "url": url,
                    "start": span[0] if span else None,
                    "end": span[1] if span else None,
                    "bytes": len(data),
                    "etag": etag,
                }
            )
            response.release_conn()
            return data
        except BaseException:
            response.close()
            response.release_conn()
            raise


class RangeFile(io.RawIOBase):
    """Seek/read adapter used only by this probe's Arrow IPC calls."""

    def __init__(self, http: HTTP, url: str, fingerprint: Fingerprint) -> None:
        super().__init__()
        self.http = http
        self.url = url
        self.size = fingerprint["size_bytes"]
        self.position = 0
        self.regions: list[tuple[int, bytes]] = []
        if self.size <= 0:
            raise ValueError("Artifact must not be empty")
        width = min(65536, self.size)
        for start, key in [(0, "head_sha256"), (self.size - width, "tail_sha256")]:
            self.seek(start)
            data = self.read(width)
            expected = fingerprint["head_sha256"] if key == "head_sha256" else fingerprint["tail_sha256"]
            if sha256(data).hexdigest() != expected:
                raise ValueError(f"Artifact fingerprint mismatch: {url} {key}")
            self.regions.append((start, data))
        self.seek(0)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence not in (0, 1, 2):
            raise ValueError("Invalid seek origin")
        target = offset + (self.position if whence == 1 else self.size if whence == 2 else 0)
        if target < 0:
            raise ValueError("Negative seek")
        self.position = target
        return target

    def read(self, size: int = -1) -> bytes:
        start = self.position
        count = max(0, self.size - start) if size < 0 else max(0, min(size, self.size - start))
        if not count:
            return b""
        for base, data in self.regions:
            if base <= start and start + count <= base + len(data):
                result = data[start - base : start - base + count]
                break
        else:
            result = self.http.get(self.url, (start, start + count - 1, self.size))
        self.position += count
        return result


def _field(data: bytes, table: int, slot: int) -> int:
    """Locate an optional FlatBuffer table field; zero means its default value."""
    vtable = table - struct.unpack_from("<i", data, table)[0]
    size = struct.unpack_from("<H", data, vtable)[0]
    position = 4 + slot * 2
    offset = struct.unpack_from("<H", data, vtable + position)[0] if position < size else 0
    return table + offset if offset else 0


def _indirect(data: bytes, position: int) -> int:
    return position + struct.unpack_from("<I", data, position)[0]


def batch_spans(stream: RangeFile) -> list[tuple[int, int]]:
    """Record-batch byte extents, using verify_vector's Arrow FlatBuffer slots.

    Extents include message metadata and body. Touched means any received byte
    overlaps this extent, not that the entire batch was fetched or decoded.
    """
    stream.seek(-10, 2)
    trailer = stream.read(10)
    if len(trailer) != 10 or trailer[4:] != b"ARROW1":
        raise ValueError("Invalid IPC trailer")
    size = struct.unpack_from("<I", trailer)[0]
    footer_start = stream.size - 10 - size
    if footer_start < 8:
        raise ValueError("Invalid IPC footer size")
    stream.seek(footer_start)
    footer = stream.read(size)
    field = _field(footer, _indirect(footer, 0), 3)
    if not field:
        return []
    vector = _indirect(footer, field)
    count = struct.unpack_from("<I", footer, vector)[0]
    spans = []
    previous = 8
    for number in range(count):
        position = vector + 4 + number * 24
        offset, metadata_size = struct.unpack_from("<qi", footer, position)
        body_size = struct.unpack_from("<q", footer, position + 16)[0]
        end = offset + metadata_size + body_size
        if offset < previous or metadata_size <= 0 or body_size < 0 or end > footer_start:
            raise ValueError("Invalid IPC batch extent")
        spans.append((offset, end))
        previous = end
    return spans


def phase_report(
    http: HTTP,
    start: int,
    elapsed: float,
    files: dict[str, RangeFile],
    spans: dict[str, list[tuple[int, int]]],
    lookup_name: str,
    data_name: str,
    lookup_batches: list[int],
    data_batches: list[int],
) -> dict[str, object]:
    requests = http.requests[start:]
    report: dict[str, object] = {
        "elapsed_seconds": elapsed,
        "request_count": len(requests),
        "body_bytes": sum(request["bytes"] for request in requests),
        "requests": requests,
        "selected_lookup_batches": lookup_batches,
        "selected_data_batches": data_batches,
    }
    for label, name in (("lookup", lookup_name), ("data", data_name)):
        received = sorted(
            (request["start"], request["end"] + 1)
            for request in requests
            if request["url"] == files[name].url and request["start"] is not None and request["end"] is not None
        )
        touched: list[int] = []
        fully_fetched: list[int] = []
        for index, (begin, end) in enumerate(spans[name]):
            if any(start < end and stop > begin for start, stop in received):
                touched.append(index)
            covered = begin
            for start, stop in received:
                if start > covered:
                    break
                covered = max(covered, stop)
            if covered >= end:
                fully_fetched.append(index)
        report[f"touched_{label}_batches"] = touched
        report[f"fully_fetched_{label}_batches"] = fully_fetched
    return report


def verify_source(
    source: Path, requested: list[int], selected: dict[int, pa.RecordBatch], schema: pa.Schema, data_name: str
) -> dict[str, object]:
    """Scan local source in bounded batches; remote access stays selective."""
    path = source / data_name if source.is_dir() else source
    if source.is_dir() and not path.exists() and data_name == "catchments.arrow":
        path = source / "catchments.parquet"
    wanted = set(requested)
    found: set[int] = set()
    if path.suffix == ".parquet":
        parquet = pq.ParquetFile(path)
        source_schema = parquet.schema_arrow
        batches = parquet.iter_batches(batch_size=4096)
    else:
        reader = pa.ipc.open_file(str(path))
        source_schema = reader.schema
        batches = (reader.get_batch(i) for i in range(reader.num_record_batches))
    if not source_schema.equals(schema, check_metadata=True):
        raise ValueError("Source schema mismatch")
    for batch in batches:
        for index, value in enumerate(batch.column("id").to_pylist()):
            if value not in wanted:
                continue
            if value in found:
                raise ValueError(f"Duplicate source ID: {value}")
            if value not in selected or not batch.slice(index, 1).equals(selected[value], check_metadata=True):
                raise ValueError(f"Source row mismatch: {value}")
            found.add(value)
    if found != set(selected):
        raise ValueError("Source selected-ID mismatch")
    return {
        "path": str(path.resolve()),
        "matched_ids": sorted(found),
        "absent_ids": sorted(wanted - found),
        "schema_and_all_values_equal": True,
    }


def check(url: str, ids: list[int], source: Path | None = None, artifact: str = "catchments") -> dict[str, object]:
    http = HTTP()
    try:
        return _check(http, url, ids, source, artifact)
    finally:
        http.close()


def _check(http: HTTP, url: str, ids: list[int], source: Path | None, artifact: str) -> dict[str, object]:
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("An HTTP(S) bundle URL is required")
    base = url if url.endswith("/") else url + "/"
    started = perf_counter()
    manifest_bytes = http.get(urljoin(base, "manifest.json"))
    manifest = cast(Manifest, json.loads(manifest_bytes))
    if manifest["format_version"] != "0.4.0":
        raise ValueError("Expected format version 0.4.0")
    if "candidate" in manifest or "experimental" in manifest:
        raise ValueError("Experimental manifests are not accepted")
    if artifact == "catchments":
        declaration: Declaration = {
            "data": manifest["catchments"],
            "lookup": manifest["lookup"],
            "directory": manifest["directory"],
        }
        binding = b"hfx:catchments_sha256"
    elif artifact in ("rivers", "river_nodes"):
        declaration = manifest[artifact]
        binding = b"hfx:data_sha256"
    else:
        raise ValueError("Unknown artifact selection")
    data_name, lookup_name, directory_name = (declaration[key] for key in ("data", "lookup", "directory"))
    artifacts = manifest["artifacts"]
    for name in (data_name, lookup_name, directory_name):
        if (
            not name
            or any(part in ("", ".", "..") for part in name.split("/"))
            or any(character in name for character in "\\%?#:")
            or any(ord(character) < 32 for character in name)
            or name not in artifacts
        ):
            raise ValueError(f"Invalid local artifact path: {name}")
    if len({data_name, lookup_name, directory_name}) != 3:
        raise ValueError("Selected artifact paths must be distinct")
    files = {
        name: RangeFile(http, urljoin(base, quote(name)), artifacts[name])
        for name in (directory_name, lookup_name, data_name)
    }
    directory_bytes = files[directory_name].read()
    if sha256(directory_bytes).hexdigest() != artifacts[directory_name]["sha256"]:
        raise ValueError("Directory digest mismatch")
    directory = cast(Directory, json.loads(directory_bytes))
    entries = directory["batches"]
    if directory["version"] != 1:
        raise ValueError("Unsupported directory version")
    previous = 0
    for index, entry in enumerate(entries):
        if entry["batch"] != index or entry["rows"] <= 0 or not previous < entry["min_id"] <= entry["max_id"]:
            raise ValueError("Invalid directory ranges")
        previous = entry["max_id"]
    lookup = pa.ipc.open_file(pa.PythonFile(files[lookup_name], mode="r"))
    expected_schema = pa.schema(
        [pa.field("id", pa.int64(), False), pa.field("block", pa.int32(), False), pa.field("row", pa.int32(), False)]
    )
    metadata = lookup.schema.metadata or {}
    if not lookup.schema.equals(expected_schema) or lookup.num_record_batches != len(entries):
        raise ValueError("Lookup schema/directory mismatch")
    if metadata != {b"hfx:format_version": b"0.4.0", binding: artifacts[data_name]["sha256"].encode()}:
        raise ValueError("Lookup data binding mismatch")
    data_reader = pa.ipc.open_file(pa.PythonFile(files[data_name], mode="r"))
    spans = {name: batch_spans(files[name]) for name in (lookup_name, data_name)}
    phases = {
        "preparation": phase_report(http, 0, perf_counter() - started, files, spans, lookup_name, data_name, [], [])
    }

    def select() -> tuple[
        list[int],
        dict[int, list[int]],
        dict[int, list[tuple[int, int]]],
        list[dict[str, object]],
        dict[int, pa.RecordBatch],
    ]:
        requested = sorted(set(ids))
        if any(value <= 0 or value > 2**63 - 1 for value in requested):
            raise ValueError("IDs must be positive signed int64")
        maxima = [entry["max_id"] for entry in entries]
        groups: dict[int, list[int]] = {}
        for value in requested:
            index = bisect_left(maxima, value)
            if index < len(entries) and entries[index]["min_id"] <= value:
                groups.setdefault(index, []).append(value)
        addresses: dict[int, list[tuple[int, int]]] = {}
        for index, values in groups.items():
            batch = lookup.get_batch(index)
            if any(column.null_count for column in batch.columns):
                raise ValueError("Null lookup address")
            batch_ids = cast(list[int], batch.column(0).to_pylist())
            if (
                batch.num_rows != entries[index]["rows"]
                or not batch_ids
                or batch_ids[0] != entries[index]["min_id"]
                or batch_ids[-1] != entries[index]["max_id"]
                or any(a >= b for a, b in zip(batch_ids, batch_ids[1:], strict=False))
            ):
                raise ValueError("Invalid selected lookup batch")
            for value in values:
                row = bisect_left(batch_ids, value)
                if row < len(batch_ids) and batch_ids[row] == value:
                    block = int(batch.column(1)[row].as_py())
                    target = int(batch.column(2)[row].as_py())
                    addresses.setdefault(block, []).append((target, value))
        rows: list[dict[str, object]] = []
        source_rows: dict[int, pa.RecordBatch] = {}
        for block, targets in sorted(addresses.items()):
            if not 0 <= block < data_reader.num_record_batches:
                raise ValueError("Invalid data block")
            batch = data_reader.get_batch(block)
            for row, value in targets:
                if not 0 <= row < batch.num_rows or batch.column("id")[row].as_py() != value:
                    raise ValueError("Lookup address does not match requested ID")
                selected = batch.slice(row, 1)
                source_rows[value] = batch.take(pa.array([row], type=pa.int64()))
                sink = pa.BufferOutputStream()
                with pa.ipc.new_file(sink, selected.schema) as writer:
                    writer.write_batch(selected)
                geometry = selected.column("geometry")[0].as_py()
                rows.append(
                    {
                        "id": value,
                        "block": block,
                        "row": row,
                        "row_ipc_sha256": sha256(sink.getvalue().to_pybytes()).hexdigest(),
                        "geometry_sha256": sha256(geometry).hexdigest(),
                    }
                )
        return requested, groups, addresses, rows, source_rows

    first_rows: dict[int, pa.RecordBatch] = {}
    for phase in ("first_access", "repeated_access"):
        request_start = len(http.requests)
        started = perf_counter()
        requested, groups, addresses, rows, source_rows = select()
        phases[phase] = phase_report(
            http,
            request_start,
            perf_counter() - started,
            files,
            spans,
            lookup_name,
            data_name,
            sorted(groups),
            sorted(addresses),
        )
        if phase == "first_access":
            first_rows = source_rows
    if first_rows.keys() != source_rows.keys() or any(
        not row.equals(source_rows[value], check_metadata=True) for value, row in first_rows.items()
    ):
        raise ValueError("Repeated selected rows differ")
    selected_ids = sorted(cast(int, row["id"]) for row in rows)
    report: dict[str, object] = {
        "url": base,
        "artifact": artifact,
        "manifest_etag": http.etags[urljoin(base, "manifest.json")],
        "phases": phases,
        "integrity": "bounded fingerprints and pinned ETags; full artifact hashes require separate verification",
        "repeat_policy": "uncached batches; retained head/tail buffers and IPC metadata",
        "batch_accounting": "touched means received bytes overlap batch metadata/body; not necessarily a full batch",
        "data_batches": sorted(addresses),
        "batch_spans": spans,
        "manifest_sha256": sha256(manifest_bytes).hexdigest(),
        "artifacts": artifacts,
        "requested_ids": requested,
        "selected_ids": selected_ids,
        "absent_ids": sorted(set(requested) - set(selected_ids)),
        "lookup_batches": sorted(groups),
        "rows": sorted(rows, key=lambda row: cast(int, row["id"])),
        "requests": http.requests,
        "bytes_received": sum(request["bytes"] for request in http.requests),
        "pyarrow_version": pa.__version__,
    }
    if artifact == "catchments":
        report["catchment_batches"] = sorted(addresses)
    if source is not None:
        report["source_verification"] = verify_source(source, requested, source_rows, data_reader.schema, data_name)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--ids", nargs="+", type=int, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--artifact", choices=("catchments", "rivers", "river_nodes"), default="catchments")
    parser.add_argument(
        "--source",
        type=Path,
        help="Optional local Parquet or independently verified sample IPC file/bundle for complete row comparison",
    )
    args = parser.parse_args()
    report_path: Path = args.report.resolve()
    if args.report.exists() or args.report.is_symlink():
        raise FileExistsError(args.report)
    if args.source is not None:
        source_path: Path = args.source.resolve()
        if report_path == source_path or (source_path.is_dir() and report_path.is_relative_to(source_path)):
            raise ValueError("report must be outside the source")
    report = check(args.url, args.ids, args.source, args.artifact)
    with report_path.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
