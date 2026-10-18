"""Production layout preserves original native values across reordered domains."""

import json
import struct
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest

from hfx.spatial_features import build_features, verify_features


def source_file(path: Path, family: str) -> Path:
    schema = pa.schema(
        [
            pa.field("id", pa.int64(), False),
            pa.field("level", pa.int8(), False),
            pa.field(
                "bbox", pa.struct([pa.field(n, pa.float32(), False) for n in ("xmin", "ymin", "xmax", "ymax")]), False
            ),
            pa.field("geometry", pa.binary(), False),
            pa.field("value", pa.float64()),
            pa.field("label", pa.string()),
        ],
        metadata={b"family": family.encode()},
    )
    bits = np.array([0x8000000000000000, 0x7FF8000000000042, 0, 0x3FF0000000000000], dtype=np.uint64)

    def geometry(x: float) -> bytes:
        header = struct.pack("<BI", 1, {"nodes": 1, "rivers": 2, "catchments": 3}[family])
        if family == "nodes":
            return header + struct.pack("<dd", x, 0.0)
        if family == "rivers":
            return header + struct.pack("<I4d", 2, x, 0.0, x + 1.0, 1.0)
        return header + struct.pack("<II10d", 1, 5, x, 0.0, x + 1.0, 0.0, x + 1.0, 1.0, x, 1.0, x, 0.0)

    batch = pa.RecordBatch.from_arrays(
        [
            pa.array([9, 1, 7, 3]),
            pa.array([2, 1, 1, 2], type=pa.int8()),
            pa.array(
                [
                    dict(zip(("xmin", "ymin", "xmax", "ymax"), [x, 0.0, x + 1.0, 1.0], strict=True))
                    for x in [10.0, -10.0, 0.0, 20.0]
                ],
                type=schema.field("bbox").type,
            ),
            pa.array([geometry(x) for x in [10.0, -10.0, 0.0, 20.0]]),
            pa.array(bits.view(np.float64), mask=np.array([False, False, True, False])),
            pa.array(["a", None, "c", "d"]),
        ],
        schema=schema,
    )
    with ipc.new_file(str(path), schema) as writer:
        writer.write_batch(batch.slice(0, 2))
        writer.write_batch(batch.slice(2))
    return path


@pytest.mark.parametrize("family", ["nodes", "rivers", "catchments"])
def test_native_reordering(tmp_path: Path, family: str) -> None:
    source = source_file(tmp_path / "source.arrow", family)
    output = tmp_path / "out"
    output.mkdir()
    declaration = build_features(source, output, family, rows=2, budget=200)
    assert verify_features(source, output, declaration)["rows"] == 4
    parquet = pq.ParquetFile(output / declaration["data"])
    assert parquet.read(columns=["id"]).column("id").to_pylist() == [1, 7, 9, 3]
    assert json.loads(parquet.schema_arrow.metadata[b"geo"])["version"] == "1.1.0"
    lookup = ipc.open_file(str(output / declaration["lookup"]))
    assert lookup.read_all().column("id").to_pylist() == [1, 3, 7, 9]  # interior ID 5 is absent
    assert lookup.schema.metadata[b"hfx:data_sha256"].decode() == declaration["data_sha256"]
    assert not list(output.glob("*spatial.json"))


def test_verifier_rejects_native_float_change(tmp_path: Path) -> None:
    from hfx.candidates import fingerprint

    source = source_file(tmp_path / "source.arrow", "nodes")
    output = tmp_path / "out"
    output.mkdir()
    declaration = build_features(source, output, "nodes", rows=2)
    data = output / declaration["data"]
    table = pq.read_table(data)
    values = table.column("value").combine_chunks().to_numpy(zero_copy_only=False).copy()
    values[0] = float("nan")  # same NaN meaning, different original payload
    table = table.set_column(
        table.schema.get_field_index("value"),
        table.schema.field("value"),
        pa.array(values, mask=table.column("value").is_null().to_numpy()),
    )
    pq.write_table(table, data, row_group_size=2)
    digest = fingerprint(data)["sha256"]
    declaration["data_sha256"] = digest
    lookup_path = output / declaration["lookup"]
    lookup = ipc.open_file(str(lookup_path)).read_all().replace_schema_metadata({b"hfx:data_sha256": digest.encode()})
    with ipc.new_file(str(lookup_path), lookup.schema) as writer:
        writer.write_table(lookup)
    with pytest.raises(ValueError, match="source column value differs"):
        verify_features(source, output, declaration)


def test_verifier_rejects_invalid_locator(tmp_path: Path) -> None:
    source = source_file(tmp_path / "source.arrow", "nodes")
    output = tmp_path / "out"
    output.mkdir()
    declaration = build_features(source, output, "nodes", rows=2)
    path = output / declaration["lookup"]
    lookup = ipc.open_file(str(path)).read_all()
    lookup = lookup.set_column(2, lookup.schema.field("row"), pa.array([99, 0, 1, 0], type=pa.int32()))
    with ipc.new_file(str(path), lookup.schema) as writer:
        writer.write_table(lookup)
    with pytest.raises(ValueError, match="address out of bounds"):
        verify_features(source, output, declaration)


def test_verifier_requires_spatial_statistics(tmp_path: Path) -> None:
    from hfx.candidates import fingerprint

    source = source_file(tmp_path / "source.arrow", "catchments")
    output = tmp_path / "out"
    output.mkdir()
    declaration = build_features(source, output, "catchments", rows=2)
    data = output / declaration["data"]
    table = pq.read_table(data)
    pq.write_table(table, data, row_group_size=2, write_statistics=False)
    digest = fingerprint(data)["sha256"]
    declaration["data_sha256"] = digest
    path = output / declaration["lookup"]
    lookup = ipc.open_file(str(path)).read_all().replace_schema_metadata({b"hfx:data_sha256": digest.encode()})
    with ipc.new_file(str(path), lookup.schema) as writer:
        writer.write_table(lookup)
    with pytest.raises(ValueError, match="bbox statistics"):
        verify_features(source, output, declaration)


def test_verifier_rejects_locator_schema_change(tmp_path: Path) -> None:
    source = source_file(tmp_path / "source.arrow", "nodes")
    output = tmp_path / "out"
    output.mkdir()
    declaration = build_features(source, output, "nodes", rows=2)
    path = output / declaration["lookup"]
    lookup = ipc.open_file(str(path)).read_all()
    schema = lookup.schema.set(0, pa.field("id", pa.int64(), nullable=True))
    changed = pa.Table.from_arrays(lookup.columns, schema=schema)
    with ipc.new_file(str(path), schema) as writer:
        writer.write_table(changed)
    with pytest.raises(ValueError, match="lookup schema"):
        verify_features(source, output, declaration)
