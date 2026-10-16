"""Measure supplied-graph inclusive membership, not delineation. One strategy/process."""

from __future__ import annotations

import argparse
import hashlib
import json
from bisect import bisect_left
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any, cast
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from experiments.data_interface.build import peak_rss
from experiments.data_interface.probe import Access, CountFile
from scripts.check_vector_access import HTTP, RangeFile

IntArray = npt.NDArray[np.int64]


class NumericGraph:
    def __init__(self, table: pa.Table, column: str) -> None:
        self.table = table.select(["id", column]).combine_chunks()
        self.ids = np.asarray(self.table["id"].to_numpy(), dtype=np.int64)
        self.column = column

    @classmethod
    def from_incoming(cls, table: pa.Table, direction: str) -> NumericGraph:
        table = table.sort_by([("id", "ascending")]).combine_chunks()
        if direction == "upstream":
            return cls(table, "upstream_ids")
        incoming = cast(pa.ListArray, table["upstream_ids"].chunk(0))
        targets = np.repeat(table["id"].to_numpy(), np.diff(incoming.offsets.to_numpy()))
        sources = incoming.values.to_numpy()
        ids = table["id"].to_numpy()
        positions = np.searchsorted(ids, sources)
        if np.any(positions >= len(ids)) or not np.array_equal(ids[positions], sources):
            raise ValueError("absent relationship ID")
        order = np.lexsort((targets, positions))
        offsets = np.concatenate(([0], np.cumsum(np.bincount(positions, minlength=len(ids)))))
        adjacency = pa.LargeListArray.from_arrays(
            pa.array(offsets, type=pa.int64()), pa.array(targets[order], type=pa.int64())
        )
        return cls(pa.table({"id": ids, "downstream_ids": adjacency}), "downstream_ids")

    def neighbors(self, ids: IntArray) -> IntArray:
        positions = np.searchsorted(self.ids, ids)
        if np.any(positions >= len(self.ids)) or not np.array_equal(self.ids[positions], ids):
            raise ValueError("absent requested ID")
        selected = pc.take(self.table[self.column], pa.array(positions, type=pa.int64()))
        return np.asarray(pc.list_flatten(selected).to_numpy(), dtype=np.int64)


def traverse(neighbors: Callable[[IntArray], IntArray], seed: int | IntArray) -> tuple[IntArray, int]:
    """Identical sorted frontier/visited operations for all acquisition strategies."""
    frontier = np.unique(np.atleast_1d(np.asarray(seed, dtype=np.int64)))
    visited = frontier.copy()
    peak = visited.nbytes + frontier.nbytes
    while len(frontier):
        adjacent = neighbors(frontier)
        following = np.setdiff1d(adjacent, visited)
        # Conservative numeric-operation estimate, not an exact allocation/heap profiler.
        peak = max(peak, 3 * (visited.nbytes + frontier.nbytes + adjacent.nbytes + following.nbytes))
        visited = np.union1d(visited, following)
        frontier = following
    return visited, peak


class Published:
    """Narrow query-owned batch reuse; no cross-query adjacency cache."""

    def __init__(self, access: Access, column: str, strategy: str) -> None:
        self.access, self.column, self.strategy = access, column, strategy
        self.cache: dict[int, pa.RecordBatch] = {}
        self.graph: NumericGraph | None = None
        self.scratch: TemporaryDirectory[str] | None = None
        self.download: dict[str, Any] = {}

    def close(self) -> None:
        if self.scratch is not None:
            self.scratch.cleanup()

    def prepare(self) -> None:
        if self.strategy == "bulk-file":
            if not self.access.remote:
                raise ValueError("bulk-file requires an HTTP bundle")
            self.scratch = TemporaryDirectory(prefix="hfx-adjacency-")
            path = Path(self.scratch.name) / "adjacency.arrow"
            self.download["temporary_directory"] = self.scratch.name
            name = self.access.declaration["data"]
            identity = self.access.manifest["artifacts"][name]
            url = urljoin(self.access.root, name)
            etag = self.access.http.etags[url]
            request = Request(
                url,
                headers={
                    "Accept-Encoding": "identity",
                    "If-Match": etag,
                    "User-Agent": "hfx-vector-verification/0.4.0",
                },
            )
            digest = hashlib.sha256()
            received = 0
            started = perf_counter()
            with urlopen(request) as response:
                try:
                    if response.status != 200:
                        raise ValueError("full artifact download requires HTTP 200")
                    if response.headers.get("ETag") != etag:
                        raise ValueError("ETag changed during full download")
                    if response.headers.get("Content-Encoding", "identity") != "identity":
                        raise ValueError("full download encoding must preserve bytes")
                    if response.headers.get("Content-Length") != str(identity["size_bytes"]):
                        raise ValueError("full download length differs")
                    with path.open("xb") as output:
                        while chunk := response.read(8 * 1024 * 1024):
                            received += len(chunk)
                            if received > identity["size_bytes"]:
                                raise ValueError("full download exceeds declared length")
                            digest.update(chunk)
                            output.write(chunk)
                finally:
                    self.access.http.requests.append(
                        {
                            "url": url,
                            "start": None,
                            "end": None,
                            "bytes": received,
                            "etag": response.headers.get("ETag", ""),
                        }
                    )
                    self.download.update(
                        {
                            "http_body_bytes": received,
                            "disk_bytes": path.stat().st_size if path.exists() else 0,
                            "sha256": digest.hexdigest(),
                            "download_s": perf_counter() - started,
                        }
                    )
            if received != identity["size_bytes"] or digest.hexdigest() != identity["sha256"]:
                raise ValueError("full download size or digest differs")
            fields = [self.access.schema.get_field_index(name) for name in ["id", self.column]]
            with pa.OSFile(str(path), "rb") as source:
                reader = pa.ipc.open_file(source, options=pa.ipc.IpcReadOptions(included_fields=fields))
                batches = []
                for index in range(reader.num_record_batches):
                    batch = reader.get_batch(index)
                    self.loaded(index, batch)
                    batches.append(batch)
                self.graph = NumericGraph(pa.Table.from_batches(batches), self.column)
        elif self.strategy == "bulk":
            batches = []
            for index in range(self.access.reader.num_record_batches):
                batch = self.access.reader.get_batch(index)
                self.loaded(index, batch)
                batches.append(batch)
            self.graph = NumericGraph(pa.Table.from_batches(batches), self.column)

    def loaded(self, index: int, batch: pa.RecordBatch) -> None:
        self.access.data_blocks.add(index)
        self.access.materialized_rows += batch.num_rows
        self.access.materialized_bytes += batch.nbytes

    def reset(self) -> None:
        self.cache.clear()

    def retained(self) -> int:
        return (self.graph.table.get_total_buffer_size() if self.graph else 0) + sum(
            batch.get_total_buffer_size() for batch in self.cache.values()
        )

    def neighbors(self, ids: IntArray) -> IntArray:
        if self.graph is not None:
            return self.graph.neighbors(ids)
        if self.strategy == "selective":
            table, absent = self.access.ids(ids.tolist())
            if absent:
                raise ValueError(f"absent requested IDs: {absent[:8]}")
        else:
            self.access.requested_rows += len(ids)
            groups: dict[int, list[int]] = {}
            for value in ids.tolist():
                index = bisect_left(self.access.maxima, value)
                if index >= len(self.access.directory) or self.access.directory[index]["min_id"] > value:
                    raise ValueError(f"absent requested ID: {value}")
                groups.setdefault(index, []).append(value)
            selected = []
            for index, values in groups.items():
                if index not in self.cache:
                    self.cache[index] = self.access.reader.get_batch(index)
                    self.loaded(index, self.cache[index])
                batch = self.cache[index]
                source_ids = batch.column("id").to_numpy()
                positions = np.searchsorted(source_ids, values)
                if np.any(positions >= len(source_ids)) or not np.array_equal(source_ids[positions], values):
                    raise ValueError("absent requested ID")
                selected.append(batch.take(pa.array(positions, type=pa.int64())))
            table = pa.Table.from_batches(selected)
        return np.asarray(pc.list_flatten(table[self.column]).to_numpy(), dtype=np.int64)


class Original:
    """Fair baseline: manifest + projected graph only; no feature IPC or lookup."""

    def __init__(self, root: str, family: str) -> None:
        self.root = root.rstrip("/") + "/"
        self.remote = root.startswith(("http://", "https://"))
        self.http = HTTP()
        raw = (
            self.http.get(urljoin(self.root, "manifest.json"))
            if self.remote
            else (Path(root) / "manifest.json").read_bytes()
        )
        self.manifest = json.loads(raw)
        self.manifest_sha256 = hashlib.sha256(raw).hexdigest()
        if self.manifest.get("experimental"):
            raise ValueError("consumer requires original bundle")
        self.name = self.manifest["graph"] if family == "catchments" else self.manifest[family]["graph"]
        identity = self.manifest["artifacts"][self.name]
        self.file = (
            RangeFile(self.http, urljoin(self.root, self.name), identity)
            if self.remote
            else CountFile(Path(root) / self.name)
        )
        if isinstance(self.file, CountFile):
            if (Path(root) / self.name).stat().st_size != identity["size_bytes"]:
                raise ValueError("local artifact size differs")
            width = min(65536, identity["size_bytes"])
            for offset, key in [(0, "head_sha256"), (identity["size_bytes"] - width, "tail_sha256")]:
                self.file.seek(offset)
                if hashlib.sha256(self.file.read(width)).hexdigest() != identity[key]:
                    raise ValueError("local bounded fingerprint differs")
            self.file.seek(0)
        self.stream = pa.PythonFile(self.file, mode="r")
        self.reader = pq.ParquetFile(self.stream, pre_buffer=False)

    def stats(self) -> dict[str, Any]:
        return {
            "http_requests": len(self.http.requests),
            "http_body_bytes": sum(r["bytes"] for r in self.http.requests),
            "local_read_calls": self.file.reads if isinstance(self.file, CountFile) else 0,
            "local_read_bytes": self.file.bytes if isinstance(self.file, CountFile) else 0,
            "retained_range_bytes": sum(len(data) for _, data in self.file.regions)
            if isinstance(self.file, RangeFile)
            else 0,
            "process_peak_rss_bytes": peak_rss(),
            "arrow_allocator_bytes": pa.total_allocated_bytes(),
        }

    def close(self) -> None:
        self.stream.close()
        if isinstance(self.file, CountFile):
            self.file.stream.close()
        self.file.close()


def id_identity(values: IntArray) -> dict[str, Any]:
    return {
        "count": len(values),
        "sorted_ids_sha256_le_i64": hashlib.sha256(values.astype("<i8", copy=False).tobytes()).hexdigest(),
    }


def check_connectivity(status: list[dict[str, Any]], level: int) -> None:
    if not any(item["level"] == level and item["status"] == "supplied" for item in status):
        raise ValueError(f"connectivity not supplied for catchment level {level}; not a known terminal")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, epilog="Run each strategy in a fresh process. Filesystem cache is uncontrolled."
    )
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--family", choices=["rivers", "catchments"], default="rivers")
    parser.add_argument("--seed", type=int, default=4)
    parser.add_argument("--direction", choices=["upstream", "downstream"], default="downstream")
    parser.add_argument(
        "--strategy", choices=["selective", "batch-cache", "bulk", "bulk-file", "consumer"], required=True
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--oracles", type=Path, default=Path(__file__).with_name("results") / "archived-oracles.json")
    parser.add_argument("--workloads", type=Path)
    parser.add_argument("--window", choices=["small", "elongated"])
    parser.add_argument("--level", type=int)
    parser.add_argument("--record-columns", nargs="+")
    parser.add_argument("--workflow-oracles", type=Path)
    parser.add_argument("--decode-geometry", action="store_true")
    parser.add_argument("--source-manifest-sha256", help="expected original manifest identity, checked after opening")
    args = parser.parse_args()
    if args.window and (
        args.workloads is None
        or args.level not in ([1] if args.family == "catchments" else [0, 1])
        or not args.record_columns
    ):
        parser.error("workflow requires --workloads, --record-columns, river level0/1 or supplied catchment level1")
    if args.record_columns and not args.window:
        parser.error("--record-columns requires workflow --window")
    if args.decode_geometry and (not args.record_columns or "geometry" not in args.record_columns):
        parser.error("--decode-geometry requires geometry in --record-columns")
    workloads = json.loads(args.workloads.read_text()) if args.window else None
    window = tuple(workloads[f"{args.family}_graph"]["windows"][args.window]["bounds_epsg4326"]) if workloads else None
    workflow_oracles = json.loads(args.workflow_oracles.read_text()) if args.workflow_oracles else None
    workflow_oracle = None
    if workflow_oracles:
        workflow_oracle = next(
            (
                item
                for item in workflow_oracles["workflows"]
                if (item["family"], item["window"], item["level"], item["direction"])
                == (args.family, args.window, args.level, args.direction)
            ),
            None,
        )
        if workflow_oracle is None:
            parser.error("no independent workflow oracle for this selection")
    if args.decode_geometry:
        import shapely

    if args.repeats < 1 or args.seed <= 0:
        parser.error("positive seed and repeats required")
    remote = args.bundle.startswith(("http://", "https://"))
    if not remote and args.report.resolve().is_relative_to(Path(args.bundle).resolve()):
        parser.error("report must be outside the source/candidate bundle")
    oracle: dict[str, Any] | None = None
    if args.family == "rivers" and args.oracles.exists():
        oracle = next(
            (
                item
                for item in json.loads(args.oracles.read_text())["graph_operations"]
                if item["event"] == "reachable" and item["seed"] == args.seed and item["direction"] == args.direction
            ),
            None,
        )
    code_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt = args.report.open("x")
    start = perf_counter()
    column = f"{args.direction}_ids"
    features: Access | None = None
    try:
        features = (
            Access(args.bundle, args.family, list(dict.fromkeys(["id", *args.record_columns]))) if args.window else None
        )
        access: Access | Original = (
            Original(args.bundle, args.family)
            if args.strategy == "consumer"
            else Access(args.bundle, args.family, ["id", column], relationship=True)
        )
    except Exception as error:
        if features is not None:
            features.close()
        with receipt:
            receipt.write(
                json.dumps({"error": str(error), "phase": "opening", "elapsed_s": perf_counter() - start}) + "\n"
            )
        raise
    opened = perf_counter()
    report: dict[str, Any] = {
        "strategy": args.strategy,
        "family": args.family,
        "seed": args.seed,
        "direction": args.direction,
        "manifest_sha256": access.manifest_sha256,
        "opening_s": opened - start,
        "opening": access.stats(),
        "feature_opening": features.stats() if features else None,
        "workflow": {
            "window": args.window,
            "level": args.level,
            "columns": args.record_columns,
            "bbox_semantics": "conservative candidates, not exact intersection",
            "baseline_overhead": "feature Access graph_spatial opens graph separately; duplicate opening/footer reads counted",
        }
        if args.window
        else None,
        "phases": [],
        "filesystem_cache": "uncontrolled",
        "versions": {"numpy": np.__version__, "pyarrow": pa.__version__},
        "code_sha256": code_sha256,
        "timer_boundary": "opening + preparation (includes connectivity validation) + first query; excludes imports, CLI parsing, oracle load and report bookkeeping",
        "consumer_remote": "original projected Parquet; acquisition and numeric preparation inside first-result time",
        "cache_policy": "query-owned batch cache cleared before every traversal; bounded transport head/tail retained",
        "scope": "inclusive unique membership over supplied edges; not delineation or terminal classification",
    }
    validation: Access | None = None
    provider: Published | NumericGraph | None = None

    def discover() -> tuple[IntArray, dict[str, Any]]:
        assert features is not None and window is not None
        features.reset()
        before = features.stats()
        started = perf_counter()
        selected = np.asarray(features.spatial(window, level=args.level), dtype=np.int64)
        phase = {
            "elapsed_s": perf_counter() - started,
            "selected_ids_array_bytes": selected.nbytes,
            **id_identity(selected),
            **features.stats(),
        }
        for key in ("http_requests", "http_body_bytes", "local_read_calls", "local_read_bytes"):
            phase[key] -= before[key]
        if workflow_oracle is not None and any(
            workflow_oracle["seeds"][key] != actual for key, actual in id_identity(selected).items()
        ):
            raise ValueError("independent discovery oracle mismatch")
        return selected, phase

    try:
        source_sha = (
            access.manifest.get("input_manifest_sha256", access.manifest_sha256)
            if isinstance(access, Access)
            else access.manifest_sha256
        )
        if args.source_manifest_sha256 is not None and args.source_manifest_sha256 != source_sha:
            raise ValueError("expected source manifest differs")
        report["source_manifest_sha256"] = source_sha
        if workloads is not None and workloads["manifest_sha256"] != source_sha:
            raise ValueError("workload source manifest differs")
        if workflow_oracles is not None and workflow_oracles["source_manifest_sha256"] != source_sha:
            raise ValueError("workflow oracle source manifest differs")
        report["workloads_sha256"] = hashlib.sha256(args.workloads.read_bytes()).hexdigest() if args.workloads else None
        report["workflow_oracles_sha256"] = (
            hashlib.sha256(args.workflow_oracles.read_bytes()).hexdigest() if args.workflow_oracles else None
        )
        seeds, discovery = discover() if features is not None else (args.seed, None)
        prep_start = perf_counter()
        if args.window and args.family == "catchments":
            statuses = (
                access.manifest["catchment_connectivity"]
                if isinstance(access, Original)
                else access.declaration["connectivity"]
            )
            check_connectivity(statuses, args.level)
        if isinstance(access, Original):
            columns = ["id", "upstream_ids"] + (["level"] if args.family == "catchments" and not args.window else [])
            table = access.reader.read(columns=columns).combine_chunks()
            if args.family == "catchments" and not args.window:
                row = table.filter(pc.equal(table["id"], args.seed))
                if row.num_rows != 1:
                    raise ValueError("absent seed")
                check_connectivity(access.manifest["catchment_connectivity"], cast(int, row["level"].to_pylist()[0]))
            graph = NumericGraph.from_incoming(table.select(["id", "upstream_ids"]), args.direction)
            del table
            provider = graph
        else:
            if args.family == "catchments" and not args.window:
                validation = Access(args.bundle, "catchments", ["id", "level"])
                row, absent = validation.ids([args.seed])
                if absent:
                    raise ValueError("absent seed")
                check_connectivity(access.declaration["connectivity"], cast(int, row["level"].to_pylist()[0]))
            provider = Published(access, column, args.strategy)
            provider.prepare()
        prepared = perf_counter()
        report["preparation_s"] = prepared - prep_start
        report["after_preparation"] = access.stats()
        if validation is not None:
            report["connectivity_validation"] = {**validation.stats(), "requests": validation.http.requests}
        for index in range(args.repeats):
            if index and features is not None:
                seeds, discovery = discover()
            if isinstance(provider, Published):
                provider.reset()
            if isinstance(access, Access):
                access.reset()
            before = access.stats()
            started = perf_counter()
            result, workspace = traverse(provider.neighbors, seeds)
            finished = perf_counter()
            if index == 0:
                report["startup_to_first_result_s"] = (
                    report["opening_s"]
                    + report["preparation_s"]
                    + (discovery["elapsed_s"] if discovery else 0)
                    + finished
                    - started
                )
            digest = hashlib.sha256(result.astype("<i8", copy=False).tobytes()).hexdigest()
            phase = {
                "phase": "first" if index == 0 else "repeat",
                "elapsed_s": finished - started,
                "discovery": discovery,
                "count": len(result),
                "sorted_ids_sha256_le_i64": digest,
                "output_array_bytes": result.nbytes,
                "numeric_workspace_estimate_bytes": workspace,
                "workspace_method": "3x simultaneous frontier/visited/adjacent/next numeric bytes; excludes Python heap",
                "retained_adjacency_buffers_bytes": provider.retained()
                if isinstance(provider, Published)
                else provider.table.get_total_buffer_size(),
                "oracle": (
                    "matched workflow seeds + closure"
                    if workflow_oracle is not None
                    else "no independent workflow oracle"
                )
                if args.window
                else ("no independent oracle for this selection" if oracle is None else "matched"),
                **access.stats(),
            }
            for key in ("http_requests", "http_body_bytes", "local_read_calls", "local_read_bytes"):
                phase[key] -= before[key]
            report["phases"].append(phase)
            if workflow_oracle is not None and any(
                workflow_oracle["closure"][key] != actual for key, actual in id_identity(result).items()
            ):
                raise ValueError("independent workflow closure oracle mismatch")
            if features is not None:
                features.reset()
                before_records = features.stats()
                record_start = perf_counter()
                records, absent = features.ids(result.tolist())
                record_elapsed = perf_counter() - record_start
                phase["records"] = {
                    "elapsed_s": record_elapsed,
                    "rows": records.num_rows,
                    "retained_buffers_bytes": records.get_total_buffer_size(),
                    **features.stats(),
                }
                for key in ("http_requests", "http_body_bytes", "local_read_calls", "local_read_bytes"):
                    phase["records"][key] -= before_records[key]
                if absent:
                    raise ValueError("absent workflow output record ID")
                if index == 0:
                    report["startup_to_records_s"] = report["startup_to_first_result_s"] + record_elapsed
                    report["wall_to_first_records_s"] = perf_counter() - start
                if args.decode_geometry:
                    decode_start = perf_counter()
                    decoded = shapely.from_wkb(records["geometry"].to_numpy())
                    phase["geometry_decode"] = {
                        "elapsed_s": perf_counter() - decode_start,
                        "count": len(decoded),
                        "shapely_version": shapely.__version__,
                    }
                    if index == 0:
                        report["startup_to_decoded_records_s"] = (
                            report["startup_to_records_s"] + phase["geometry_decode"]["elapsed_s"]
                        )
                    del decoded
                del records
            if (
                not args.window
                and oracle is not None
                and (oracle["count"] != len(result) or oracle["sorted_ids_sha256"] != digest)
            ):
                raise ValueError("independent traversal oracle mismatch")
            del result
        report["requests"] = access.http.requests
        report["process_peak_rss_bytes"] = peak_rss()
        report["memory_note"] = (
            "retained Arrow buffers, estimated query workspace and cumulative process peak RSS are distinct; no exact Python heap claim"
        )
    except Exception as error:
        report["error"] = str(error)
        report["requests"] = access.http.requests
        raise
    finally:
        if isinstance(provider, Published):
            if provider.download:
                report["bulk_file"] = provider.download
            provider.close()
        if validation is not None:
            validation.close()
        if features is not None:
            report["feature_requests"] = features.http.requests
            report["feature_manifest_sha256"] = features.manifest_sha256
            features.close()
        access.close()
        with receipt:
            receipt.write(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
