"""Production relationships retain source evidence and bind final feature artifacts."""

from copy import deepcopy
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest
from test_data_interface_relationships import _records, _source


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
