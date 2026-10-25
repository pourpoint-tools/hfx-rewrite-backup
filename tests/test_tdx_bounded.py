"""Multi-basin expectations are hand-enumerated, not derived by the producer."""

import hashlib
import json
import sqlite3
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest

from scripts import produce_tdx
from scripts.verify_tdx import verify_originals


@pytest.fixture
def inventory(tmp_path: Path) -> Path:
    sources: list[dict[str, Any]] = []
    for basin in ("20", "10"):
        item: dict[str, Any] = {"basin": basin}
        for domain in ("catchments", "rivers"):
            path = tmp_path / f"{basin}-{domain}.gpkg"
            polygon = domain == "catchments"
            layer = "basins" if polygon else "TDX_streamnet_7020000010_01"
            kind = "POLYGON" if polygon else "LINESTRING"
            wkb = (
                struct.pack("<BIII10d", 1, 3, 1, 5, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0)
                if polygon
                else struct.pack("<BII4d", 1, 2, 2, 3, 4, 1, 2)
            )
            geometry = b"GP" + bytes([0, 1]) + struct.pack("<i", 4326) + wkb
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, srs_id INTEGER)")
                connection.execute("INSERT INTO gpkg_contents VALUES (?, 'features', 4326)", (layer,))
                connection.execute(
                    "CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, geometry_type_name TEXT, srs_id INTEGER, z INTEGER, m INTEGER)"
                )
                connection.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, 4326, 0, 0)", (layer, kind))
                if polygon:
                    connection.execute(
                        "CREATE TABLE basins (fid INTEGER PRIMARY KEY NOT NULL, geom POLYGON, streamID INTEGER)"
                    )
                    fids = [17, 5] if basin == "10" else [5]
                    connection.executemany("INSERT INTO basins VALUES (?, ?, 9)", [(fid, geometry) for fid in fids])
                else:
                    connection.execute(
                        "CREATE TABLE TDX_streamnet_7020000010_01 (fid INTEGER PRIMARY KEY NOT NULL, geom LINESTRING, LINKNO MEDIUMINT, DSLINKNO MEDIUMINT, USLINKNO1 MEDIUMINT, USLINKNO2 MEDIUMINT)"
                    )
                    connection.executemany(
                        "INSERT INTO TDX_streamnet_7020000010_01 VALUES (?, ?, ?, ?, ?, -1)",
                        [(7, geometry, 42, -1, 9), (3, geometry, 9, 42, -1)],
                    )
            item[domain] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        sources.append(item)
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({"release": "NGA-TDX-Hydro-20230126", "sources": sources}))
    return path


def test_projected_basin_workspace_and_global_ids(
    inventory: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "normalized"
    original = produce_tdx.source_relationships
    seen: list[tuple[list[tuple[int, int, int, int, int]], list[tuple[int, int]]]] = []

    def relationships(
        rivers: list[tuple[int, int, int, int, int]], polygons: list[tuple[int, int]]
    ) -> tuple[dict[int, list[int]], list[tuple[int, int]]]:
        # Topology must be reconstructed from closed authoritative feature files.
        assert (output / "rivers.arrow").exists()
        seen.append((rivers.copy(), polygons.copy()))
        return original(rivers, polygons)

    monkeypatch.setattr(produce_tdx, "source_relationships", relationships)
    # A projected pass, not a second geometry decode, supplies topology.
    projected = produce_tdx._projected_rows
    projections: list[list[str]] = []

    def rows(path: Path, names: list[str]) -> Iterator[dict[str, Any]]:
        projections.append(names)
        assert "geometry" not in names
        yield from projected(path, names)

    monkeypatch.setattr(produce_tdx, "_projected_rows", rows)
    produce_tdx.produce(inventory, output)
    assert len(projections) == 2
    assert seen == [
        ([(1, 9, 42, -1, -1), (2, 42, -1, 9, -1)], [(1, 9), (2, 9)]),
        ([(3, 9, 42, -1, -1), (4, 42, -1, 9, -1)], [(3, 9)]),
    ]
    assert pq.read_table(output / "river-graph.parquet")["upstream_ids"].to_pylist() == [[], [1], [], [3]]
    assert pq.read_table(output / "local-associations.parquet").to_pylist() == [
        {"river_id": 1, "catchment_id": 1},
        {"river_id": 1, "catchment_id": 2},
        {"river_id": 3, "catchment_id": 3},
    ]
    with ipc.open_file(str(output / "catchments.arrow")) as reader:
        table = reader.read_all()
    assert table["id"].to_pylist() == [1, 2, 3]
    assert table["source_id"].to_pylist() == ["5", "17", "5"]
    assert table["processing_basin"].to_pylist() == ["10", "10", "20"]
    assert verify_originals(inventory, output)["features"] == {"catchments": 3, "rivers": 4}


def test_feature_batches_can_cross_basin_boundaries(inventory: Path, tmp_path: Path) -> None:
    from hfx.candidates import fingerprint

    output = tmp_path / "normalized"
    produce_tdx.produce(inventory, output)
    manifest = json.loads((output / "manifest.json").read_text())
    for domain in ("rivers", "catchments"):
        path = output / f"{domain}.arrow"
        with ipc.open_file(str(path)) as reader:
            table = reader.read_all()
        with ipc.new_file(str(path), table.schema) as writer:
            writer.write_table(table.combine_chunks(), max_chunksize=3)
        manifest["artifacts"][path.name] = fingerprint(path)
    (output / "manifest.json").write_text(json.dumps(manifest))
    assert verify_originals(inventory, output)["features"] == {"catchments": 3, "rivers": 4}


@pytest.mark.parametrize(
    "column,value,error", [("streamID", 42, "Native value"), ("geometry", b"corrupt", "geometry bytes")]
)
def test_later_basin_fidelity(inventory: Path, tmp_path: Path, column: str, value: int | bytes, error: str) -> None:
    import pyarrow as pa

    from hfx.candidates import fingerprint

    output = tmp_path / "normalized"
    produce_tdx.produce(inventory, output)
    path = output / "catchments.arrow"
    with ipc.open_file(str(path)) as reader:
        table = reader.read_all()
    rows = table.to_pylist()
    rows[-1][column] = value
    with ipc.new_file(str(path), table.schema) as writer:
        writer.write_table(pa.Table.from_pylist(rows, schema=table.schema))
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["artifacts"][path.name] = fingerprint(path)
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=error):
        verify_originals(inventory, output)
