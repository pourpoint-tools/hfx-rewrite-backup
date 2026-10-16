from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from experiments.data_interface.baseline_graph_spatial import probe


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    # Row groups: crossing + boundary; other tier + distant; unknown bbox stats tested separately.
    table = pa.table(
        {
            "id": pa.array([41, 7, 90, 800, 3, 105], type=pa.int64()),
            "level": pa.array([0, 0, 1, 1, 0, 0], type=pa.int16()),
            "bbox_minx": pa.array([-2, 1, 0, 5, 10, 20], type=pa.float32()),
            "bbox_miny": pa.array([0, 1, 0, 5, 10, 20], type=pa.float32()),
            "bbox_maxx": pa.array([2, 1, 1, 6, 11, 21], type=pa.float32()),
            "bbox_maxy": pa.array([2, 1, 1, 6, 11, 21], type=pa.float32()),
            "upstream_ids": pa.array([[], [41], [], [], [], []], type=pa.list_(pa.int64())),
        }
    )
    pq.write_table(table, tmp_path / "graph.parquet", row_group_size=2)
    data = (tmp_path / "graph.parquet").read_bytes()
    fingerprint = {
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "head_sha256": hashlib.sha256(data[:65536]).hexdigest(),
        "tail_sha256": hashlib.sha256(data[-65536:]).hexdigest(),
    }
    manifest = {
        "format_version": "0.4.0",
        "graph": "graph.parquet",
        "rivers": {"graph": "graph.parquet"},
        "artifacts": {"graph.parquet": fingerprint},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def test_crossing_boundary_and_level_selection(bundle: Path) -> None:
    result = probe(str(bundle), "catchments", (1.0, 1.0, 1.0, 1.0), (0,))
    assert result["selected_ids"] == [41, 7]
    assert result["selected_groups"] == [0]
    assert result["materialized_rows"] == 2
    assert result["retained_output_bytes"] == 16
    assert result["sorted_ids_sha256_le_i64"] == hashlib.sha256(np.array([7, 41], dtype="<i8").tobytes()).hexdigest()
    phases = result["phases"]
    assert phases["opening"]["local_serialized_read_calls"] > 0
    assert phases["opening"]["http_request_count"] == 0
    assert phases["selection"]["http_body_bytes"] == 0
    assert result["materialized_columns"] == ["id", "level", "bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"]


def test_all_tiers_empty_and_omitted_tiers(bundle: Path) -> None:
    assert probe(str(bundle), "rivers", (1.0, 1.0, 1.0, 1.0))["selected_ids"] == [41, 7, 90]
    empty = probe(str(bundle), "rivers", (-10.0, -10.0, -9.0, -9.0))
    assert empty["selected_ids"] == [] and empty["selected_groups"] == []
    no_tier = probe(str(bundle), "catchments", (0.0, 0.0, 2.0, 2.0), ())
    assert no_tier["selected_ids"] == [] and no_tier["materialized_rows"] == 0


def test_fingerprint_failure(bundle: Path) -> None:
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["artifacts"]["graph.parquet"]["head_sha256"] = "0" * 64
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        probe(str(bundle), "catchments", (0.0, 0.0, 1.0, 1.0))


def test_graph_cli_rejects_source_receipt_and_wrong_workload_identity(
    bundle: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from experiments.data_interface.baseline_graph_spatial import main

    workloads = bundle.parent / "workloads.json"
    raw = (bundle / "manifest.json").read_bytes()
    workload = {
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "rivers_graph": {
            "windows": {
                "small": {
                    "bounds_epsg4326": [1, 1, 1, 1],
                    "all_tiers": {
                        "count": 3,
                        "sorted_ids_sha256_le_i64": hashlib.sha256(
                            np.array([7, 41, 90], dtype="<i8").tobytes()
                        ).hexdigest(),
                    },
                }
            }
        },
    }
    workloads.write_text(json.dumps(workload))
    argv = [
        "graph",
        str(bundle),
        "--family",
        "rivers",
        "--window",
        "small",
        "--workloads",
        str(workloads),
        "--report",
        str(bundle / "receipt.json"),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(ValueError, match="outside.*bundle"):
        main()
    assert not (bundle / "receipt.json").exists()
    workload["manifest_sha256"] = "0" * 64
    workloads.write_text(json.dumps(workload))
    argv[-1] = str(bundle.parent / "receipt.json")
    with pytest.raises(ValueError, match="source manifest"):
        main()
