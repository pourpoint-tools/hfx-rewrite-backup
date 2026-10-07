"""Small independently worked examples for the experimental producer."""

from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest

from hfx.candidates import write_index


def test_index_sorts_sparse_ids_and_keeps_physical_addresses(tmp_path: Path) -> None:
    # Physical rows: group 0 = [90, 2], group 1 = [700, 13].
    directory = write_index(tmp_path / "lookup.arrow", [pa.array([90, 2]), pa.array([700, 13])], "abc", "a-index", 2)
    with ipc.open_file(tmp_path / "lookup.arrow") as reader:
        assert reader.schema == pa.schema(
            [
                pa.field("id", pa.int64(), nullable=False),
                pa.field("block", pa.int32(), nullable=False),
                pa.field("row", pa.int32(), nullable=False),
            ]
        )
        assert reader.read_all().to_pydict() == {"id": [2, 13, 90, 700], "block": [0, 1, 0, 1], "row": [1, 1, 0, 0]}
        assert reader.num_record_batches == 2
        assert reader.schema.metadata[b"hfx:catchments_sha256"] == b"abc"
    assert directory == {
        "version": 1,
        "batches": [
            {"batch": 0, "min_id": 2, "max_id": 13, "rows": 2},
            {"batch": 1, "min_id": 90, "max_id": 700, "rows": 2},
        ],
    }


@pytest.mark.parametrize("ids", [[1, 1], [0, 2], [-1, 3], [1, None]])
def test_index_rejects_invalid_identity(tmp_path: Path, ids: list[int | None]) -> None:
    with pytest.raises(ValueError, match="positive, unique, non-null"):
        write_index(tmp_path / "lookup.arrow", [pa.array(ids, type=pa.int64())], "abc", "a-index", 2)


def test_arrow_budget_preserves_schema_nulls_order_and_oversized_wkb(tmp_path: Path) -> None:
    import struct

    from hfx.candidates import write_catchments

    # Valid polygon WKB with many repeated vertices makes a single oversized row.
    def polygon(vertices: int) -> bytes:
        return struct.pack("<BIII", 1, 3, 1, vertices) + struct.pack("<dd", 1.0, 2.0) * vertices

    schema = pa.schema(
        [
            pa.field("id", pa.int64(), nullable=False),
            pa.field("parent_id", pa.int64()),
            pa.field("geometry", pa.binary(), nullable=False),
            pa.field("source_id", pa.string()),
        ],
        metadata={b"geo": b'{"crs":"EPSG:4326","encoding":"WKB"}'},
    )
    table = pa.Table.from_pylist(
        [
            {"id": 90, "parent_id": None, "geometry": polygon(4), "source_id": "ninety"},
            {"id": 2, "parent_id": 90, "geometry": polygon(4), "source_id": None},
            {"id": 700, "parent_id": 90, "geometry": polygon(100), "source_id": "big"},
            {"id": 13, "parent_id": 2, "geometry": polygon(4), "source_id": "last"},
        ],
        schema=schema,
    )
    pq.write_table(table, tmp_path / "source.parquet", row_group_size=2)
    ids = write_catchments(pq.ParquetFile(tmp_path / "source.parquet"), tmp_path / "catchments.arrow", 250)
    assert [a.to_pylist() for a in ids] == [[90, 2], [700], [13]]
    with ipc.open_file(tmp_path / "catchments.arrow") as reader:
        assert reader.schema.equals(schema, check_metadata=True)
        assert reader.read_all().equals(table, check_metadata=True)
        assert [reader.get_batch(i).num_rows for i in range(3)] == [2, 1, 1]
        assert reader.get_batch(0).nbytes <= 250
        assert reader.get_batch(1).nbytes > 250
        assert reader.get_batch(2).nbytes <= 250


def test_complete_bundles_preserve_source_and_refuse_existing_paths(tmp_path: Path) -> None:
    import json

    from hfx.candidates import build, fingerprint

    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps({"format_version": "0.3.0", "unit_count": 3, "crs": "EPSG:4326"}))
    (source / "ATTRIBUTION_AND_PROVENANCE.txt").write_text("internal use only")
    (source / "aux").mkdir()
    (source / "aux/snap_stems.parquet").write_bytes(b"unchanged snap fixture")
    (source / "graph.parquet").write_bytes(b"unchanged graph fixture")
    pq.write_table(
        pa.table({"id": pa.array([90, 2, 700], type=pa.int64()), "geometry": [b"a", b"bb", b"ccc"]}),
        source / "catchments.parquet",
        row_group_size=2,
    )
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    a, b = tmp_path / "a", tmp_path / "b"
    build(source, a, b, index_batch_rows=2, catchment_batch_bytes=32)
    assert before == {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert (a / "catchments.parquet").read_bytes() == before[Path("catchments.parquet")]
    assert not (b / "catchments.parquet").exists()
    for output, identity, data in [(a, "a-index", "catchments.parquet"), (b, "b-arrow", "catchments.arrow")]:
        manifest = json.loads((output / "manifest.json").read_text())
        assert manifest["experimental"] is True
        assert manifest["format_version"] == "0.4.0"
        assert manifest["candidate"] == identity
        assert manifest["catchments"] == data
        for relative, value in before.items():
            if str(relative) not in {"manifest.json", "catchments.parquet"}:
                assert (output / relative).read_bytes() == value
        assert (output / "source-manifest.json").read_bytes() == before[Path("manifest.json")]
        for relative, identity in manifest["artifacts"].items():
            assert fingerprint(output / relative) == identity
    with pytest.raises(FileExistsError):
        build(source, a, b)
    assert before == {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}


def test_overlapping_destinations_are_rejected_before_writing(tmp_path: Path) -> None:
    from hfx.candidates import build

    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="disjoint"):
        build(source, source / "a", tmp_path / "b")
    with pytest.raises(ValueError, match="disjoint"):
        build(source, tmp_path / "a", tmp_path / "a/b")
    assert list(source.iterdir()) == []
