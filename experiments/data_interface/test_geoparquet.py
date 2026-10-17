import json
import struct
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest

from experiments.data_interface.geoparquet import (
    GeoParquetAccess,
    exact_array,
    main,
    verify_geoparquet,
    wkb_type,
    write_geoparquet,
)
from hfx.candidates import fingerprint


def source_file(root: Path) -> Path:
    root = root / "input"
    root.mkdir()
    path = root / "rivers.arrow"
    bbox = pa.struct(
        [pa.field(n, pa.float32(), False, metadata={b"unit": b"degree"}) for n in ("xmin", "ymin", "xmax", "ymax")]
    )
    schema = pa.schema(
        [
            pa.field("id", pa.int64(), False),
            pa.field("level", pa.int16(), False),
            pa.field("bbox", bbox, False),
            pa.field("native", pa.float64(), metadata={b"source": b"native"}),
            pa.field("geometry", pa.binary(), False),
        ],
        metadata={b"source": b"unchanged"},
    )
    points = [struct.pack("<BIdd", 1, 1, x, 0.0) for x in (1.0, 2.0, 3.0)]
    table = pa.Table.from_pylist(
        [
            {
                "id": i + 1,
                "level": i % 2,
                "bbox": {"xmin": float(i + 1), "ymin": 0.0, "xmax": float(i + 1), "ymax": 0.0},
                "native": value,
                "geometry": points[i],
            }
            for i, value in enumerate([-0.0, None, float("nan")])
        ],
        schema=schema,
    )
    with ipc.new_file(str(path), schema) as writer:
        writer.write_batch(table.slice(0, 2).to_batches()[0])
        writer.write_batch(table.slice(2).to_batches()[0])
    (root / "manifest.json").write_text(json.dumps({"artifacts": {path.name: fingerprint(path)}}))
    return path


def test_exact_native_roundtrip_and_actual_group_boundaries(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    output = tmp_path / "rivers.parquet"
    receipt = write_geoparquet(source, output)
    result = verify_geoparquet(source, output, receipt)
    assert result["rows"] == 3
    assert result["row_group_rows"] == [2, 1]
    parquet = pq.ParquetFile(output)
    geo = json.loads(parquet.schema_arrow.metadata[b"geo"])
    assert geo["version"] == "1.1.0"
    assert geo["columns"]["geometry"]["geometry_types"] == []
    assert "crs" not in geo["columns"]["geometry"]  # Default CRS84, longitude/latitude.
    assert geo["columns"]["geometry"]["covering"]["bbox"]["xmin"] == ["bbox", "xmin"]
    for index in range(parquet.metadata.num_columns):
        column = parquet.metadata.row_group(0).column(index)
        assert column.compression == "ZSTD"
        assert column.is_stats_set == column.path_in_schema.startswith("bbox.")
        if column.path_in_schema == "geometry":
            assert "RLE_DICTIONARY" not in column.encodings
    with pytest.raises(FileExistsError):
        write_geoparquet(source, output)


@pytest.mark.parametrize("change", ["boundary", "metadata"])
def test_verifier_rejects_changed_boundaries_or_schema(tmp_path: Path, change: str) -> None:
    source = source_file(tmp_path)
    output = tmp_path / "rivers.parquet"
    receipt = write_geoparquet(source, output)
    table = pq.ParquetFile(output).read()
    if change == "metadata":
        table = table.replace_schema_metadata({**table.schema.metadata, b"source": b"changed"})
    pq.write_table(table, output, row_group_size=1 if change == "boundary" else 2)
    receipt["artifact"] = fingerprint(output)
    with pytest.raises(ValueError, match="(row group|schema)"):
        verify_geoparquet(source, output, receipt)


def test_float_verification_preserves_nan_payload_and_signed_zero() -> None:
    def floats(bits: list[int]) -> pa.Array:
        return pa.array(bits, type=pa.uint64()).view(pa.float64())

    assert exact_array(floats([0x7FF8000000000001]), floats([0x7FF8000000000001]))
    assert not exact_array(floats([0x7FF8000000000001]), floats([0x7FF8000000000002]))
    assert not exact_array(floats([0]), floats([0x8000000000000000]))


def test_verifier_rejects_changed_geometry_and_binding(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    output = tmp_path / "rivers.parquet"
    receipt = write_geoparquet(source, output)
    bad = dict(receipt, source_artifact_sha256="0" * 64)
    with pytest.raises(ValueError, match="binding"):
        verify_geoparquet(source, output, bad)
    table = pq.ParquetFile(output).read()
    table = table.set_column(
        table.schema.get_field_index("geometry"), table.schema.field("geometry"), pa.array([b"wrong"] * 3)
    )
    pq.write_table(table, output, row_group_size=2)
    with pytest.raises(ValueError, match="artifact"):
        verify_geoparquet(source, output, receipt)
    # Rebinding corrupted bytes must not evade the independent full-row comparison.
    receipt["artifact"] = fingerprint(output)
    with pytest.raises(ValueError, match="geometry"):
        verify_geoparquet(source, output, receipt)


@pytest.mark.parametrize("code", [1, 2, 3, 4, 5, 6, 7, 1001, 1007])
def test_wkb_type_accepts_standard_2d_and_z(code: int) -> None:
    assert wkb_type(struct.pack(">BI", 0, code)) == code


@pytest.mark.parametrize("code", [0, 8, 2001, 3001, 0x80000001, 0x20000001])
def test_wkb_type_rejects_m_nonlinear_and_ewkb(code: int) -> None:
    with pytest.raises(ValueError, match="WKB"):
        wkb_type(struct.pack("<BI", 1, code))


def test_output_cannot_mutate_input_bundle(tmp_path: Path) -> None:
    source = source_file(tmp_path)
    with pytest.raises(ValueError, match="source bundle"):
        write_geoparquet(source, source.parent / "new.parquet")


def test_retained_parquet_reader_spatial_and_known_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_file(tmp_path)
    lookup_schema = pa.schema(
        [pa.field("id", pa.int64(), False), pa.field("block", pa.int32(), False), pa.field("row", pa.int32(), False)],
        metadata={b"hfx:data_sha256": fingerprint(source)["sha256"].encode()},
    )
    with ipc.new_file(str(source.parent / "lookup.arrow"), lookup_schema) as writer:
        writer.write_batch(
            pa.RecordBatch.from_arrays(
                [pa.array([1, 2, 3]), pa.array([0, 0, 1], type=pa.int32()), pa.array([0, 1, 0], type=pa.int32())],
                schema=lookup_schema,
            )
        )
    (source.parent / "directory.json").write_text(
        json.dumps({"batches": [{"batch": 0, "min_id": 1, "max_id": 3, "rows": 3}]})
    )
    manifest = {
        "families": {"rivers": {"data": source.name, "lookup": "lookup.arrow", "directory": "directory.json"}},
        "artifacts": {p.name: fingerprint(p) for p in source.parent.iterdir() if p.name != "manifest.json"},
    }
    original = tmp_path / "original"
    original.mkdir()
    for name in (source.name, "lookup.arrow", "directory.json"):
        (original / name).write_bytes((source.parent / name).read_bytes())
    original_manifest = {"rivers": manifest["families"]["rivers"]}
    (original / "manifest.json").write_text(json.dumps(original_manifest))
    import hashlib

    manifest["input_manifest_sha256"] = hashlib.sha256((original / "manifest.json").read_bytes()).hexdigest()
    (source.parent / "manifest.json").write_text(json.dumps(manifest))
    output = tmp_path / "rivers.parquet"
    receipt = write_geoparquet(source, output)
    with pytest.raises(ValueError, match="candidate source binding"):
        GeoParquetAccess(str(output), str(source.parent), {**receipt, "source_artifact_sha256": "0" * 64})
    access = GeoParquetAccess(str(output), str(source.parent), receipt)
    try:
        selected = access.spatial((1.5, -1.0, 2.5, 1.0), ["geometry", "id"])
        assert selected.column("id").to_pylist() == [2]
        assert selected.column_names == ["geometry", "id"]
        assert access.last_groups == [0]
        table, absent = access.ids([3, 4, 1, 3], ["id", "geometry"])
        assert table.column("id").to_pylist() == [3, 1, 3]
        assert absent == [4]
        missing, absent = access.ids([40], ["geometry", "id"])
        assert missing.num_rows == 0 and absent == [40]
        with pytest.raises(ValueError, match="selected ID"):
            access.records({0: [(0, 3)]}, ["id"])
        with pytest.raises(ValueError, match="out of bounds"):
            access.records({0: [(2, 1)]}, ["id"])
        assert access.stats()["local_read_calls"] > 0
        reader = access.reader
        empty = access.spatial((20.0, 0.0, 21.0, 1.0), ["id"])
        assert empty.num_rows == 0
        assert access.reader is reader
    finally:
        access.close()
    from experiments.data_interface.geoparquet_probe import measure

    bundle = tmp_path / "derived"
    bundle.mkdir()
    (bundle / output.name).write_bytes(output.read_bytes())
    (bundle / "manifest.json").write_text(
        json.dumps({"artifact": output.name, "binding": receipt, "verification": {"status": "passed"}})
    )
    result = measure(str(bundle), str(source.parent), original, ["geometry", "id", "native"], [2, 1, 2], 2)
    assert [item["output_rows"] for item in result["repeats"]] == [3, 3]
    assert all(item["validation"]["semantic_equal"] for item in result["repeats"])
    assert result["opening"]["local_read_calls"] > 0
    from experiments.data_interface.record_probe import id_hash

    window = {
        "bounds_epsg4326": [1.5, -1.0, 2.5, 1.0],
        "all_tiers": {"count": 1, "sorted_ids_sha256_le_i64": id_hash([2])},
    }
    import numpy as np
    import numpy.typing as npt
    import shapely

    from experiments.data_interface import geoparquet_probe

    events: list[str] = []
    from_wkb = shapely.from_wkb
    source_records = geoparquet_probe.source_records

    def decode(wkb: npt.NDArray[np.object_]) -> npt.NDArray[np.object_]:
        geometries = from_wkb(wkb)
        assert shapely.to_wkt(geometries).tolist() == ["POINT (2 0)"]
        events.append("decode")
        return geometries

    def validate_source(
        root: Path, family: str, ids: list[int], columns: list[str] | None
    ) -> tuple[pa.Table, list[int]]:
        events.append("source_records")
        return source_records(root, family, ids, columns)

    monkeypatch.setattr(shapely, "from_wkb", decode)
    monkeypatch.setattr(geoparquet_probe, "source_records", validate_source)
    spatial = measure(
        str(bundle), str(source.parent), original, ["geometry", "id", "native"], [], 2, window, decode=True
    )
    assert events == ["decode", "source_records", "decode", "source_records"]
    assert spatial["phase"] == "spatial_discovery_and_fetch"
    for index, item in enumerate(spatial["repeats"]):
        assert item["output_rows"] == 1
        assert item["validation"]["semantic_equal"]
        assert item["requested_wkb_bytes"] == 21
        assert item["geometry_decode_s"] > 0
        assert item["total_to_result_s"] == pytest.approx(
            item["acquisition"]["elapsed_s"] + item["geometry_decode_s"] + (spatial["opening_s"] if index == 0 else 0)
        )


def test_cli_rejects_receipt_output_collision_before_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = source_file(tmp_path)
    output = tmp_path / "rivers.parquet"
    monkeypatch.setattr(
        sys, "argv", ["geoparquet", str(source), str(output), "--receipt", str(output.parent / "." / output.name)]
    )
    with pytest.raises(ValueError, match="receipt.*output"):
        main()
    assert not output.exists()


def test_probe_removes_only_exact_additive_geo_metadata(tmp_path: Path) -> None:
    from experiments.data_interface.geoparquet_probe import source_schema_table

    source = source_file(tmp_path)
    output = tmp_path / "rivers.parquet"
    write_geoparquet(source, output)
    actual = pq.ParquetFile(output).read().select(["geometry", "id", "native"])
    expected = ipc.open_file(str(source)).read_all().select(["geometry", "id", "native"])
    restored = source_schema_table(actual)
    assert restored.schema.equals(expected.schema, check_metadata=True)
    assert all(
        exact_array(restored.column(name).combine_chunks(), expected.column(name).combine_chunks())
        for name in expected.column_names
    )
    changed = actual.replace_schema_metadata({**actual.schema.metadata, b"source": b"changed"})
    assert not source_schema_table(changed).schema.equals(expected.schema, check_metadata=True)
    with pytest.raises(ValueError, match="geo metadata"):
        source_schema_table(actual.replace_schema_metadata({**actual.schema.metadata, b"geo": b"{}"}))
