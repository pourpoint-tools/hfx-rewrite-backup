"""One-shot selective HTTP probe, not a supported reader API.

Use a trusted manifest on an immutable endpoint. Bounded hashes detect mismatch;
they do not authenticate interiors. ETags pin versions, not SHA-256 identities.
"""

from __future__ import annotations

import argparse
import io
import json
from bisect import bisect_left
from hashlib import sha256
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import pyarrow as pa
import pyarrow.parquet as pq


class Fingerprint(TypedDict):
    size_bytes: int
    sha256: str
    head_sha256: str
    tail_sha256: str


class Manifest(TypedDict):
    format_version: str
    catchments: str
    lookup: str
    directory: str
    graph: str
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

    def get(self, url: str, span: tuple[int, int, int] | None = None) -> bytes:
        headers = {"Accept-Encoding": "identity", "User-Agent": "hfx-vector-verification/0.4.0"}
        if url in self.etags:
            headers["If-Match"] = self.etags[url]
        if span:
            start, end, size = span
            headers["Range"] = f"bytes={start}-{end}"
        with urlopen(Request(url, headers=headers), timeout=30) as response:
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
            return data


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


def verify_source(
    source: Path, requested: list[int], selected: dict[int, pa.RecordBatch], schema: pa.Schema
) -> dict[str, object]:
    """Scan local source in bounded batches; remote access stays selective."""
    path = source / "catchments.parquet" if source.is_dir() else source
    wanted = set(requested)
    found: set[int] = set()
    with pq.ParquetFile(path) as reader:
        if not reader.schema_arrow.equals(schema, check_metadata=True):
            raise ValueError("Source schema mismatch")
        for batch in reader.iter_batches(batch_size=4096):
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


def check(url: str, ids: list[int], source: Path | None = None) -> dict[str, object]:
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("An HTTP(S) bundle URL is required")
    base = url if url.endswith("/") else url + "/"
    http = HTTP()
    manifest_bytes = http.get(urljoin(base, "manifest.json"))
    manifest = cast(Manifest, json.loads(manifest_bytes))
    if manifest["format_version"] != "0.4.0" or any(
        actual != name
        for actual, name in [
            (manifest["catchments"], "catchments.arrow"),
            (manifest["lookup"], "lookup.arrow"),
            (manifest["directory"], "lookup-directory.json"),
            (manifest["graph"], "graph.parquet"),
        ]
    ):
        raise ValueError("Expected the released 0.4.0 vector layout")
    if "candidate" in manifest or "experimental" in manifest:
        raise ValueError("Experimental manifests are not accepted")
    artifacts = manifest["artifacts"]
    files = {
        name: RangeFile(http, urljoin(base, name), artifacts[name])
        for name in ("lookup-directory.json", "lookup.arrow", "catchments.arrow")
    }
    directory_bytes = files["lookup-directory.json"].read()
    if sha256(directory_bytes).hexdigest() != artifacts["lookup-directory.json"]["sha256"]:
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
    lookup = pa.ipc.open_file(pa.PythonFile(files["lookup.arrow"], mode="r"))
    expected_schema = pa.schema(
        [pa.field("id", pa.int64(), False), pa.field("block", pa.int32(), False), pa.field("row", pa.int32(), False)]
    )
    metadata = lookup.schema.metadata or {}
    if not lookup.schema.equals(expected_schema) or lookup.num_record_batches != len(entries):
        raise ValueError("Lookup schema/directory mismatch")
    if (
        metadata.get(b"hfx:format_version") != b"0.4.0"
        or metadata.get(b"hfx:catchments_sha256") != artifacts["catchments.arrow"]["sha256"].encode()
    ):
        raise ValueError("Lookup catchment binding mismatch")
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
    catchments = pa.ipc.open_file(pa.PythonFile(files["catchments.arrow"], mode="r"))
    rows: list[dict[str, object]] = []
    source_rows: dict[int, pa.RecordBatch] = {}
    for block, targets in sorted(addresses.items()):
        if not 0 <= block < catchments.num_record_batches:
            raise ValueError("Invalid catchment block")
        batch = catchments.get_batch(block)
        for row, value in targets:
            if not 0 <= row < batch.num_rows or batch.column("id")[row].as_py() != value:
                raise ValueError("Lookup address does not match requested ID")
            selected = batch.slice(row, 1)
            if source is not None:
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
    selected_ids = sorted(cast(int, row["id"]) for row in rows)
    report: dict[str, object] = {
        "url": base,
        "manifest_sha256": sha256(manifest_bytes).hexdigest(),
        "artifacts": artifacts,
        "requested_ids": requested,
        "selected_ids": selected_ids,
        "absent_ids": sorted(set(requested) - set(selected_ids)),
        "lookup_batches": sorted(groups),
        "catchment_batches": sorted(addresses),
        "rows": sorted(rows, key=lambda row: cast(int, row["id"])),
        "requests": http.requests,
        "bytes_received": sum(request["bytes"] for request in http.requests),
        "pyarrow_version": pa.__version__,
    }
    if source is not None:
        report["source_verification"] = verify_source(source, requested, source_rows, catchments.schema)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--ids", nargs="+", type=int, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--source",
        type=Path,
        help="Optional local source Parquet file or bundle directory for independent row comparison",
    )
    args = parser.parse_args()
    report = check(args.url, args.ids, args.source)
    args.report.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
