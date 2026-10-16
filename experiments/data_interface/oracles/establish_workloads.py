"""Read only published source inputs; never import candidate or archived prototypes."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
from collections import deque
from pathlib import Path
from typing import Any, cast

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely

ROOT: Path
CATCHMENT_GRAPH: Path
OUT: Path


def digest(ids: np.ndarray[Any, Any]) -> str:
    return hashlib.sha256(np.asarray(ids, dtype="<i8").tobytes()).hexdigest()


def summary(ids: np.ndarray[Any, Any]) -> dict[str, Any]:
    return {
        "count": int(len(ids)),
        "ordered_ids_sha256_le_i64": digest(ids),
        "sorted_ids_sha256_le_i64": digest(np.sort(ids)),
        "first_ids": ids[:8].tolist(),
        "last_ids": ids[-8:].tolist(),
    }


def encoded(table: pa.Table) -> str:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table.combine_chunks())
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def record_witness(table: pa.Table) -> dict[str, Any]:
    geom = cast(list[bytes], table["geometry"].to_pylist())
    return {
        "ids": table["id"].to_pylist(),
        "levels": table["level"].to_pylist(),
        "schema_sha256": hashlib.sha256(table.schema.serialize().to_pybytes()).hexdigest(),
        "complete_arrow_stream_sha256": encoded(table),
        "wkb_sha256_each": [hashlib.sha256(v).hexdigest() for v in geom],
        "bbox": table["bbox"].to_pylist(),
        "decoded_geometry_types": shapely.get_type_id(shapely.from_wkb(geom)).tolist(),
    }


def select_original(domain: str, ids: list[int]) -> pa.Table:
    lookup_name = {"rivers": "river-lookup.arrow", "nodes": "river-node-lookup.arrow", "catchments": "lookup.arrow"}[
        domain
    ]
    data_name = {"rivers": "rivers.arrow", "nodes": "river-nodes.arrow", "catchments": "catchments.arrow"}[domain]
    directory_name = {
        "rivers": "river-lookup-directory.json",
        "nodes": "river-node-lookup-directory.json",
        "catchments": "lookup-directory.json",
    }[domain]
    directory = json.loads((ROOT / directory_name).read_text())["batches"]
    pieces = []
    with pa.OSFile(str(ROOT / lookup_name), "rb") as f, pa.OSFile(str(ROOT / data_name), "rb") as d:
        lookup, data = pa.ipc.open_file(f), pa.ipc.open_file(d)
        for identity in ids:
            index = next(i for i, entry in enumerate(directory) if entry["min_id"] <= identity <= entry["max_id"])
            batch = lookup.get_batch(index)
            matches = np.flatnonzero(batch["id"].to_numpy() == identity)
            assert len(matches) == 1
            entry = batch.slice(int(matches[0]), 1).to_pydict()
            row = data.get_batch(entry["block"][0]).slice(entry["row"][0], 1)
            assert row["id"][0].as_py() == identity
            pieces.append(row)
    return pa.Table.from_batches(pieces)


def original_rows(domain: str) -> dict[str, Any]:
    name = {"rivers": "rivers.arrow", "nodes": "river-nodes.arrow", "catchments": "catchments.arrow"}[domain]
    with pa.OSFile(str(ROOT / name), "rb") as f:
        reader = pa.ipc.open_file(f)
        first = reader.get_batch(0)
        middle = reader.get_batch(reader.num_record_batches // 2)
        last = reader.get_batch(reader.num_record_batches - 1)
        ids = [
            int(first["id"][0].as_py()),
            int(middle["id"][middle.num_rows // 2].as_py()),
            int(last["id"][-1].as_py()),
        ]
        grouped_ids = cast(list[int], first["id"].slice(0, 16).to_pylist())
        return {
            "data": str(ROOT / name),
            "batch_count": reader.num_record_batches,
            "row_based_selection": "first row; middle row of middle batch; last row (not arithmetic IDs)",
            "scattered_ids": ids,
            "clustered_ids": grouped_ids,
            "scattered_complete_records": record_witness(select_original(domain, ids)),
            "clustered_complete_records": record_witness(select_original(domain, grouped_ids)),
        }


def graph_workloads(path: Path, flow: bool) -> dict[str, Any]:
    columns = ["id", "level", "bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"]
    if flow:
        columns.append("upstream_ids")
    table = pq.read_table(path, columns=columns)
    ids = table["id"].combine_chunks().to_numpy()
    levels = table["level"].combine_chunks().to_numpy()
    coords = np.column_stack([table[c].combine_chunks().to_numpy() for c in columns[2:6]])
    boundary = coords[255:257]
    windows = {
        "small": [
            float((coords[0, 0] + coords[0, 2]) / 2 - 0.01),
            float((coords[0, 1] + coords[0, 3]) / 2 - 0.01),
            float((coords[0, 0] + coords[0, 2]) / 2 + 0.01),
            float((coords[0, 1] + coords[0, 3]) / 2 + 0.01),
        ],
        "elongated": [
            float((coords[0, 0] + coords[0, 2]) / 2 - 1),
            float((coords[0, 1] + coords[0, 3]) / 2 - 0.01),
            float((coords[0, 0] + coords[0, 2]) / 2 + 1),
            float((coords[0, 1] + coords[0, 3]) / 2 + 0.01),
        ],
        "large_amazon": [-53.5, -4.0, -47.5, 2.0],
        "empty_ocean": [0.0, -50.0, 0.01, -49.99],
        "source_batch_boundary": [
            float(boundary[:, 0].min()),
            float(boundary[:, 1].min()),
            float(boundary[:, 2].max()),
            float(boundary[:, 3].max()),
        ],
    }
    output: dict[str, Any] = {
        "source_graph": str(path),
        "rows": len(ids),
        "first_middle_last_graph_rows": [
            {"row": i, "id": int(ids[i]), "level": int(levels[i]), "bbox": coords[i].tolist()}
            for i in [0, len(ids) // 2, len(ids) - 1]
        ],
        "windows": {},
        "window_derivation": {
            "small_elongated": "center of original first graph row bbox",
            "large_amazon": "archived geographic discovery box, not certified watershed",
            "empty_ocean": "fixed southern Atlantic ocean box; emptiness checked from original bboxes",
            "source_batch_boundary": "union of original graph rows 255 and 256 bboxes; these straddle published 256-source-row organization, not candidate blocks",
        },
    }
    for name, window in windows.items():
        expanded = np.array(
            [np.nextafter(np.float32(v), np.float32(-np.inf if i < 2 else np.inf)) for i, v in enumerate(window)]
        )
        mask = (
            (coords[:, 0] <= expanded[2])
            & (coords[:, 1] <= expanded[3])
            & (coords[:, 2] >= expanded[0])
            & (coords[:, 3] >= expanded[1])
        )
        by_tier = {}
        for tier in np.unique(levels):
            selected = ids[mask & (levels == tier)]
            by_tier[str(int(tier))] = summary(selected)
        output["windows"][name] = {
            "bounds_epsg4326": window,
            "expanded_float32_bounds": expanded.tolist(),
            "all_tiers": summary(ids[mask]),
            "by_independent_domain_tier": by_tier,
        }
        assert name != "empty_ocean" or not np.any(mask)
    if flow:
        upstream = cast(pa.ListArray, table["upstream_ids"].combine_chunks())
        offsets = upstream.offsets.to_numpy()
        incoming = upstream.values.to_numpy()
        order = np.argsort(ids)
        sorted_ids = ids[order]

        def row(identity: int) -> int:
            slot = np.searchsorted(sorted_ids, identity)
            assert slot < len(sorted_ids) and sorted_ids[slot] == identity
            return int(order[slot])

        def walk(seed: int, reverse: bool) -> np.ndarray[Any, Any]:
            seen = {seed}
            queue = deque([seed])
            while queue:
                identity = queue.popleft()
                if reverse:
                    lo, hi = np.searchsorted(keys, identity, side="left"), np.searchsorted(keys, identity, side="right")
                    neighbors = ids[targets[lo:hi]]
                else:
                    i = row(identity)
                    neighbors = incoming[offsets[i] : offsets[i + 1]]
                for value in neighbors:
                    value = int(value)
                    if value not in seen:
                        seen.add(value)
                        queue.append(value)
            return np.array(sorted(seen), dtype=np.int64)

        up = walk(1233924, False)
        targets = np.repeat(np.arange(len(ids), dtype=np.int32), np.diff(offsets))
        permutation = np.argsort(incoming, kind="stable")
        keys = incoming[permutation]
        targets = targets[permutation]
        down = walk(4, True)
        assert len(down) == 1292 and digest(down) == "5fb738c5a64d2124695c5d8ddbc303815f072b4fce502e88aae15f6f790fed4f"
        assert len(up) == 88513 and digest(up) == "f019291d28c4279c8e9c05d29e0c9594e89da191b58808253194b2fee8f8dab4"
        output["flow"] = {
            "downstream_inclusive_4": summary(down),
            "upstream_inclusive_1233924": summary(up),
            "oracle": "original incoming graph; independent Python queue, reverse key sort; no candidate/prototype imports",
        }
        # Small complete geometry witnesses use original lookup; exact intersection only for selected witnesses.
        witnesses = select_original("rivers", [1, 4, 1233924])
        geometry = shapely.from_wkb(witnesses["geometry"].to_pylist())
        output["geometry_witnesses"] = record_witness(witnesses)
        output["geometry_witnesses"]["exact_intersects_windows"] = {
            name: shapely.intersects(geometry, shapely.box(*window)).tolist() for name, window in windows.items()
        }
    del table
    gc.collect()
    return output


def main() -> None:
    global ROOT, CATCHMENT_GRAPH, OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    ROOT, CATCHMENT_GRAPH, OUT = args.source, args.source / "graph.parquet", args.report
    if OUT.exists():
        raise FileExistsError(OUT)
    result: dict[str, Any] = {
        "scope": "source-only correctness inventory; no timing or candidate",
        "versions": {"pyarrow": pa.__version__, "numpy": np.__version__, "shapely": shapely.__version__},
        "manifest_sha256": hashlib.sha256((ROOT / "manifest.json").read_bytes()).hexdigest(),
        "hash_convention": "ID hashes SHA256 contiguous little-endian signed int64; Arrow stream hashes combine chunks with original projected/full schema; exact WKB hashes per row",
        "limitations": [
            "bbox overlap oracle is not exact geometry selection",
            "small selected geometry witnesses do not certify global intersections",
            "source order/batch-boundary windows are not candidate block boundaries",
            "source witnesses are selected records, not complete spatial certification",
        ],
    }
    result["rivers_records"] = original_rows("rivers")
    result["nodes_records"] = original_rows("nodes")
    result["catchments_records"] = original_rows("catchments")
    result["rivers_graph"] = graph_workloads(ROOT / "river-graph.parquet", True)
    result["catchments_graph"] = graph_workloads(CATCHMENT_GRAPH, False)
    result["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with OUT.open("x") as output:
        output.write(json.dumps(result, indent=2) + "\n")
    print(OUT)


if __name__ == "__main__":
    main()
