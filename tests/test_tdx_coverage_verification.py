"""Coverage and provenance corruption must fail independent source verification."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest
from test_tdx_bounded import inventory  # noqa: F401
from test_tdx_coverage import mixed_inventory  # noqa: F401

from hfx.candidates import fingerprint
from scripts.produce_tdx import produce
from scripts.verify_tdx import verify_originals


@pytest.mark.parametrize(
    "corruption", ["reason", "declaration", "missing", "extra", "coverage", "nullable", "type", "association"]
)
def test_coverage_provenance_corruption(mixed_inventory: Path, tmp_path: Path, corruption: str) -> None:  # noqa: F811
    output = tmp_path / "out"
    produce(mixed_inventory, output)
    name = "source-metadata.json"
    if corruption == "association":
        name = "local-associations.parquet"
        table = pq.read_table(output / name)
        rows = table.to_pylist() + [{"river_id": 3, "catchment_id": 1}]
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), output / name)
    elif corruption in ("coverage", "nullable", "type"):
        name = "rivers.arrow"
        with ipc.open_file(str(output / name)) as reader:
            table = reader.read_all()
        index = table.schema.get_field_index("local_catchment_coverage")
        if corruption == "coverage":
            values = table.column(index).to_pylist()
            values[2] = "supplied"
            table = table.set_column(index, table.schema.field(index), pa.array(values))
        elif corruption == "type":
            table = table.set_column(
                index,
                pa.field("local_catchment_coverage", pa.int8(), nullable=False),
                pa.array([0] * len(table), type=pa.int8()),
            )
        else:
            table = table.set_column(index, pa.field("local_catchment_coverage", pa.string()), table.column(index))
        with ipc.new_file(str(output / name), table.schema) as writer:
            writer.write_table(table)
    else:
        metadata = json.loads((output / name).read_text())
        if corruption == "reason":
            metadata[2]["reason"] = "Not the acquisition reason"
        elif corruption == "declaration":
            metadata[0]["schemas"]["basins"][2]["type"] = "INTEGER"
        elif corruption == "missing":
            metadata.pop()
        else:
            metadata.append(metadata[0])
        (output / name).write_text(json.dumps(metadata))
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["artifacts"][name] = fingerprint(output / name)
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="coverage|metadata|associations"):
        verify_originals(mixed_inventory, output)


@pytest.mark.parametrize("corruption", ["missing", "meaning"])
def test_manifest_coverage_semantics(mixed_inventory: Path, tmp_path: Path, corruption: str) -> None:  # noqa: F811
    output = tmp_path / "out"
    produce(mixed_inventory, output)
    manifest = json.loads((output / "manifest.json").read_text())
    if corruption == "missing":
        del manifest["categorical_columns"]
    else:
        manifest["categorical_columns"][0]["codes"][1]["meaning"] = "Naturally polygonless river"
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="coverage"):
        verify_originals(mixed_inventory, output)
