"""Independent sparse split/reconvergence traversal examples."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest

from experiments.data_interface.traversal_probe import NumericGraph, traverse


def diamond(direction: str) -> NumericGraph:
    # Source records deliberately arrive out of ID order.
    table = pa.table({"id": [30, 10, 40, 20], "upstream_ids": [[10], [], [20, 30], [10]]})
    return NumericGraph.from_incoming(table, direction)


@pytest.mark.parametrize(("direction", "seed"), [("upstream", 40), ("downstream", 10)])
def test_sparse_diamond_inclusive_unique(direction: str, seed: int) -> None:
    graph = diamond(direction)
    result, workspace = traverse(graph.neighbors, seed)
    np.testing.assert_array_equal(result, [10, 20, 30, 40])
    assert workspace >= result.nbytes


def test_absent_seed_is_not_a_terminal() -> None:
    with pytest.raises(ValueError, match="absent"):
        traverse(diamond("upstream").neighbors, 15)


def test_published_modes_group_and_reuse_batches(tmp_path: Path) -> None:
    from experiments.data_interface.probe import Access
    from experiments.data_interface.traversal_probe import Published

    table = pa.table({"id": [10, 20, 30, 40], "downstream_ids": [[20, 30], [40], [40], []]})
    data = tmp_path / "flow.arrow"
    with pa.ipc.new_file(str(data), table.schema) as writer:
        writer.write_table(table, max_chunksize=2)
    directory = tmp_path / "directory.json"
    directory.write_text(
        json.dumps(
            {
                "batches": [
                    {"batch": 0, "min_id": 10, "max_id": 20, "rows": 2},
                    {"batch": 1, "min_id": 30, "max_id": 40, "rows": 2},
                ]
            }
        )
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "experimental": True,
                "relationships": {"rivers": {"data": data.name, "directory": directory.name}},
                "artifacts": {
                    p.name: {
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                        "size_bytes": p.stat().st_size,
                        "head_sha256": hashlib.sha256(p.read_bytes()[:65536]).hexdigest(),
                        "tail_sha256": hashlib.sha256(p.read_bytes()[-65536:]).hexdigest(),
                    }
                    for p in (directory, data)
                },
            }
        )
    )
    for mode in ("selective", "batch-cache", "bulk"):
        with Access(str(tmp_path), "rivers", ["id", "downstream_ids"], relationship=True) as access:
            provider = Published(access, "downstream_ids", mode)
            provider.prepare()
            result, _ = traverse(provider.neighbors, 10)
            np.testing.assert_array_equal(result, [10, 20, 30, 40])
            if mode == "batch-cache":
                assert len(provider.cache) == 2
                provider.reset()
                assert not provider.cache
            with pytest.raises(ValueError, match="absent"):
                traverse(provider.neighbors, 15)


def test_cut_edge_is_an_error_not_clipped() -> None:
    table = pa.table({"id": [10], "upstream_ids": [[90]]})
    graph = NumericGraph.from_incoming(table, "upstream")
    with pytest.raises(ValueError, match="absent"):
        traverse(graph.neighbors, 10)


def test_unknown_connectivity_rejected() -> None:
    from experiments.data_interface.traversal_probe import check_connectivity

    statuses = [{"level": 0, "status": "not_supplied"}, {"level": 1, "status": "supplied"}]
    with pytest.raises(ValueError, match="not supplied"):
        check_connectivity(statuses, 0)
    check_connectivity(statuses, 1)


def test_consumer_cli_timed_preparation_and_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    import pyarrow.parquet as pq

    from experiments.data_interface.traversal_probe import main

    source = tmp_path / "bundle"
    source.mkdir()
    graph = source / "graph.parquet"
    table = pa.table({"id": [30, 10, 40, 20], "upstream_ids": [[10], [], [20, 30], [10]]})
    pq.write_table(table, graph)
    raw = graph.read_bytes()
    identity = {
        "size_bytes": len(raw),
        "head_sha256": hashlib.sha256(raw[:65536]).hexdigest(),
        "tail_sha256": hashlib.sha256(raw[-65536:]).hexdigest(),
    }
    (source / "manifest.json").write_text(
        json.dumps({"rivers": {"graph": graph.name}, "artifacts": {graph.name: identity}})
    )
    report = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe",
            "--bundle",
            str(source),
            "--strategy",
            "consumer",
            "--seed",
            "10",
            "--repeats",
            "2",
            "--report",
            str(report),
        ],
    )
    main()
    receipt = json.loads(report.read_text())
    assert receipt["startup_to_first_result_s"] >= receipt["opening_s"] + receipt["preparation_s"]
    assert [p["count"] for p in receipt["phases"]] == [4, 4]
    assert (
        receipt["phases"][0]["sorted_ids_sha256_le_i64"]
        == hashlib.sha256(bytes.fromhex("0a0000000000000014000000000000001e000000000000002800000000000000")).hexdigest()
    )
    assert receipt["after_preparation"]["local_read_bytes"] > receipt["opening"]["local_read_bytes"]
    assert (
        receipt["phases"][0]["total_transport"]["local_read_bytes"] == receipt["after_preparation"]["local_read_bytes"]
    )
    assert receipt["phases"][1]["total_transport"]["local_read_bytes"] == 0
    assert receipt["total_transport"]["local_read_bytes"] == receipt["after_preparation"]["local_read_bytes"]
    assert receipt["requests"] == []


@pytest.mark.parametrize("unsafe", ["overwrite", "source"])
def test_cli_refuses_unsafe_measurements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str) -> None:
    import sys

    from experiments.data_interface.traversal_probe import main

    source = tmp_path / "bundle"
    source.mkdir()
    report = source / "receipt.json" if unsafe == "source" else tmp_path / "receipt.json"
    if unsafe == "overwrite":
        report.write_text("preserved")
    bundle = str(source)
    monkeypatch.setattr(sys, "argv", ["probe", "--bundle", bundle, "--strategy", "consumer", "--report", str(report)])
    with pytest.raises((SystemExit, FileExistsError)):
        main()
    if unsafe == "overwrite":
        assert report.read_text() == "preserved"


def test_multi_seed_overlap_and_empty_membership() -> None:
    graph = diamond("downstream")
    result, _ = traverse(graph.neighbors, np.asarray([30, 20, 20], dtype=np.int64))
    np.testing.assert_array_equal(result, [20, 30, 40])
    empty, workspace = traverse(graph.neighbors, np.asarray([], dtype=np.int64))
    assert not len(empty)
    assert workspace == 0


@pytest.mark.parametrize("mode", ["consumer", "batch-cache"])
def test_workflow_discovery_closure_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    import sys

    import pyarrow.parquet as pq

    from experiments.data_interface.traversal_probe import main

    source = tmp_path / "bundle"
    source.mkdir()
    bbox = pa.array([{"xmin": x, "ymin": 0.0, "xmax": x + 0.1, "ymax": 0.1} for x in [0.0, 1.0, 2.0, 3.0]])
    table = pa.table({"id": [10, 20, 30, 40], "level": [0] * 4, "bbox": bbox})
    with pa.ipc.new_file(str(source / "features.arrow"), table.schema) as writer:
        writer.write_table(table)
    data_sha = hashlib.sha256((source / "features.arrow").read_bytes()).hexdigest()
    lookup = pa.table({"id": [10, 20, 30, 40], "block": [0] * 4, "row": [0, 1, 2, 3]}).replace_schema_metadata(
        {b"hfx:data_sha256": data_sha.encode()}
    )
    with pa.ipc.new_file(str(source / "lookup.arrow"), lookup.schema) as writer:
        writer.write_table(lookup)
    incoming = [[], [10], [10], [20, 30]]
    graph = pa.table(
        {
            "id": [10, 20, 30, 40],
            "level": [0] * 4,
            "upstream_ids": incoming,
            "bbox_minx": [0.0, 1.0, 2.0, 3.0],
            "bbox_miny": [0.0] * 4,
            "bbox_maxx": [0.1, 1.1, 2.1, 3.1],
            "bbox_maxy": [0.1] * 4,
        }
    )
    pq.write_table(graph, source / "graph.parquet")
    relation = pa.table({"id": [10, 20, 30, 40], "downstream_ids": [[20, 30], [40], [40], []]})
    with pa.ipc.new_file(str(source / "flow.arrow"), relation.schema) as writer:
        writer.write_table(relation)
    (source / "directory.json").write_text(
        json.dumps({"batches": [{"batch": 0, "min_id": 10, "max_id": 40, "rows": 4}]})
    )
    declaration = {
        "data": "features.arrow",
        "lookup": "lookup.arrow",
        "directory": "directory.json",
        "graph": "graph.parquet",
    }
    artifacts = {
        p.name: {
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "size_bytes": p.stat().st_size,
            "head_sha256": hashlib.sha256(p.read_bytes()[:65536]).hexdigest(),
            "tail_sha256": hashlib.sha256(p.read_bytes()[-65536:]).hexdigest(),
        }
        for p in source.iterdir()
    }
    manifest: dict[str, object] = {"rivers": declaration, "artifacts": artifacts}
    if mode != "consumer":
        declaration["data_sha256"] = data_sha
        manifest.update(
            {
                "experimental": True,
                "families": {"rivers": declaration},
                "relationships": {"rivers": {"data": "flow.arrow", "directory": "directory.json"}},
            }
        )
    (source / "manifest.json").write_text(json.dumps(manifest))
    workloads = tmp_path / "workloads.json"
    source_sha = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    workloads.write_text(
        json.dumps(
            {
                "manifest_sha256": source_sha,
                "rivers_graph": {"windows": {"small": {"bounds_epsg4326": [-0.01, -0.01, 0.11, 0.11]}}},
            }
        )
    )
    oracles = tmp_path / "oracles.json"

    def identity(values: list[int]) -> dict[str, object]:
        return {
            "count": len(values),
            "sorted_ids_sha256_le_i64": hashlib.sha256(np.asarray(values, dtype="<i8").tobytes()).hexdigest(),
            "explicit_ids": values,
            "envelope_details": {"source": "independent fixture"},
        }

    oracle = {
        "family": "rivers",
        "window": "small",
        "level": 0,
        "direction": "downstream",
        "seeds": identity([10]),
        "closure": identity([10, 20, 30, 40]),
    }
    oracles.write_text(json.dumps({"source_manifest_sha256": source_sha, "workflows": [oracle]}))
    report = tmp_path / "report.json"
    argv = [
        "probe",
        "--bundle",
        str(source),
        "--strategy",
        mode,
        "--source",
        str(source),
        "--window",
        "small",
        "--level",
        "0",
        "--workloads",
        str(workloads),
        "--workflow-oracles",
        str(oracles),
        "--record-columns",
        "id",
        "bbox",
        "--repeats",
        "1",
        "--report",
        str(report),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    main()
    receipt = json.loads(report.read_text())
    phase = receipt["phases"][0]
    assert phase["discovery"]["count"] == 1
    assert phase["count"] == 4
    assert phase["records"]["rows"] == 4  # Three records lie beyond the selected window.
    assert receipt["startup_to_records_s"] >= receipt["startup_to_first_result_s"]
    assert "feature_requests" in receipt
    assert receipt["workloads_sha256"] == hashlib.sha256(workloads.read_bytes()).hexdigest()
    assert receipt["workflow_oracles_sha256"] == hashlib.sha256(oracles.read_bytes()).hexdigest()
    accepted_workloads, accepted_oracles = workloads.read_text(), oracles.read_text()
    for path, key in [(workloads, "manifest_sha256"), (oracles, "source_manifest_sha256")]:
        changed = json.loads(path.read_text())
        changed[key] = "0" * 64
        path.write_text(json.dumps(changed))
        argv[-1] = str(tmp_path / f"wrong-{key}.json")
        with pytest.raises(ValueError, match="source manifest"):
            main()
        workloads.write_text(accepted_workloads)
        oracles.write_text(accepted_oracles)
    oracle["closure"] = identity([10])
    oracles.write_text(json.dumps({"source_manifest_sha256": source_sha, "workflows": [oracle]}))
    argv[-1] = str(tmp_path / "mismatch.json")
    with pytest.raises(ValueError, match="oracle mismatch"):
        main()
    assert "oracle mismatch" in json.loads((tmp_path / "mismatch.json").read_text())["error"]


@pytest.mark.parametrize("tamper", [False, True])
def test_workflow_validates_source_records_and_totals_distinct_accesses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: bool
) -> None:
    import sys

    from experiments.data_interface import traversal_probe
    from experiments.data_interface.features import build_features
    from experiments.data_interface.probe import Access
    from experiments.data_interface.test_record_probe import original_bundle
    from hfx.candidates import fingerprint

    source, candidate = tmp_path / "source", tmp_path / "candidate"
    original_bundle(source)
    source_sha = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    candidate.mkdir()
    declaration = build_features(source / "rivers.arrow", candidate, "rivers", rows=2)
    relation = pa.table({"id": [2, 90, 700], "downstream_ids": [[90], [700], []]})
    with pa.ipc.new_file(str(candidate / "flow.arrow"), relation.schema) as writer:
        writer.write_table(relation)
    (candidate / "flow-directory.json").write_text(
        json.dumps({"batches": [{"batch": 0, "min_id": 2, "max_id": 700, "rows": 3}]})
    )
    (candidate / "manifest.json").write_text(
        json.dumps(
            {
                "experimental": True,
                "input_manifest_sha256": source_sha,
                "families": {"rivers": declaration},
                "relationships": {"rivers": {"data": "flow.arrow", "directory": "flow-directory.json"}},
                "artifacts": {path.name: fingerprint(path) for path in candidate.iterdir()},
            }
        )
    )
    workloads = tmp_path / "workloads.json"
    workloads.write_text(
        json.dumps(
            {
                "manifest_sha256": source_sha,
                "rivers_graph": {"windows": {"small": {"bounds_epsg4326": [4.0, 0.0, 6.0, 1.0]}}},
            }
        )
    )
    report = tmp_path / "report.json"
    original_ids = Access.ids
    if tamper:

        def changed_ids(access: Access, requested: list[int]) -> tuple[pa.Table, list[int]]:
            table, absent = original_ids(access, requested)
            if "source_value" in table.column_names:
                position = table.schema.get_field_index("source_value")
                table = table.set_column(
                    position, table.schema.field(position), pa.array([99] * table.num_rows, type=pa.int32())
                )
            return table, absent

        monkeypatch.setattr(Access, "ids", changed_ids)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "traverse",
            "--bundle",
            str(candidate),
            "--source",
            str(source),
            "--strategy",
            "batch-cache",
            "--window",
            "small",
            "--level",
            "0",
            "--workloads",
            str(workloads),
            "--record-columns",
            "source_value",
            "--repeats",
            "2",
            "--report",
            str(report),
        ],
    )
    if tamper:
        with pytest.raises(ValueError, match="source records differ"):
            traversal_probe.main()
        return
    traversal_probe.main()
    receipt = json.loads(report.read_text())
    first, repeated = receipt["phases"]
    assert first["record_validation"]["semantic_equal"]
    assert first["records"]["rows"] == 3
    assert first["total_transport"]["local_read_bytes"] == sum(
        phase["local_read_bytes"]
        for phase in [receipt["opening"], receipt["feature_opening"], first["discovery"], first["records"], first]
    )
    assert repeated["total_transport"]["local_read_bytes"] == sum(
        phase["local_read_bytes"] for phase in [repeated["discovery"], repeated["records"], repeated]
    )
    assert receipt["total_transport"]["local_read_bytes"] == sum(
        phase["total_transport"]["local_read_bytes"] for phase in receipt["phases"]
    )


def test_transport_totals_include_optional_connectivity_access(tmp_path: Path) -> None:
    from experiments.data_interface.probe import Access
    from experiments.data_interface.record_probe import TRANSPORT
    from experiments.data_interface.test_record_probe import original_bundle
    from experiments.data_interface.traversal_probe import transport_stats
    from hfx.candidates import fingerprint

    source = tmp_path / "source"
    original_bundle(source)
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["artifacts"] = {path.name: fingerprint(path) for path in source.iterdir() if path != manifest_path}
    manifest_path.write_text(json.dumps(manifest))
    # This source helper's lookup metadata is not publication-bound; use relationship mode
    # solely to exercise three independently counted file streams here.
    manifest["experimental"] = True
    manifest["relationships"] = {"rivers": {"data": "rivers.arrow", "directory": "directory.json"}}
    manifest_path.write_text(json.dumps(manifest))
    with (
        Access(str(source), "rivers", ["id"], relationship=True) as adjacency,
        Access(str(source), "rivers", ["id"], relationship=True) as features,
        Access(str(source), "rivers", ["id"], relationship=True) as connectivity,
    ):
        accesses = [adjacency, features, connectivity]
        expected = {key: sum(int(access.stats()[key]) for access in accesses) for key in TRANSPORT}
        assert transport_stats(accesses) == expected
        assert expected["local_read_bytes"] > adjacency.stats()["local_read_bytes"]
