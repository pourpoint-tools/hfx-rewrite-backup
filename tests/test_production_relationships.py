"""Production relationships retain source evidence and bind final feature artifacts."""

import json
from copy import deepcopy
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest
from relationship_fixtures import _records, _source


def test_final_feature_bindings_and_independent_verification(tmp_path: Path) -> None:
    from hfx.relationships import build_relationships, verify_relationships

    source, output = tmp_path / "source", tmp_path / "output"
    _source(source)
    output.mkdir()
    families: dict[str, dict[str, object]] = {
        domain: {"data": f"{domain}.parquet", "data_sha256": str(index) * 64}
        for index, domain in enumerate(("catchments", "rivers", "river_nodes"), start=1)
    }
    declarations = build_relationships(source, output, families, batch_rows=2)
    rivers = cast(dict[str, object], declarations["rivers"])
    assert rivers["feature_artifacts"] == families
    columns = cast(dict[str, dict[str, str]], rivers["columns"])
    assert columns["upstream_ids"]["source_artifact"] == "river-graph.parquet"
    assert columns["local_catchment_ids"]["source_artifact"] == "rivers.arrow"
    records = _records(output, rivers)
    assert records[10]["downstream_ids"] == [20, 40]
    assert records[20]["component_catchment_ids"] == [900]
    # Rivers 20 and 40 share both endpoints, not a flow edge to each other.
    assert records[20]["upstream_node_ids"] == records[40]["upstream_node_ids"] == [200]
    assert records[20]["downstream_node_ids"] == records[40]["downstream_node_ids"] == [300]
    assert records[20]["downstream_ids"] == records[40]["downstream_ids"] == [70]
    # Unknown local association is not replaced by the known component association.
    assert records[900]["local_catchment_ids"] == []
    assert records[900]["component_catchment_ids"] == [900]
    assert cast(dict[str, object], declarations["catchments"])["connectivity"] == [
        {"level": 0, "status": "not_supplied"},
        {"level": 1, "status": "supplied"},
    ]
    result = verify_relationships(source, output, families, declarations)
    assert result["rivers"]["rows"] == 5

    catchments = cast(dict[str, object], declarations["catchments"])
    catchments["connectivity_source"] = "unrelated.json"
    with pytest.raises(ValueError, match="connectivity source"):
        verify_relationships(source, output, families, declarations)
    catchments["connectivity_source"] = "manifest.json"

    changed = deepcopy(families)
    changed["rivers"]["data_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="feature.*binding"):
        verify_relationships(source, output, changed, declarations)

    # A plausible false edge still has correct IDs, schema and directory ranges.
    path = output / str(rivers["data"])
    with ipc.open_file(str(path)) as reader:
        table = reader.read_all()
    index = table.schema.get_field_index("downstream_ids")
    table = table.set_column(
        index, table.schema.field(index), pa.array([[70], [70], [70], [], []], pa.list_(pa.int64()))
    )
    with ipc.new_file(str(path), table.schema) as writer:
        writer.write_table(table, max_chunksize=2)
    with pytest.raises(ValueError, match="rivers.downstream_ids.*source"):
        verify_relationships(source, output, families, declarations)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("fractional_ids", "schema"),
        ("null_ids", "must not be null"),
        ("nullable_ids", "schema"),
        ("nullable_lists", "schema"),
        ("unsorted_neighbors", "strictly sorted"),
        ("duplicate_neighbors", "strictly sorted"),
    ],
)
def test_bundle_rejects_invalid_relationship_storage(tmp_path: Path, mutation: str, message: str) -> None:
    from hfx.candidates import fingerprint
    from hfx.spatial_bundle import build, verify
    from tests.test_spatial_bundle import normalized_source

    source, output = tmp_path / "source", tmp_path / "output"
    digest = normalized_source(source)
    manifest = build(source, output, source_manifest_sha256=digest, rows=2)
    name = manifest["relationships"]["rivers"]["data"]
    path = output / name
    with ipc.open_file(str(path)) as reader:
        table = reader.read_all()
    index = 0 if mutation.endswith("ids") else table.schema.get_field_index("downstream_ids")
    field = table.schema.field(index)
    values = table.column(index).to_pylist()
    if mutation == "fractional_ids":
        field = pa.field("id", pa.float64(), nullable=False)
        values = [value + 0.5 for value in cast(list[int], values)]
    elif mutation == "null_ids":
        values[0] = None
    elif mutation.startswith("nullable"):
        field = field.with_nullable(True)
    elif mutation == "unsorted_neighbors":
        assert values[0] == [20, 40]
        values[0] = [40, 20]
    else:
        values[0] = [20, 20, 40]
    table = table.set_column(index, field, pa.array(values, type=field.type))
    with ipc.new_file(str(path), table.schema) as writer:
        writer.write_table(table, max_chunksize=2)
    # Rebind the altered artifact so rejection proves semantic verification.
    manifest["artifacts"][name] = fingerprint(path)
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=message):
        verify(source, output, source_manifest_sha256=digest)
