from __future__ import annotations

import pyarrow as pa

from experiments.data_interface.oracles.source_node_spatial import selected


def test_point_boundary_null_correspondence_and_separate_tier() -> None:
    bbox_type = pa.struct([pa.field(name, pa.float32(), False) for name in ["xmin", "ymin", "xmax", "ymax"]])
    table = pa.table(
        {
            "id": pa.array([41, 7, 90], type=pa.int64()),
            "level": pa.array([0, 1, 1], type=pa.int16()),
            "coarser_node_id": pa.array([None, 41, None], type=pa.int64()),
            "bbox": pa.array([{"xmin": x, "ymin": x, "xmax": x, "ymax": x} for x in [1.0, 1.0, 3.0]], type=bbox_type),
        }
    )
    sink = pa.BufferOutputStream()
    with pa.ipc.new_file(sink, table.schema) as writer:
        writer.write_table(table, max_chunksize=2)
    reader = pa.ipc.open_file(sink.getvalue())
    rows = selected(reader, [1.0, 1.0, 1.0, 1.0])
    assert rows["id"].to_pylist() == [41, 7]
    assert rows["coarser_node_id"].to_pylist() == [None, 41]
    assert selected(reader, [1.0, 1.0, 1.0, 1.0], 1)["id"].to_pylist() == [7]
    assert selected(reader, [8.0, 8.0, 9.0, 9.0]).num_rows == 0
