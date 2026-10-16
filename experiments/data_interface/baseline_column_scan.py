"""One-process original-IPC column census; not a reader library."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import resource
import sys
from pathlib import Path
from time import perf_counter

import pyarrow as pa


class CountedFile(io.RawIOBase):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.file = path.open("rb")
        self.calls = 0
        self.bytes = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        return self.file.seek(offset, whence)

    def tell(self) -> int:
        return self.file.tell()

    def read(self, size: int = -1) -> bytes:
        data = self.file.read(size)
        self.calls += 1
        self.bytes += len(data)
        return data

    def close(self) -> None:
        self.file.close()
        super().close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--columns", nargs="+", required=True)
    parser.add_argument("--mode", choices=("full", "projected"), required=True)
    parser.add_argument("--expected-rows", type=int, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.output.resolve().is_relative_to(args.source.resolve().parent):
        raise ValueError("report must be outside input bundle")
    manifest_bytes = (args.source.parent / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    source_identity = manifest["artifacts"][args.source.name]
    # Untimed schema selection is reported, not hidden in opening costs.
    metadata_started = perf_counter()
    with pa.OSFile(str(args.source), "rb") as source:
        schema = pa.ipc.open_file(source).schema
    schema_seconds = perf_counter() - metadata_started
    names = list(dict.fromkeys(["id", *args.columns]))
    fields = [schema.get_field_index(name) for name in names]
    if any(field < 0 for field in fields):
        raise ValueError("unknown projected field")
    handle = CountedFile(args.source)
    started = perf_counter()
    reader = pa.ipc.open_file(
        pa.PythonFile(handle, mode="r"),
        options=pa.ipc.IpcReadOptions(included_fields=fields if args.mode == "projected" else None),
    )
    opened = {
        "seconds": perf_counter() - started,
        "serialized_read_calls": handle.calls,
        "serialized_read_bytes": handle.bytes,
    }
    initial_calls, initial_bytes = handle.calls, handle.bytes
    rows = materialized = selected_bytes = max_batch_bytes = 0
    nulls = dict.fromkeys(names, 0)
    first_id: int | None = None
    last_id: int | None = None
    read_seconds = select_seconds = 0.0
    started = perf_counter()
    for index in range(reader.num_record_batches):
        phase = perf_counter()
        batch = reader.get_batch(index)
        read_seconds += perf_counter() - phase
        phase = perf_counter()
        selected = batch.select(names)
        rows += batch.num_rows
        materialized += batch.nbytes
        selected_bytes += selected.nbytes
        max_batch_bytes = max(max_batch_bytes, batch.nbytes)
        for name in names:
            nulls[name] += selected.column(name).null_count
        if first_id is None:
            first_id = selected.column("id")[0].as_py()
        last_id = selected.column("id")[-1].as_py()
        select_seconds += perf_counter() - phase
    scan_seconds = perf_counter() - started
    if rows != args.expected_rows:
        raise ValueError((rows, args.expected_rows))
    result = {
        "kind": "local_ipc_global_scan",
        "source": str(args.source),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "source_artifact_identity": source_identity,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "mode": args.mode,
        "columns": names,
        "python": sys.version,
        "pyarrow": pa.__version__,
        "platform": platform.platform(),
        "cache": "fresh process; filesystem cache uncontrolled; schema discovery pre-reads footer",
        "schema_discovery_seconds": schema_seconds,
        "open": opened,
        "scan_seconds": scan_seconds,
        "batch_read_seconds": read_seconds,
        "column_select_and_census_seconds": select_seconds,
        "scan_serialized_read_calls": handle.calls - initial_calls,
        "scan_serialized_read_bytes": handle.bytes - initial_bytes,
        "rows": rows,
        "batches": reader.num_record_batches,
        "materialized_logical_bytes_total": materialized,
        "requested_logical_bytes_total": selected_bytes,
        "max_live_input_batch_logical_bytes": max_batch_bytes,
        "retained_global_rows": 0,
        "null_counts": nulls,
        "first_id": first_id,
        "last_id": last_id,
        "geometry_decoded": False,
        "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "limitations": "local OS reads, not HTTP bytes or physical disk IO; no geometry decoding; peak is lifetime process RSS, max live batch excludes temporaries",
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)
    handle.close()


if __name__ == "__main__":
    main()
