"""Original node spatial oracle: projected IPC scan, no node graph/index inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import cast

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

COLUMNS = ["id", "level", "bbox", "coarser_node_id"]


def selected(reader: pa.ipc.RecordBatchFileReader, bbox: list[float], tier: int | None = None) -> pa.Table:
    pieces: list[pa.RecordBatch] = []
    for i in range(reader.num_record_batches):
        batch = reader.get_batch(i)
        bounds = cast(pa.StructArray, batch["bbox"])
        x0, y0, x1, y1 = [bounds.field(name).to_numpy() for name in ["xmin", "ymin", "xmax", "ymax"]]
        mask = (x0 <= bbox[2]) & (y0 <= bbox[3]) & (x1 >= bbox[0]) & (y1 >= bbox[1])
        if tier is not None:
            mask &= batch["level"].to_numpy() == tier
        if np.any(mask):
            pieces.append(batch.filter(mask))
    return pa.Table.from_batches(pieces, schema=reader.schema)


def table_hash(table: pa.Table) -> str:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table.combine_chunks())
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    if args.report.resolve().is_relative_to(args.source.resolve()):
        raise ValueError("report must be outside input bundle")
    manifest_bytes = (args.source / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    data_name = manifest["river_nodes"]["data"]
    with pa.OSFile(str(args.source / data_name), "rb") as stream:
        full = pa.ipc.open_file(stream)
        source_schema = full.schema
        bootstrap_options = pa.ipc.IpcReadOptions(
            included_fields=[source_schema.get_field_index(name) for name in ["id", "bbox"]]
        )
        first = pa.ipc.open_file(stream, options=bootstrap_options).get_batch(0)
        point = first["bbox"][0].as_py()
        x, y = (point["xmin"] + point["xmax"]) / 2, (point["ymin"] + point["ymax"]) / 2
        bbox = [x - 0.01, y - 0.01, x + 0.01, y + 0.01]
        expanded = [
            float(np.nextafter(np.float32(v), np.float32(-np.inf if i < 2 else np.inf))) for i, v in enumerate(bbox)
        ]
        options = pa.ipc.IpcReadOptions(included_fields=[source_schema.get_field_index(name) for name in COLUMNS])
        projected = pa.ipc.open_file(stream, options=options)
        table = selected(projected, expanded)
        ids = table["id"].to_numpy()
        result = {
            "scope": "independent source-only node bbox scan, not an index or geometry policy",
            "family": "nodes",
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "data": data_name,
            "data_fingerprint": manifest["artifacts"][data_name],
            "source_schema_sha256": hashlib.sha256(source_schema.serialize().to_pybytes()).hexdigest(),
            "projection_schema_sha256": hashlib.sha256(table.schema.serialize().to_pybytes()).hexdigest(),
            "projection_arrow_sha256": table_hash(table),
            "columns": COLUMNS,
            "window": {
                "label": "first_source_node",
                "bbox": bbox,
                "expanded_float32_bbox": expanded,
                "derivation": "0.01 degree radius around first original source-node bbox center",
                "witness_node_id": first["id"][0].as_py(),
            },
            "count": table.num_rows,
            "sorted_ids_sha256_le_i64": hashlib.sha256(np.sort(ids).astype("<i8").tobytes()).hexdigest(),
            "rows": table.to_pylist(),
            "by_tier": {},
            "interpretation": "coarser_node_id is cross-tier correspondence; no parent/flow/incidence inference. Original publication has no node graph/spatial index; entire bbox projection scanned.",
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "pyarrow_version": pa.__version__,
        }
        for tier in np.unique(table["level"].to_numpy()):
            subset = table.filter(pc.equal(table["level"], pa.scalar(int(tier), type=pa.int16())))
            result["by_tier"][str(int(tier))] = {
                "count": subset.num_rows,
                "sorted_ids_sha256_le_i64": hashlib.sha256(
                    np.sort(subset["id"].to_numpy()).astype("<i8").tobytes()
                ).hexdigest(),
            }
    with args.report.open("x") as output:
        output.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
