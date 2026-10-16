import json
import struct
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest

from experiments.data_interface.geoparquet import exact_array, verify_geoparquet, wkb_type, write_geoparquet
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
