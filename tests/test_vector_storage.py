"""Typed batches and disk-backed address ordering, without source-specific schemas."""

from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest


def test_typed_batches_preserve_values_and_sort_addresses(tmp_path: Path) -> None:
    from hfx.vector_storage import write_vectors

    schema = pa.schema(
        [pa.field("id", pa.int64(), nullable=False), pa.field("value", pa.int16()), pa.field("geometry", pa.binary())],
        metadata={b"source": b"fixture"},
    )
    table = pa.Table.from_pylist(
        [
            {"id": 90, "value": None, "geometry": b"a"},
            {"id": 2, "value": 7, "geometry": b"b" * 200},
            {"id": 700, "value": 3, "geometry": None},
            {"id": 13, "value": 4, "geometry": b"c"},
        ],
        schema=schema,
    )
    directory = write_vectors(
        schema,
        iter(table.to_batches(max_chunksize=2)),
        tmp_path / "data.arrow",
        tmp_path / "lookup.arrow",
        batch_bytes=60,
        index_batch_rows=2,
    )
    with ipc.open_file(tmp_path / "data.arrow") as reader:
        assert reader.read_all().equals(table, check_metadata=True)
        assert [reader.get_batch(i).num_rows for i in range(reader.num_record_batches)] == [1, 1, 2]
        assert reader.get_batch(1).nbytes > 60
    with ipc.open_file(tmp_path / "lookup.arrow") as reader:
        from hashlib import sha256

        assert reader.read_all().to_pydict() == {"id": [2, 13, 90, 700], "block": [1, 2, 0, 2], "row": [0, 1, 0, 0]}
        assert reader.schema.metadata == {
            b"hfx:data_sha256": sha256((tmp_path / "data.arrow").read_bytes()).hexdigest().encode(),
            b"hfx:format_version": b"0.4.0",
        }
    assert directory == {
        "version": 1,
        "batches": [
            {"batch": 0, "min_id": 2, "max_id": 13, "rows": 2},
            {"batch": 1, "min_id": 90, "max_id": 700, "rows": 2},
        ],
    }
    assert sorted(p.name for p in tmp_path.iterdir()) == ["data.arrow", "lookup.arrow"]


@pytest.mark.parametrize(
    "ids",
    [
        pa.array([1, 1], type=pa.int64()),
        pa.array([1, None], type=pa.int64()),
        pa.array([1, 0], type=pa.int64()),
        pa.array([1, 2], type=pa.int32()),
    ],
)
def test_invalid_ids_fail_without_coercion_and_clean_own_scratch(tmp_path: Path, ids: pa.Array) -> None:
    from hfx.vector_storage import write_vectors

    table = pa.table({"id": ids})
    sentinel = tmp_path / "existing.sqlite"
    sentinel.write_bytes(b"unrelated")
    with pytest.raises(ValueError, match="int64|positive, unique, non-null"):
        write_vectors(
            table.schema, iter(table.to_batches(max_chunksize=1)), tmp_path / "data.arrow", tmp_path / "lookup.arrow"
        )
    assert sentinel.read_bytes() == b"unrelated"
    assert not list(tmp_path.glob("hfx-addresses-*"))
    if ids.type == pa.int64():
        assert (tmp_path / "data.arrow").exists()


def test_streaming_catchments_keep_historical_lookup_binding(tmp_path: Path) -> None:
    from hashlib import sha256

    from hfx.vector_storage import write_vectors

    table = pa.table({"id": pa.array([9, 2], type=pa.int64())})
    write_vectors(
        table.schema,
        iter(table.to_batches(max_chunksize=1)),
        tmp_path / "data.arrow",
        tmp_path / "lookup.arrow",
        lookup_binding="hfx:catchments_sha256",
    )
    with ipc.open_file(tmp_path / "lookup.arrow") as reader:
        assert reader.schema.metadata == {
            b"hfx:catchments_sha256": sha256((tmp_path / "data.arrow").read_bytes()).hexdigest().encode(),
            b"hfx:format_version": b"0.4.0",
        }
