from pathlib import Path

from experiments.data_interface.features import build_features
from experiments.data_interface.probe import Access
from experiments.data_interface.test_features import source_file
from hfx.candidates import fingerprint


def test_instrumented_selected_and_spatial_access(tmp_path: Path) -> None:
    import json

    source_file(tmp_path / "source.arrow")
    target = tmp_path / "candidate"
    target.mkdir()
    declaration = build_features(tmp_path / "source.arrow", target, "rivers", rows=2)
    artifacts = {p.name: fingerprint(p) for p in target.iterdir()}
    (target / "manifest.json").write_text(
        json.dumps({"experimental": True, "families": {"rivers": declaration}, "artifacts": artifacts})
    )
    access = Access(str(target), "rivers", ["source_value", "id"])
    selected, absent = access.ids([700, 3, 2, 700])
    assert absent == [3]
    assert selected.to_pylist() == [
        {"source_value": -7, "id": 700},
        {"source_value": 42, "id": 2},
        {"source_value": -7, "id": 700},
    ]
    assert access.stats()["data_blocks"] == [0]
    assert access.stats()["materialized_rows"] == 2
    assert access.spatial((4.0, 0.0, 6.0, 1.0), level=0) == [2]
    access.close()
    assert all(file.closed for file in access.files.values())


def test_lookup_binding_rejects_wrong_feature_identity(tmp_path: Path) -> None:
    import json

    import pytest

    source_file(tmp_path / "source.arrow")
    target = tmp_path / "candidate"
    target.mkdir()
    declaration = build_features(tmp_path / "source.arrow", target, "rivers", rows=2)
    artifacts = {p.name: fingerprint(p) for p in target.iterdir()}
    artifacts[declaration["data"]]["sha256"] = "0" * 64
    (target / "manifest.json").write_text(
        json.dumps({"experimental": True, "families": {"rivers": declaration}, "artifacts": artifacts})
    )
    with pytest.raises(ValueError, match="binding"):
        Access(str(target), "rivers", ["id"])


def test_absent_relationship_id_still_counts_decoded_batch(tmp_path: Path) -> None:
    import json

    import pyarrow as pa
    import pyarrow.ipc as ipc

    schema = pa.schema([pa.field("id", pa.int64(), False), pa.field("downstream_ids", pa.list_(pa.int64()), False)])
    table = pa.table({"id": [10, 20], "downstream_ids": [[20], []]}, schema=schema)
    with ipc.new_file(str(tmp_path / "relations.arrow"), schema) as writer:
        writer.write_table(table)
    (tmp_path / "directory.json").write_text(
        json.dumps({"version": 1, "batches": [{"batch": 0, "min_id": 10, "max_id": 20, "rows": 2}]})
    )
    declaration = {"data": "relations.arrow", "directory": "directory.json"}
    artifacts = {p.name: fingerprint(p) for p in tmp_path.iterdir()}
    (tmp_path / "manifest.json").write_text(
        json.dumps({"experimental": True, "relationships": {"rivers": declaration}, "artifacts": artifacts})
    )
    with Access(str(tmp_path), "rivers", ["id", "downstream_ids"], relationship=True) as access:
        selected, absent = access.ids([15])
        assert selected.num_rows == 0
        assert absent == [15]
        assert access.stats()["materialized_rows"] == 2
        assert access.stats()["materialized_bytes"] == table.nbytes
        assert access.stats()["data_blocks"] == [0]
        assert access.stats()["lookup_blocks"] == []
        access.reset()
        selected, absent = access.ids([10])
        assert selected.to_pylist() == [{"id": 10, "downstream_ids": [20]}]
        assert absent == []
        assert access.stats()["data_blocks"] == [0]
        assert access.stats()["lookup_blocks"] == []


def test_local_mutated_artifact_rejects_before_selected_values(tmp_path: Path) -> None:
    import json

    import pytest

    source_file(tmp_path / "source.arrow")
    target = tmp_path / "candidate"
    target.mkdir()
    declaration = build_features(tmp_path / "source.arrow", target, "rivers", rows=2)
    artifacts = {p.name: fingerprint(p) for p in target.iterdir()}
    (target / "manifest.json").write_text(
        json.dumps({"experimental": True, "families": {"rivers": declaration}, "artifacts": artifacts})
    )
    path = target / declaration["data"]
    value = bytearray(path.read_bytes())
    value[100] ^= 1
    path.write_bytes(value)
    with pytest.raises(ValueError, match="fingerprint"):
        Access(str(target), "rivers", ["id"])
