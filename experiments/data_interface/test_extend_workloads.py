import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest

from experiments.data_interface.oracles.extend_workloads import medium_window, row_ordinals, selected_rows


def test_medium_is_ordinary_square_around_source_window() -> None:
    assert medium_window([9.0, 19.0, 11.0, 21.0]) == (9.9, 19.9, 10.1, 20.1)


def test_even_ordinals_include_actual_source_rows_at_variable_batch_boundaries(tmp_path: Path) -> None:
    schema = pa.schema([("id", pa.int64()), ("level", pa.int16())])
    path = tmp_path / "source.arrow"
    with ipc.new_file(str(path), schema) as writer:
        writer.write_batch(pa.record_batch([[91, 3], [0, 1]], schema=schema))
        writer.write_batch(pa.record_batch([[70, 8, 12], [1, 2, 2]], schema=schema))
    ordinals = row_ordinals(5, 3)
    assert ordinals == [0, 2, 4]
    with pa.OSFile(str(path), "rb") as source:
        assert selected_rows(ipc.open_file(source), ordinals) == [
            {"ordinal": 0, "id": 91, "level": 0},
            {"ordinal": 2, "id": 70, "level": 1},
            {"ordinal": 4, "id": 12, "level": 2},
        ]


def test_extension_keeps_prior_witnesses_and_binds_source_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from experiments.data_interface.oracles import extend_workloads

    source = tmp_path / "source"
    source.mkdir()
    schema = pa.schema([("id", pa.int64()), ("level", pa.int16()), ("geometry", pa.binary())])
    with ipc.new_file(str(source / "records.arrow"), schema) as writer:
        writer.write_batch(pa.record_batch([[91, 3], [0, 1], [b"a", b"b"]], schema=schema))
        writer.write_batch(pa.record_batch([[70, 8, 12], [1, 2, 2], [b"c", b"d", b"e"]], schema=schema))
    # The fourth bbox only overlaps after the required outward float32 expansion.
    pq.write_table(
        pa.table(
            {
                "id": [91, 3, 70, 8, 12],
                "level": [0, 1, 1, 2, 2],
                "bbox_minx": [0.0, 0.05, 2.0, float(np.float32(0.1)), -3.0],
                "bbox_miny": [0.0, 0.05, 2.0, 0.0, -3.0],
                "bbox_maxx": [0.0, 0.05, 2.0, 0.2, -2.0],
                "bbox_maxy": [0.0, 0.05, 2.0, 0.0, -2.0],
            }
        ),
        source / "graph.parquet",
        row_group_size=2,
    )
    artifacts = {
        name: {"sha256": hashlib.sha256((source / name).read_bytes()).hexdigest()}
        for name in ["records.arrow", "graph.parquet"]
    }
    manifest = {
        "rivers": {"data": "records.arrow", "graph": "graph.parquet", "count": 5},
        "catchments": "records.arrow",
        "graph": "graph.parquet",
        "unit_count": 5,
        "artifacts": artifacts,
    }
    manifest_bytes = json.dumps(manifest).encode()
    (source / "manifest.json").write_bytes(manifest_bytes)
    source_sha = hashlib.sha256(manifest_bytes).hexdigest()
    monkeypatch.setattr(extend_workloads, "PINNED_MANIFEST", source_sha)
    prior_records = {"clustered_ids": [91, 3], "scattered_ids": [91, 70, 12]}
    prior_window = {"bounds_epsg4326": [-0.01, -0.01, 0.01, 0.01], "old_hash": "unchanged"}
    original = {
        "manifest_sha256": source_sha,
        "rivers_records": prior_records,
        "catchments_records": prior_records,
        "rivers_graph": {"windows": {"small": prior_window}},
        "catchments_graph": {"windows": {"small": prior_window}},
        "nodes_records": {"untouched": True},
    }
    workloads = tmp_path / "workloads.json"
    workloads.write_text(json.dumps(original))
    catchments = tmp_path / "catchment-records.json"
    catchments.write_text(json.dumps({**prior_records, "manifest_sha256": source_sha}))
    report = tmp_path / "extension.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "extend_workloads",
            str(source),
            "--workloads",
            str(workloads),
            "--catchment-records",
            str(catchments),
            "--report",
            str(report),
            "--count",
            "3",
        ],
    )
    extend_workloads.main()
    result = json.loads(report.read_text())
    assert json.loads(workloads.read_text()) == original
    for family in ["rivers", "catchments"]:
        records = result[family + "_records"]
        assert records["clustered_ids"] == prior_records["clustered_ids"]
        assert records["scattered_ids"] == prior_records["scattered_ids"]
        assert records["many_clustered"]["requested_ids"] == [91, 3, 70]
        assert records["many_dispersed"]["requested_ids"] == [91, 70, 12]
        assert records["many_dispersed"]["source_levels"] == [0, 1, 2]
        windows = result[family + "_graph"]["windows"]
        assert windows["small"] == prior_window
        assert windows["medium"]["all_tiers"]["count"] == 3
        assert (
            windows["medium"]["all_tiers"]["sorted_ids_sha256_le_i64"]
            == hashlib.sha256(np.asarray([3, 8, 91], dtype="<i8").tobytes()).hexdigest()
        )
        assert windows["medium"]["by_independent_domain_tier"]["2"]["count"] == 1
        assert result["extension"]["source_bindings"][family] == artifacts
    assert result["nodes_records"] == original["nodes_records"]
    assert result["extension"]["versions"] == {"pyarrow": pa.__version__, "numpy": np.__version__}
    assert result["extension"]["input_workloads_sha256"] == hashlib.sha256(workloads.read_bytes()).hexdigest()
    # A changed input identity must fail before any source witness is generated.
    report.unlink()
    changed = {**original, "manifest_sha256": "not-the-source"}
    workloads.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="Original workload source identity differs"):
        extend_workloads.main()
    assert not report.exists()
