from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from experiments.data_interface.relation_baseline import prepare, reverse


def test_sparse_nullable_reverse(tmp_path: Path) -> None:
    path = tmp_path / "source.arrow"
    table = pa.table(
        {
            "id": pa.array([90, 10, 47, 800], type=pa.int64()),
            "parent_id": pa.array([800, None, 800, None], type=pa.int64()),
            "geometry": [b"a", b"b", b"c", b"d"],
        }
    )
    with pa.ipc.new_file(str(path), table.schema) as writer:
        writer.write_table(table)
    projected, keys, ids, _ = prepare(path, "parent_id")
    assert projected.column_names == ["id", "parent_id"]
    assert projected["parent_id"].to_pylist() == [800, None, 800, None]
    np.testing.assert_array_equal(reverse(keys, ids, 800), [47, 90])
    np.testing.assert_array_equal(reverse(keys, ids, 123), [])
    with pytest.raises(ValueError, match="missing source column"):
        prepare(path, "absent")


@pytest.mark.parametrize("driver", ["scan", "reverse"])
def test_measurement_receipts_cannot_write_into_source_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, driver: str
) -> None:
    import sys

    from experiments.data_interface import baseline_column_scan, relation_baseline

    source = tmp_path / "source"
    source.mkdir()
    path = source / "rivers.arrow"
    table = pa.table({"id": [10, 20], "parent_id": pa.array([None, 10], type=pa.int64())})
    with pa.ipc.new_file(str(path), table.schema) as writer:
        writer.write_table(table)
    receipt = source / "receipt.json"
    if driver == "scan":
        argv = [
            "scan",
            str(path),
            str(receipt),
            "--columns",
            "parent_id",
            "--mode",
            "projected",
            "--expected-rows",
            "2",
        ]
        main = baseline_column_scan.main
    else:
        argv = ["reverse", str(path), "--column", "parent_id", "--targets", "10", "--report", str(receipt)]
        main = relation_baseline.main
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(ValueError, match="outside.*bundle"):
        main()
    assert not receipt.exists()
