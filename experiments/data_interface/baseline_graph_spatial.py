"""Counted original Parquet bbox discovery; no topology preparation or record fetch.

Use from HFX root with uv run python <script> SOURCE --family rivers --window small
--report <new.json>. This independent comparator is not a supported reader.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, cast
from urllib.parse import quote, unquote, urljoin, urlparse

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.parquet as pq

from scripts.check_vector_access import HTTP, Fingerprint, RangeFile

type Bounds = tuple[float, float, float, float]
COLUMNS = ["id", "level", "bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"]


class LocalReads(HTTP):
    """Count local serialized reads at the same boundary as HTTP GET bodies."""

    def get(self, url: str, span: tuple[int, int, int] | None = None) -> bytes:
        path = Path(unquote(urlparse(url).path))
        stat = path.stat()
        etag = f'"{stat.st_dev}-{stat.st_ino}-{stat.st_size}-{stat.st_mtime_ns}"'
        if url in self.etags and self.etags[url] != etag:
            raise ValueError("Local artifact changed")
        with path.open("rb") as stream:
            if span is None:
                data = stream.read()
            else:
                start, end, size = span
                if size != stat.st_size:
                    raise ValueError("Local artifact size mismatch")
                stream.seek(start)
                data = stream.read(end - start + 1)
                if len(data) != end - start + 1:
                    raise ValueError("Short local read")
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


def candidate_groups(file: pq.ParquetFile, bbox: Bounds, levels: tuple[int, ...] | None) -> list[int]:
    indices = {file.metadata.schema.column(i).path: i for i in range(file.metadata.num_columns)}
    groups: list[int] = []
    if levels == ():
        return groups
    for index in range(file.num_row_groups):
        group = file.metadata.row_group(index)
        level_stats = group.column(indices["level"]).statistics
        if (
            levels is not None
            and level_stats is not None
            and level_stats.has_min_max
            and not any(cast(int, level_stats.min) <= level <= cast(int, level_stats.max) for level in levels)
        ):
            continue
        stats = [group.column(indices[column]).statistics for column in COLUMNS[2:]]
        if any(
            stat is None or not stat.has_min_max or stat.null_count is None or stat.null_count > 0 for stat in stats
        ):
            groups.append(index)
            continue
        numeric_stats = cast(list[pq.Statistics], stats)
        values = [cast(float, stat.min if i < 2 else stat.max) for i, stat in enumerate(numeric_stats)]
        if values[0] <= bbox[2] and values[1] <= bbox[3] and values[2] >= bbox[0] and values[3] >= bbox[1]:
            groups.append(index)
    return groups


def select_graph(file: pq.ParquetFile, envelope: Bounds, levels: tuple[int, ...] | None) -> dict[str, Any]:
    groups = candidate_groups(file, envelope, levels)
    pieces: list[npt.NDArray[np.int64]] = []
    materialized = 0
    materialized_bytes = 0
    largest_materialized_buffer = 0
    for group in groups:
        table = file.read_row_group(group, columns=COLUMNS, use_threads=False)
        if any(table[column].null_count for column in COLUMNS):
            raise ValueError("Null consumed graph fields")
        materialized += table.num_rows
        materialized_bytes += table.nbytes
        largest_materialized_buffer = max(largest_materialized_buffer, table.get_total_buffer_size())
        lo_x, lo_y, hi_x, hi_y = [table[column].to_numpy() for column in COLUMNS[2:]]
        if (
            np.any(~np.isfinite(np.column_stack([lo_x, lo_y, hi_x, hi_y])))
            or np.any(lo_x > hi_x)
            or np.any(lo_y > hi_y)
        ):
            raise ValueError("Invalid consumed graph bbox")
        mask = (lo_x <= envelope[2]) & (lo_y <= envelope[3]) & (hi_x >= envelope[0]) & (hi_y >= envelope[1])
        if levels is not None:
            mask &= np.isin(table["level"].to_numpy(), levels)
        pieces.append(np.asarray(table["id"].to_numpy()[mask], dtype=np.int64))
    ids = np.concatenate(pieces) if pieces else np.array([], dtype=np.int64)
    return {
        "ids": ids,
        "groups": groups,
        "rows": materialized,
        "max_buffer_bytes": largest_materialized_buffer,
        "logical_bytes": materialized_bytes,
    }


def transfer_phase(transport: HTTP, offset: int, elapsed: float, local: bool) -> dict[str, Any]:
    receipts = transport.requests[offset:]
    count, size = len(receipts), sum(item["bytes"] for item in receipts)
    return {
        "elapsed_seconds": elapsed,
        "http_request_count": 0 if local else count,
        "http_body_bytes": 0 if local else size,
        "local_serialized_read_calls": count if local else 0,
        "local_serialized_read_bytes": size if local else 0,
        "receipts": receipts,
    }


def id_hash(ids: npt.NDArray[np.int64]) -> str:
    return hashlib.sha256(np.asarray(ids, dtype="<i8").tobytes()).hexdigest()


def probe(source: str, family: str, bbox: Bounds, levels: tuple[int, ...] | None = None) -> dict[str, Any]:
    if family not in ("catchments", "rivers"):
        raise ValueError("Unknown family")
    envelope = conservative(bbox)
    local = urlparse(source).scheme not in ("http", "https")
    base = Path(source).resolve().as_uri() + "/" if local else source.rstrip("/") + "/"
    transport = LocalReads() if local else HTTP()
    started = perf_counter()
    manifest_bytes = transport.get(urljoin(base, "manifest.json"))
    manifest = json.loads(manifest_bytes)
    graph_name = manifest["graph"] if family == "catchments" else manifest["rivers"]["graph"]
    if (
        not isinstance(graph_name, str)
        or any(part in ("", ".", "..") for part in graph_name.split("/"))
        or any(c in graph_name for c in "\\%?#:")
    ):
        raise ValueError("Unsafe graph artifact path")
    fingerprint = cast(Fingerprint, manifest["artifacts"][graph_name])
    stream = RangeFile(transport, urljoin(base, quote(graph_name)), fingerprint)
    file = pq.ParquetFile(pa.PythonFile(stream, mode="r"), pre_buffer=False)
    try:
        opening = transfer_phase(transport, 0, perf_counter() - started, local)
        request_start = len(transport.requests)
        selected_started = perf_counter()
        selected = select_graph(file, envelope, levels)
        ids = selected["ids"]
        selection = transfer_phase(transport, request_start, perf_counter() - selected_started, local)
        total_to_result = perf_counter() - started
        return {
            "source": source,
            "family": family,
            "bbox": bbox,
            "expanded_float32_bbox": envelope,
            "levels": levels,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "graph": graph_name,
            "graph_fingerprint": fingerprint,
            "pyarrow_version": pa.__version__,
            "phases": {"opening": opening, "selection": selection},
            "total_to_result_seconds": total_to_result,
            "graph_row_groups": file.num_row_groups,
            "graph_rows": file.metadata.num_rows,
            "selected_groups": selected["groups"],
            "materialized_columns": COLUMNS,
            "materialized_rows": selected["rows"],
            "selected_count": len(ids),
            "selected_ids": ids.tolist(),
            "ordered_ids_sha256_le_i64": id_hash(ids),
            "sorted_ids_sha256_le_i64": id_hash(np.sort(ids)),
            "retained_output_bytes": ids.nbytes,
            "largest_materialized_group_buffer_bytes": selected["max_buffer_bytes"],
            "retained_head_tail_buffer_bytes": sum(len(data) for _, data in stream.regions),
            "process_lifetime_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            * (1 if sys.platform == "darwin" else 1024),
            "integrity": "manifest snapshot, graph size/head/tail hashes and pinned transport identity; no full graph hash or DAG verification",
            "cache_policy": "retained head/tail only; Parquet pre_buffer=False, projected row groups, use_threads=False; uncontrolled filesystem/CDN cache",
            "accounting": "actual returned HTTP bodies/calls, excludes headers/TLS/retries below adapter; local serialized reads are not physical disk IO; output and materialized buffer are not RSS",
            "scope": "bbox candidate IDs only, no topology prep, geometry decoding or selected feature records",
        }
    finally:
        file.close()
        stream.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--family", choices=("catchments", "rivers"), required=True)
    window = parser.add_mutually_exclusive_group(required=True)
    window.add_argument("--window")
    window.add_argument("--bbox", type=float, nargs=4)
    parser.add_argument("--levels", type=int, nargs="*")
    parser.add_argument("--workloads", type=Path, default=Path(__file__).with_name("results") / "workloads.json")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    if not args.source.startswith(("http://", "https://")) and args.report.resolve().is_relative_to(
        Path(args.source).resolve()
    ):
        raise ValueError("report must be outside input bundle")
    expected = None
    if args.window:
        workloads = json.loads(args.workloads.read_text())
        expected = workloads[f"{args.family}_graph"]["windows"][args.window]
        bbox = cast(Bounds, tuple(expected["bounds_epsg4326"]))
    else:
        bbox = cast(Bounds, tuple(args.bbox))
    levels = None if args.levels is None else tuple(args.levels)
    result = probe(args.source, args.family, bbox, levels)
    if expected is not None:
        if workloads["manifest_sha256"] != result["manifest_sha256"]:
            raise ValueError("workload source manifest differs")
        result["workloads_sha256"] = hashlib.sha256(args.workloads.read_bytes()).hexdigest()
        if levels is None:
            oracle = expected["all_tiers"]
        elif len(levels) == 1:
            oracle = expected["by_independent_domain_tier"][str(levels[0])]
        else:
            oracle = None
        if oracle is not None:
            assert result["selected_count"] == oracle["count"]
            assert result["sorted_ids_sha256_le_i64"] == oracle["sorted_ids_sha256_le_i64"]
            result["source_oracle_count_and_hash_match"] = True
    result["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with args.report.open("x") as output:
        output.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
