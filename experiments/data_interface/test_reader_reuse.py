"""Reader reuse must avoid repeated serialized metadata work without caching batches."""

import json
from pathlib import Path
from typing import Any

import pyarrow.ipc as ipc
import pytest

from experiments.data_interface.features import build_features
from experiments.data_interface.probe import Access
from experiments.data_interface.test_features import source_file
from hfx.candidates import fingerprint


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    source_file(tmp_path / "source.arrow")
    target = tmp_path / "candidate"
    target.mkdir()
    declaration = build_features(tmp_path / "source.arrow", target, "rivers", rows=2)
    artifacts = {p.name: fingerprint(p) for p in target.iterdir()}
    (target / "manifest.json").write_text(
        json.dumps({"experimental": True, "families": {"rivers": declaration}, "artifacts": artifacts})
    )
    return target


def test_single_cursor_wrapper_and_no_unprojected_data_footer(bundle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_open = ipc.open_file
    opens: list[Any] = []

    def counted_open(source: Any, *args: Any, **kwargs: Any) -> Any:
        opens.append(kwargs.get("options"))
        return original_open(source, *args, **kwargs)

    monkeypatch.setattr(ipc, "open_file", counted_open)
    with Access(str(bundle), "rivers", ["id"]) as access:
        assert len(opens) == 2  # Lookup footer and one projected data footer.
        assert access.open(access.declaration["data"]) is access.data_file
        assert access.schema.equals(original_open(str(bundle / access.declaration["data"])).schema, check_metadata=True)
        assert access.ids([700])[0].to_pylist() == [{"id": 700}]


def test_spatial_reuses_metadata_but_not_selected_batches(bundle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with Access(str(bundle), "rivers", ["id"]) as access:
        assert access.spatial((4.0, 0.0, 6.0, 1.0), level=0) == [2]
        before = access.stats()

        def unexpected_open(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("same-instance spatial query reopened IPC metadata")

        monkeypatch.setattr(ipc, "open_file", unexpected_open)
        assert access.spatial((4.0, 0.0, 6.0, 1.0), level=0) == [2]
        after = access.stats()
        assert after["local_read_bytes"] > before["local_read_bytes"]
        assert after["materialized_rows"] == 2 * before["materialized_rows"]


def test_opt_in_read_ahead_preserves_projection_and_closes_backing_files(bundle: Path) -> None:
    with Access(str(bundle), "rivers", ["id"], read_ahead_bytes=4096) as access:
        assert access.ids([700, 2])[0].to_pylist() == [{"id": 700}, {"id": 2}]
        assert access.spatial((4.0, 0.0, 6.0, 1.0), level=0) == [2]
        assert access.stats()["read_ahead_bytes"] == 4096
    assert all(file.closed for file in access.files.values())


def test_original_graph_reader_is_retained(bundle: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    graph = pa.table(
        {
            "id": [2, 700],
            "level": [0, 1],
            "bbox_minx": [4.0, 50.0],
            "bbox_miny": [0.0, 50.0],
            "bbox_maxx": [6.0, 51.0],
            "bbox_maxy": [1.0, 51.0],
        }
    )
    pq.write_table(graph, bundle / "graph.parquet", row_group_size=1)
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["rivers"] = manifest.pop("families")["rivers"]
    manifest.pop("experimental")
    manifest["rivers"]["graph"] = "graph.parquet"
    manifest["artifacts"]["graph.parquet"] = fingerprint(bundle / "graph.parquet")
    manifest_path.write_text(json.dumps(manifest))
    with Access(str(bundle), "rivers", ["id"], graph_pre_buffer=False) as access:
        assert access.spatial((4.0, 0.0, 6.0, 1.0), level=0) == [2]

        def unexpected_open(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("same-instance query reopened Parquet metadata")

        monkeypatch.setattr(pq, "ParquetFile", unexpected_open)
        before = access.stats()
        assert access.spatial((4.0, 0.0, 6.0, 1.0), level=0) == [2]
        assert access.stats()["local_read_bytes"] > before["local_read_bytes"]


def test_spatial_reuses_an_identical_normalized_record_projection(
    bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Access(str(bundle), "rivers", ["bbox", "id", "level"]) as access:

        def unexpected_open(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("identical spatial projection reopened IPC metadata")

        monkeypatch.setattr(ipc, "open_file", unexpected_open)
        assert access.spatial((4.0, 0.0, 6.0, 1.0), level=0) == [2]
