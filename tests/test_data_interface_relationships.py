"""Independently worked sparse relationships for the interface experiment."""

import json
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq


def _ipc(path: Path, columns: dict[str, list[object]], schema: pa.Schema) -> None:
    table = pa.table(columns, schema=schema)
    with ipc.new_file(str(path), schema) as writer:
        writer.write_table(table, max_chunksize=2)


def _source(path: Path) -> None:
    path.mkdir()
    (path / "manifest.json").write_text(
        json.dumps(
            {"catchment_connectivity": [{"level": 0, "status": "not_supplied"}, {"level": 1, "status": "supplied"}]}
        )
    )
    _ipc(
        path / "catchments.arrow",
        {"id": [900, 70, 10, 40, 20], "parent_id": [None, 900, 900, 900, 900]},
        pa.schema([("id", pa.int64()), ("parent_id", pa.int64())]),
    )
    _ipc(
        path / "rivers.arrow",
        {
            "id": [70, 900, 20, 10, 40],
            "parent_id": [900, None, 900, 900, 900],
            "local_catchment_id": [70, None, 20, 10, 40],
            "component_catchment_id": [900, 900, 900, 900, 900],
            "upstream_node_id": [300, None, 200, 100, 200],
            "downstream_node_id": [400, None, 300, 200, 300],
        },
        pa.schema(
            [
                (name, pa.int64())
                for name in (
                    "id",
                    "parent_id",
                    "local_catchment_id",
                    "component_catchment_id",
                    "upstream_node_id",
                    "downstream_node_id",
                )
            ]
        ),
    )
    _ipc(
        path / "river-nodes.arrow",
        {"id": [400, 100, 500, 300, 200], "coarser_node_id": [500, 500, None, 500, 500]},
        pa.schema([("id", pa.int64()), ("coarser_node_id", pa.int64())]),
    )
    # Diamond: 10 -> {20, 40} -> 70. IDs overlap across the two domains.
    for filename in ("graph.parquet", "river-graph.parquet"):
        pq.write_table(
            pa.table(
                {
                    "id": pa.array([70, 900, 20, 10, 40], pa.int64()),
                    "upstream_ids": pa.array([[20, 40], [], [10], [], [10]], pa.list_(pa.int64())),
                }
            ),
            path / filename,
            row_group_size=2,
        )


def _records(output: Path, declaration: dict[str, object]) -> dict[int, dict[str, object]]:
    with ipc.open_file(str(output / str(declaration["data"]))) as reader:
        return {row["id"]: row for row in reader.read_all().to_pylist()}


def test_sorted_forward_reverse_diamond_and_unknown_component(tmp_path: Path) -> None:
    from experiments.data_interface.relationships import build_relationships

    source, output = tmp_path / "source", tmp_path / "output"
    _source(source)
    output.mkdir()
    declarations = build_relationships(source, output, batch_rows=2)
    for domain in ("catchments", "rivers"):
        declaration = cast(dict[str, object], declarations[domain])
        records = _records(output, declaration)
        assert list(records) == [10, 20, 40, 70, 900]
        assert {key: row["upstream_ids"] for key, row in records.items()} == {
            10: [],
            20: [10],
            40: [10],
            70: [20, 40],
            900: [],
        }
        assert {key: row["downstream_ids"] for key, row in records.items()} == {
            10: [20, 40],
            20: [70],
            40: [70],
            70: [],
            900: [],
        }
        directory = json.loads((output / str(declaration["directory"])).read_text())
        assert directory == {
            "version": 1,
            "batches": [
                {"batch": 0, "min_id": 10, "max_id": 20, "rows": 2},
                {"batch": 1, "min_id": 40, "max_id": 70, "rows": 2},
                {"batch": 2, "min_id": 900, "max_id": 900, "rows": 1},
            ],
        }
        with ipc.open_file(str(output / str(declaration["data"]))) as reader:
            assert all(field.type == pa.list_(pa.int64()) for field in list(reader.schema)[1:])
    assert cast(dict[str, object], declarations["catchments"])["connectivity"] == [
        {"level": 0, "status": "not_supplied"},
        {"level": 1, "status": "supplied"},
    ]


def test_explicit_references_remain_separate_and_shared_node_adds_no_flow(tmp_path: Path) -> None:
    from experiments.data_interface.relationships import build_relationships

    source, output = tmp_path / "source", tmp_path / "output"
    _source(source)
    # All four rivers meet node 200, but the source pairs only 10->20 and 40->70.
    schema = ipc.open_file(str(source / "rivers.arrow")).schema
    _ipc(
        source / "rivers.arrow",
        {
            "id": [70, 900, 20, 10, 40],
            "parent_id": [900, None, 900, 900, 900],
            "local_catchment_id": [70, None, 20, 10, 40],
            "component_catchment_id": [900, 900, 900, 900, 900],
            "upstream_node_id": [200, None, 200, 100, 300],
            "downstream_node_id": [400, None, 300, 200, 200],
        },
        schema,
    )
    pq.write_table(
        pa.table(
            {
                "id": pa.array([70, 900, 20, 10, 40], pa.int64()),
                "upstream_ids": pa.array([[40], [], [10], [], []], pa.list_(pa.int64())),
            }
        ),
        source / "river-graph.parquet",
    )
    output.mkdir()
    declarations = build_relationships(source, output, batch_rows=2)
    rivers = _records(output, cast(dict[str, object], declarations["rivers"]))
    catchments = _records(output, cast(dict[str, object], declarations["catchments"]))
    nodes = _records(output, cast(dict[str, object], declarations["river_nodes"]))
    assert rivers[10]["downstream_ids"] == [20]
    assert rivers[40]["downstream_ids"] == [70]
    assert nodes[200]["incoming_river_ids"] == [10, 40]
    assert nodes[200]["outgoing_river_ids"] == [20, 70]
    assert nodes[500]["finer_node_ids"] == [100, 200, 300, 400]
    assert nodes[200]["coarser_node_ids"] == [500]
    assert nodes[500]["coarser_node_ids"] == []
    assert catchments[900]["child_ids"] == [10, 20, 40, 70]
    assert rivers[900]["child_ids"] == [10, 20, 40, 70]
    assert rivers[20]["parent_ids"] == [900]
    assert rivers[900]["parent_ids"] == []
    assert catchments[900]["local_river_ids"] == []
    assert catchments[900]["component_river_ids"] == [10, 20, 40, 70, 900]
    assert catchments[20]["local_river_ids"] == [20]
    assert rivers[20]["local_catchment_ids"] == [20]
    assert rivers[20]["component_catchment_ids"] == [900]
    assert rivers[20]["upstream_node_ids"] == [200]
    assert rivers[20]["downstream_node_ids"] == [300]
    bindings = cast(dict[str, object], cast(dict[str, object], declarations["river_nodes"])["columns"])
    assert bindings["incoming_river_ids"] == {
        "source_domain": "rivers",
        "target_domain": "rivers",
        "source_artifact": "rivers.arrow",
        "source_column": "downstream_node_id",
        "direction": "reverse",
    }


def test_full_verification_checks_source_edges_and_published_ranges(tmp_path: Path) -> None:
    import pytest

    from experiments.data_interface.relationships import build_relationships, verify_relationships

    source, output = tmp_path / "source", tmp_path / "output"
    _source(source)
    output.mkdir()
    declarations = build_relationships(source, output, batch_rows=2)
    result = verify_relationships(source, output, declarations)
    assert result["catchments"]["rows"] == 5
    assert cast(dict[str, int], result["rivers"]["columns"])["downstream_ids"] == 4
    assert cast(dict[str, int], result["river_nodes"]["columns"])["incoming_river_ids"] == 4

    path = output / "rivers-relationships.arrow"
    table = ipc.open_file(str(path)).read_all()
    # Sorted IDs are still correct; replace one real edge with a plausible false edge.
    index = table.schema.get_field_index("downstream_ids")
    replacement = pa.array([[70], [70], [70], [], []], type=pa.list_(pa.int64()))
    table = table.set_column(index, table.schema.field(index), replacement)
    with ipc.new_file(str(path), table.schema) as writer:
        writer.write_table(table, max_chunksize=2)
    with pytest.raises(ValueError, match="rivers.downstream_ids.*source"):
        verify_relationships(source, output, declarations)


def test_full_verification_rejects_binding_and_directory_changes(tmp_path: Path) -> None:
    import pytest

    from experiments.data_interface.relationships import build_relationships, verify_relationships

    source, output = tmp_path / "source", tmp_path / "output"
    _source(source)
    output.mkdir()
    declarations = build_relationships(source, output, batch_rows=2)
    path = output / "catchments-relationships-directory.json"
    directory = json.loads(path.read_text())
    directory["batches"][0]["max_id"] = 99
    path.write_text(json.dumps(directory))
    with pytest.raises(ValueError, match="directory"):
        verify_relationships(source, output, declarations)
    build_relationships(source, output, batch_rows=2)
    declaration = cast(dict[str, object], declarations["rivers"])
    columns = cast(dict[str, dict[str, str]], declaration["columns"])
    columns["local_catchment_ids"]["target_domain"] = "rivers"
    with pytest.raises(ValueError, match="binding"):
        verify_relationships(source, output, declarations)
