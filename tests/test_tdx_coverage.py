"""Independent multi-basin coverage and mixed-width expectations."""

import hashlib
import json
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest
from test_tdx_bounded import inventory  # noqa: F401

from scripts.produce_tdx import produce
from scripts.verify_tdx import verify_originals


@pytest.fixture
def mixed_inventory(inventory: Path) -> Path:  # noqa: F811
    data = json.loads(inventory.read_text())
    narrow = Path(data["sources"][1]["catchments"]["path"])
    with sqlite3.connect(narrow) as connection:
        connection.execute("ALTER TABLE basins RENAME TO old_basins")
        connection.execute("CREATE TABLE basins (fid INTEGER PRIMARY KEY NOT NULL, geom POLYGON, streamID MEDIUMINT)")
        connection.execute("INSERT INTO basins SELECT * FROM old_basins")
        connection.execute("DROP TABLE old_basins")
    data["sources"][1]["catchments"]["sha256"] = hashlib.sha256(narrow.read_bytes()).hexdigest()
    river = data["sources"][0]["rivers"].copy()
    # Middle basin deliberately shares native LINKNOs, but not HFX identities.
    data["sources"].append(
        {
            "basin": "15",
            "rivers": river,
            "catchments": {"status": "unavailable", "reason": "Original polygon source unavailable"},
        }
    )
    inventory.write_text(json.dumps(data))
    return inventory


def test_mixed_width_and_missing_source(mixed_inventory: Path, tmp_path: Path) -> None:
    output = tmp_path / "out"
    produce(mixed_inventory, output)
    with ipc.open_file(str(output / "catchments.arrow")) as reader:
        catchments = reader.read_all()
    assert catchments.schema.field("streamID").type == pa.int64()
    assert catchments["streamID"].to_pylist() == [9, 9, 9]
    assert catchments["processing_basin"].to_pylist() == ["10", "10", "20"]
    with ipc.open_file(str(output / "rivers.arrow")) as reader:
        rivers = reader.read_all()
    assert rivers["local_catchment_coverage"].to_pylist() == [
        "supplied",
        "supplied",
        "unavailable",
        "unavailable",
        "supplied",
        "supplied",
    ]
    assert rivers["LINKNO"].to_pylist() == [9, 42, 9, 42, 9, 42]
    assert pq.read_table(output / "river-graph.parquet")["upstream_ids"].to_pylist() == [[], [1], [], [3], [], [5]]
    assert pq.read_table(output / "local-associations.parquet").to_pylist() == [
        {"river_id": 1, "catchment_id": 1},
        {"river_id": 1, "catchment_id": 2},
        {"river_id": 5, "catchment_id": 3},
    ]
    metadata = json.loads((output / "source-metadata.json").read_text())
    polygons = [entry for entry in metadata if entry["domain"] == "catchments"]
    assert [entry["status"] for entry in polygons] == ["supplied", "unavailable", "supplied"]
    assert polygons[0]["schemas"]["basins"][2]["type"] == "MEDIUMINT"
    assert polygons[2]["schemas"]["basins"][2]["type"] == "INTEGER"
    assert verify_originals(mixed_inventory, output)["features"] == {"catchments": 3, "rivers": 6}


def test_spatial_delivery_retains_coverage(mixed_inventory: Path, tmp_path: Path) -> None:
    from hfx.spatial_bundle import build

    staging, spatial = tmp_path / "staging", tmp_path / "spatial"
    produce(mixed_inventory, staging)
    build(staging, spatial, source_manifest_sha256=hashlib.sha256((staging / "manifest.json").read_bytes()).hexdigest())
    manifest = json.loads((spatial / "manifest.json").read_text())
    river_path = manifest["families"]["rivers"]["data"]
    rivers = pq.read_table(spatial / river_path).sort_by("id")
    assert rivers["local_catchment_coverage"].to_pylist() == [
        "supplied",
        "supplied",
        "unavailable",
        "unavailable",
        "supplied",
        "supplied",
    ]
    assert manifest["categorical_columns"][0]["artifact"] == river_path
    assert (spatial / "source-metadata.json").read_bytes() == (staging / "source-metadata.json").read_bytes()
    relation_path = manifest["relationships"]["rivers"]["data"]
    with ipc.open_file(str(spatial / relation_path)) as reader:
        relations = reader.read_all()
    assert relations["local_catchment_ids"].to_pylist() == [[1, 2], [], [], [], [3], []]


@pytest.mark.parametrize(
    "declaration",
    [
        None,
        {},
        {"status": "unavailable"},
        {"status": "unavailable", "reason": ""},
        {"status": "unavailable", "reason": "missing", "path": "ignored"},
    ],
)
def test_missing_coverage_must_be_explicit(mixed_inventory: Path, tmp_path: Path, declaration: object) -> None:
    data = json.loads(mixed_inventory.read_text())
    data["sources"][-1]["catchments"] = declaration
    mixed_inventory.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        produce(mixed_inventory, tmp_path / "out")
