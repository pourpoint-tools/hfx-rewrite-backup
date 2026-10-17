import json
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from experiments.data_interface.features import build_features
from experiments.data_interface.record_probe import source_records, validate_records
from experiments.data_interface.test_features import source_file
from hfx.candidates import fingerprint


def original_bundle(path: Path) -> pa.Table:
    path.mkdir()
    table = source_file(path / "rivers.arrow")
    lookup_schema = pa.schema([("id", pa.int64()), ("block", pa.int32()), ("row", pa.int32())])
    with ipc.new_file(str(path / "lookup.arrow"), lookup_schema) as writer:
        writer.write_table(pa.table({"id": [2, 90, 700], "block": [0, 0, 1], "row": [1, 0, 0]}, schema=lookup_schema))
    (path / "directory.json").write_text(json.dumps({"batches": [{"min_id": 2, "max_id": 700}]}))
    (path / "manifest.json").write_text(
        json.dumps({"rivers": {"data": "rivers.arrow", "lookup": "lookup.arrow", "directory": "directory.json"}})
    )
    return table


def test_original_lookup_preserves_order_duplicates_nulls_types_and_absence(tmp_path: Path) -> None:
    original_bundle(tmp_path / "source")
    selected, absent = source_records(tmp_path / "source", "rivers", [700, 3, 90, 700], ["source_value", "id"])
    assert selected.to_pylist() == [
        {"source_value": -7, "id": 700},
        {"source_value": None, "id": 90},
        {"source_value": -7, "id": 700},
    ]
    assert selected.schema.field("source_value").type == pa.int32()
    assert selected.schema.metadata == {b"custom": b"preserve"}
    assert absent == [3]
    empty, absent = source_records(tmp_path / "source", "rivers", [3, 701], ["id"])
    assert empty.num_rows == 0
    assert absent == [3, 701]


def test_validation_rejects_wrong_null_type_and_wkb() -> None:
    expected = pa.table({"id": [9], "value": pa.array([None], type=pa.int32()), "geometry": [b"exact"]})
    assert validate_records(expected, [11], expected, [11])["semantic_equal"]
    for actual in [
        expected.set_column(1, "value", pa.array([0], type=pa.int32())),
        expected.set_column(1, "value", pa.array([None], type=pa.int64())),
        expected.set_column(2, "geometry", pa.array([b"different"])),
    ]:
        with pytest.raises(ValueError, match="source records"):
            validate_records(actual, [11], expected, [11])
    with pytest.raises(ValueError, match="absent"):
        validate_records(expected, [], expected, [11])


def test_measure_splits_discovery_fetch_and_excludes_validation_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from experiments.data_interface import record_probe

    original_bundle(tmp_path / "source")
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    declaration = build_features(tmp_path / "source/rivers.arrow", candidate, "rivers", rows=2)
    artifacts = {p.name: fingerprint(p) for p in candidate.iterdir()}
    import hashlib

    binding = hashlib.sha256((tmp_path / "source/manifest.json").read_bytes()).hexdigest()
    (candidate / "manifest.json").write_text(
        json.dumps(
            {
                "experimental": True,
                "families": {"rivers": declaration},
                "artifacts": artifacts,
                "input_manifest_sha256": binding,
            }
        )
    )
    # Each timed phase takes exactly one tick; source validation advances 100 ticks.
    tick = [0.0]

    def clock() -> float:
        tick[0] += 1.0
        return tick[0]

    independent_read = record_probe.source_records

    def read_with_validation_cost(
        root: Path, family: str, ids: list[int], columns: list[str] | None
    ) -> tuple[pa.Table, list[int]]:
        tick[0] += 100.0
        return independent_read(root, family, ids, columns)

    monkeypatch.setattr(record_probe, "perf_counter", clock)
    monkeypatch.setattr(record_probe, "source_records", read_with_validation_cost)
    window = {
        "bounds_epsg4326": [4, 0, 6, 1],
        "all_tiers": {
            "count": 1,
            "sorted_ids_sha256_le_i64": hashlib.sha256(bytes.fromhex("0200000000000000")).hexdigest(),
        },
    }
    report = record_probe.measure(
        str(candidate), tmp_path / "source", "rivers", ["id", "source_value"], [[]], 2, window
    )
    first, repeated = [entry["operations"][0] for entry in report["repeats"]]
    assert report["closed"]
    assert report["opening_s"] == 1.0
    assert first["operation_to_result_s"] == repeated["operation_to_result_s"] == 2.0
    assert first["spatial_discovery"]["data_blocks_count"] == 1
    assert first["spatial_discovery"]["materialized_rows"] == 2
    assert first["record_fetch"]["lookup_blocks_count"] == 1
    assert first["record_fetch"]["data_blocks_count"] == 1
    assert first["record_fetch"]["materialized_rows"] == 2
    assert first["output_rows"] == 1
    assert first["record_fetch"]["local_read_bytes"] == repeated["record_fetch"]["local_read_bytes"] > 0
    assert first["validation"]["semantic_equal"]
    absent = record_probe.measure(str(candidate), tmp_path / "source", "rivers", ["id"], [[3]], 1)["repeats"][0][
        "operations"
    ][0]
    assert absent["absent"] == [3]
    assert absent["output_rows"] == 0
    assert absent["record_fetch"]["lookup_blocks_count"] == 1
    assert absent["record_fetch"]["materialized_rows"] == 0


def test_wkb_fetch_and_decode_are_separate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("shapely")
    import hashlib

    from experiments.data_interface import record_probe

    source = tmp_path / "source"
    original = original_bundle(source)
    point_wkb = bytes.fromhex("0101000000000000000000f03f0000000000000040")  # POINT (1 2), little endian.
    table = original.set_column(4, original.schema.field("geometry"), pa.array([point_wkb] * 3))
    with ipc.new_file(str(source / "rivers.arrow"), table.schema) as writer:
        writer.write_table(table, max_chunksize=2)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    declaration = build_features(source / "rivers.arrow", candidate, "rivers", rows=2)
    artifacts = {p.name: fingerprint(p) for p in candidate.iterdir()}
    (candidate / "manifest.json").write_text(
        json.dumps(
            {
                "experimental": True,
                "families": {"rivers": declaration},
                "artifacts": artifacts,
                "input_manifest_sha256": hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest(),
            }
        )
    )
    ticks = iter(range(100))
    monkeypatch.setattr(record_probe, "perf_counter", lambda: float(next(ticks)))
    result = record_probe.measure(str(candidate), source, "rivers", ["geometry"], [[90]], 1)["repeats"][0][
        "operations"
    ][0]
    assert result["requested_wkb_bytes"] == 21
    assert result["record_fetch"]["elapsed_s"] == 1.0
    assert result["geometry_decode_s"] == 1.0
    assert result["decoded_geometries"] == 1
    assert result["operation_to_result_s"] == 2.0
    assert result["total_to_result_s"] == 3.0


def test_node_spatial_cli_validates_source_oracle_and_tiers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib
    import sys

    from experiments.data_interface import record_probe

    source = tmp_path / "source"
    original_bundle(source)
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["river_nodes"] = manifest.pop("rivers")
    lookup_path = source / "lookup.arrow"
    lookup = ipc.open_file(str(lookup_path)).read_all()
    lookup = lookup.replace_schema_metadata(
        {b"hfx:data_sha256": fingerprint(source / "rivers.arrow")["sha256"].encode()}
    )
    with ipc.new_file(str(lookup_path), lookup.schema) as writer:
        writer.write_table(lookup)
    manifest["artifacts"] = {p.name: fingerprint(p) for p in source.iterdir() if p.name != "manifest.json"}
    manifest_path.write_text(json.dumps(manifest))
    sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    workloads = tmp_path / "workloads.json"
    workloads.write_text(
        json.dumps({"manifest_sha256": sha, "nodes_records": {"clustered_ids": [2], "scattered_ids": [2]}})
    )
    oracle = tmp_path / "node.json"
    oracle.write_text(
        json.dumps(
            {
                "manifest_sha256": sha,
                "window": {"bbox": [4, 0, 6, 1]},
                "count": 1,
                "sorted_ids_sha256_le_i64": record_probe.id_hash([2]),
                "by_tier": {"0": {"count": 1, "sorted_ids_sha256_le_i64": record_probe.id_hash([2])}},
            }
        )
    )
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "record_probe",
            str(source),
            "--source",
            str(source),
            "--family",
            "river_nodes",
            "--workloads",
            str(workloads),
            "--operation",
            "spatial",
            "--level",
            "0",
            "--columns",
            "id",
            "source_value",
            "--node-spatial-oracle",
            str(oracle),
            "--report",
            str(receipt),
        ],
    )
    record_probe.main()
    report = json.loads(receipt.read_text())
    assert report["selection"] == "first_source_node"
    assert report["repeats"][0]["operations"][0]["output_rows"] == 1
    assert report["repeats"][0]["operations"][0]["validation"]["semantic_equal"]
    changed = json.loads(oracle.read_text())
    changed["by_tier"]["0"]["count"] = 2
    oracle.write_text(json.dumps(changed))
    receipt.unlink()
    with pytest.raises(ValueError, match="independent bbox oracle"):
        record_probe.main()


@pytest.mark.parametrize("selection", ["many-clustered", "many-scattered", "medium"])
def test_extended_workload_cli_selects_exact_source_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selection: str
) -> None:
    import hashlib
    import sys
    from typing import Any

    from experiments.data_interface import record_probe

    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.json").write_text("{}")
    binding = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    medium = {"bounds_epsg4326": [9.9, 19.9, 10.1, 20.1], "all_tiers": {"count": 2}}
    workloads = tmp_path / "workloads.json"
    workloads.write_text(
        json.dumps(
            {
                "manifest_sha256": binding,
                "rivers_records": {
                    "clustered_ids": [91],
                    "scattered_ids": [12],
                    "many_clustered": {"requested_ids": [91, 3, 70]},
                    "many_dispersed": {"requested_ids": [91, 70, 12]},
                },
                "rivers_graph": {"windows": {"medium": medium}},
            }
        )
    )
    captured: dict[str, Any] = {}

    def measure(
        bundle: str,
        source: Path,
        family: str,
        columns: list[str] | None,
        requests: list[list[int]],
        repeats: int,
        window: dict[str, Any] | None,
        level: int | None,
        **options: Any,
    ) -> dict[str, Any]:
        captured.update(requests=requests, window=window)
        return {"repeats": []}

    monkeypatch.setattr(record_probe, "measure", measure)
    receipt = tmp_path / "receipt.json"
    argv = [
        "record_probe",
        str(source),
        "--source",
        str(source),
        "--workloads",
        str(workloads),
        "--report",
        str(receipt),
    ]
    argv += (
        ["--operation", "spatial", "--spatial-window", "medium"]
        if selection == "medium"
        else ["--selection", selection]
    )
    monkeypatch.setattr(sys, "argv", argv)
    record_probe.main()
    assert json.loads(receipt.read_text())["selection"] == selection
    assert captured["window"] == (medium if selection == "medium" else None)
    assert captured["requests"] == (
        [[]] if selection == "medium" else [[91, 3, 70]] if selection == "many-clustered" else [[91, 70, 12]]
    )
