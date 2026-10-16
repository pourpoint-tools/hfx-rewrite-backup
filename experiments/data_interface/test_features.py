from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from experiments.data_interface.features import build_features, select_ids, spatial_ids, verify_features


def source_file(path: Path) -> pa.Table:
    bbox = pa.struct([pa.field(n, pa.float32(), False) for n in ("xmin", "ymin", "xmax", "ymax")])
    schema = pa.schema(
        [
            pa.field("id", pa.int64(), False),
            pa.field("level", pa.int16(), False),
            pa.field("bbox", bbox, False),
            pa.field("source_value", pa.int32()),
            pa.field("geometry", pa.binary(), False),
        ],
        metadata={b"custom": b"preserve"},
    )
    table = pa.Table.from_pylist(
        [
            {
                "id": 90,
                "level": 1,
                "bbox": {"xmin": 9.0, "ymin": 0.0, "xmax": 11.0, "ymax": 1.0},
                "source_value": None,
                "geometry": b"exact90",
            },
            {
                "id": 2,
                "level": 0,
                "bbox": {"xmin": -5.0, "ymin": 0.0, "xmax": 5.0, "ymax": 1.0},
                "source_value": 42,
                "geometry": b"exact2",
            },
            {
                "id": 700,
                "level": 1,
                "bbox": {"xmin": -11.0, "ymin": 0.0, "xmax": -9.0, "ymax": 1.0},
                "source_value": -7,
                "geometry": b"exact700",
            },
        ],
        schema=schema,
    )
    with ipc.new_file(str(path), schema, options=ipc.IpcWriteOptions(compression="zstd")) as writer:
        writer.write_table(table, max_chunksize=2)
    return table


def test_spatial_build_preserves_native_rows_and_selects_sparse_ids(tmp_path: Path) -> None:
    original = source_file(tmp_path / "source.arrow")
    output = tmp_path / "candidate"
    output.mkdir()
    declaration = build_features(tmp_path / "source.arrow", output, "rivers", rows=2)
    verify_features(tmp_path / "source.arrow", output, declaration)
    selected, absent = select_ids(output, declaration, [700, 3, 2, 700], ["geometry", "id", "source_value"])
    assert absent == [3]
    assert selected.column_names == ["geometry", "id", "source_value"]
    assert selected.to_pylist() == [
        {"geometry": b"exact700", "id": 700, "source_value": -7},
        {"geometry": b"exact2", "id": 2, "source_value": 42},
        {"geometry": b"exact700", "id": 700, "source_value": -7},
    ]
    assert selected.schema.metadata == original.schema.metadata
    assert spatial_ids(output, declaration, (4.0, 0.0, 6.0, 1.0), level=0) == [2]
    assert spatial_ids(output, declaration, (40.0, 0.0, 50.0, 1.0)) == []
    with pytest.raises(FileExistsError):
        build_features(tmp_path / "source.arrow", output, "rivers", rows=2)


def test_verifier_rejects_corrupted_spatial_directory(tmp_path: Path) -> None:
    import json

    source_file(tmp_path / "source.arrow")
    output = tmp_path / "candidate"
    output.mkdir()
    declaration = build_features(tmp_path / "source.arrow", output, "rivers", rows=2)
    path = output / declaration["spatial"]
    directory = json.loads(path.read_text())
    directory["batches"][0]["bbox"] = [100.0, 100.0, 101.0, 101.0]
    path.write_text(json.dumps(directory))
    with pytest.raises(ValueError, match="spatial"):
        verify_features(tmp_path / "source.arrow", output, declaration)
