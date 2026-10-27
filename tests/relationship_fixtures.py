"""Independent sparse relationship fixtures shared by production tests."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq


def _ipc(path: Path, columns: dict[str, list[object]], schema: pa.Schema) -> None:
    table = pa.table(columns, schema=schema)
    with ipc.new_file(str(path), schema) as writer:
        writer.write_table(table, max_chunksize=2)


def _source(path: Path) -> None:
    path.mkdir()
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "catchments": "catchments.arrow",
                "graph": "graph.parquet",
                "rivers": {"data": "rivers.arrow", "graph": "river-graph.parquet"},
                "river_nodes": {"data": "river-nodes.arrow"},
                "catchment_connectivity": [{"level": 0, "status": "not_supplied"}, {"level": 1, "status": "supplied"}],
            }
        )
    )
    _ipc(
        path / "catchments.arrow",
        {"id": [900, 70, 10, 40, 20], "parent_id": [None, 900, 900, 900, 900]},
        pa.schema([("id", pa.int64()), ("parent_id", pa.int64())]),
    )
    _ipc(
        path / "rivers.arrow",
        {
            "id": [70, 900, 20, 10, 40],
            "parent_id": [900, None, 900, 900, 900],
            "local_catchment_id": [70, None, 20, 10, 40],
            "component_catchment_id": [900, 900, 900, 900, 900],
            "upstream_node_id": [300, None, 200, 100, 200],
            "downstream_node_id": [400, None, 300, 200, 300],
        },
        pa.schema(
            [
                (name, pa.int64())
                for name in (
                    "id",
                    "parent_id",
                    "local_catchment_id",
                    "component_catchment_id",
                    "upstream_node_id",
                    "downstream_node_id",
                )
            ]
        ),
    )
    _ipc(
        path / "river-nodes.arrow",
        {"id": [400, 100, 500, 300, 200], "coarser_node_id": [500, 500, None, 500, 500]},
        pa.schema([("id", pa.int64()), ("coarser_node_id", pa.int64())]),
    )
    # Diamond: 10 -> {20, 40} -> 70. IDs overlap across the two domains.
    for filename in ("graph.parquet", "river-graph.parquet"):
        pq.write_table(
            pa.table(
                {
                    "id": pa.array([70, 900, 20, 10, 40], pa.int64()),
                    "upstream_ids": pa.array([[20, 40], [], [10], [], [10]], pa.list_(pa.int64())),
                }
            ),
            path / filename,
            row_group_size=2,
        )


def _records(output: Path, declaration: dict[str, object]) -> dict[int, dict[str, object]]:
    with ipc.open_file(str(output / str(declaration["data"]))) as reader:
        return {row["id"]: row for row in reader.read_all().to_pylist()}
