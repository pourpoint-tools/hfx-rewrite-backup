from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pytest

from experiments.data_interface import association_probe


def test_association_spatial_records_uses_explicit_independent_intersection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    import struct

    def digest(ids: list[int]) -> str:
        return hashlib.sha256(struct.pack("<" + "q" * len(ids), *ids)).hexdigest()

    manifest = b'{"artifacts": {}}'
    (tmp_path / "manifest.json").write_bytes(manifest)
    source_sha = hashlib.sha256(manifest).hexdigest()
    expected = pa.table(
        {
            "id": pa.array([40, 70], type=pa.int64()),
            "bbox": ["explicit40", "explicit70"],
            "source_length": pa.array([None, 2.5], type=pa.float32()),
        }
    )
    accesses = []
    associated_ids, spatial_ids = [10, 40, 70], [20, 40, 70, 90]
    requested_ids = [40, 70]
    absent_catchment = False

    class FakeAccess:
        def __init__(self, root: str, family: str, columns: list[str], *, relationship: bool = False) -> None:
            self.family = family
            self.manifest = {"experimental": True, "input_manifest_sha256": source_sha}
            self.manifest_sha256 = "candidate"
            self.http = SimpleNamespace(requests=[])
            self.calls = 0
            self.closed = False
            accesses.append(self)

        def __enter__(self) -> "FakeAccess":
            return self

        def __exit__(self, *_: object) -> None:
            self.closed = True

        def reset(self) -> None:
            pass

        def stats(self) -> dict[str, Any]:
            return {
                "http_requests": self.calls,
                "http_body_bytes": self.calls * 8,
                "local_read_calls": 0,
                "local_read_bytes": 0,
                "lookup_blocks": [],
                "data_blocks": [0],
                "graph_blocks": [],
            }

        def ids(self, requested: list[int]) -> tuple[pa.Table, list[int]]:
            self.calls += 1
            if self.family == "catchments":
                assert requested == [901]
                schema = pa.schema([("id", pa.int64()), ("local_river_ids", pa.list_(pa.int64()))])
                if absent_catchment:
                    return pa.Table.from_batches([], schema=schema), [901]
                return pa.table({"id": [901], "local_river_ids": [associated_ids]}, schema=schema), []
            assert requested == requested_ids
            return expected, []

        def spatial(self, window: tuple[float, ...]) -> list[int]:
            self.calls += 1
            return spatial_ids

    monkeypatch.setattr(association_probe, "Access", FakeAccess, raising=False)

    def original(root: Path, family: str, ids: list[int], columns: list[str]) -> tuple[pa.Table, list[int]]:
        assert ids == requested_ids
        return expected, []

    monkeypatch.setattr(association_probe, "source_records", original, raising=False)
    ticks = iter(range(1000))
    monkeypatch.setattr(association_probe, "perf_counter", lambda: float(next(ticks)), raising=False)
    window = {
        "bounds_epsg4326": [0, 0, 1, 1],
        "all_tiers": {"count": 4, "sorted_ids_sha256_le_i64": digest([20, 40, 70, 90])},
    }
    oracle = {"count": 3, "sorted_ids_sha256": digest([10, 40, 70])}
    result = association_probe.measure("candidate", tmp_path, 901, "local_river_ids", window, oracle, 2)
    first, repeated = result["repeats"]
    assert all(access.closed for access in accesses)
    assert first["selected_count"] == 2
    assert first["selected_ids_sha256_le_i64"] == digest([40, 70])
    assert first["association_count"] == 3
    assert first["discovery_count"] == 4
    assert first["validation"]["semantic_equal"]
    assert first["phases"]["association"]["http_requests"] == 1
    assert first["phases"]["discovery"]["http_requests"] == 1
    assert first["phases"]["records"]["http_requests"] == 1
    assert first["total_to_result_s"] == 6.0
    assert repeated["total_to_result_s"] == 4.0
    with pytest.raises(ValueError, match="association differs"):
        association_probe.measure("candidate", tmp_path, 901, "local_river_ids", window, {"count": 2}, 1)
    assert result["shapely_version"] is None
    expected = expected.slice(0, 0)
    requested_ids = []
    for associated_ids, spatial_ids in [([], [20, 40, 70, 90]), ([10, 40, 70], []), ([], [])]:
        window["all_tiers"] = {"count": len(spatial_ids), "sorted_ids_sha256_le_i64": digest(spatial_ids)}
        oracle = {"count": len(associated_ids), "sorted_ids_sha256": digest(associated_ids)}
        empty = association_probe.measure("candidate", tmp_path, 901, "local_river_ids", window, oracle, 1)["repeats"][
            0
        ]
        assert empty["selected_count"] == 0
        assert empty["retained"]["intersection_array_bytes"] == 0
        assert empty["validation"]["semantic_equal"]
    absent_catchment = True
    with pytest.raises(ValueError, match="absent catchment"):
        association_probe.measure("candidate", tmp_path, 901, "local_river_ids", window, oracle, 1)
    assert all(access.closed for access in accesses)
