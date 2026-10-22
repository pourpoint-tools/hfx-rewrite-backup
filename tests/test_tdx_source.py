"""Original GeoPackage witnesses defined without the ingestion implementation."""

import sqlite3
import struct
from pathlib import Path

import pyarrow as pa
import pytest

from hfx.tdx_source import read_layer


def original_pair_layer(path: Path) -> bytes:
    # GeoPackage standard header, little-endian WKB, deliberately descending vertices.
    wkb = struct.pack("<BII4d", 1, 2, 2, 3.0, 4.0, 1.0, 2.0)
    geometry = b"GP" + bytes([0, 1]) + struct.pack("<i", 4326) + wkb
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT, srs_id INTEGER)")
        connection.execute("INSERT INTO gpkg_contents VALUES ('TDX_streamnet_7020000010_01', 'features', 4326)")
        connection.execute(
            "CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, geometry_type_name TEXT, srs_id INTEGER, z INTEGER, m INTEGER)"
        )
        connection.execute(
            "INSERT INTO gpkg_geometry_columns VALUES ('TDX_streamnet_7020000010_01', 'geom', 'LINESTRING', 4326, 0, 0)"
        )
        connection.execute(
            "CREATE TABLE TDX_streamnet_7020000010_01 (fid INTEGER PRIMARY KEY NOT NULL, geom LINESTRING, LINKNO MEDIUMINT, DSLINKNO MEDIUMINT, DSContArea REAL)"
        )
        connection.executemany(
            "INSERT INTO TDX_streamnet_7020000010_01 VALUES (?, ?, ?, ?, ?)",
            [(7, geometry, 42, -1, None), (3, geometry, 9, 42, 12.5)],
        )
    return wkb


def test_native_types_nulls_identity_and_geometry_order(tmp_path: Path) -> None:
    path = tmp_path / "streamnet.gpkg"
    wkb = original_pair_layer(path)
    batches = list(read_layer(path, "rivers", batch_rows=1))
    table = pa.Table.from_batches(batches)
    assert [len(batch) for batch in batches] == [1, 1]
    assert table.column_names == ["fid", "geom", "LINKNO", "DSLINKNO", "DSContArea"]
    assert table["fid"].to_pylist() == [3, 7]
    assert table["LINKNO"].type == pa.int32()
    assert table["fid"].type == pa.int64()
    assert table["DSContArea"].type == pa.float64()
    assert table["DSContArea"].to_pylist() == [12.5, None]
    assert table["geom"].to_pylist() == [wkb, wkb]
    assert table.schema.field("LINKNO").metadata[b"gpkg:declared_type"] == b"MEDIUMINT"
    assert not table.schema.field("fid").nullable
    assert table.schema.field("DSContArea").nullable


def test_rejects_source_type_mismatch_instead_of_coercing(tmp_path: Path) -> None:
    path = tmp_path / "streamnet.gpkg"
    original_pair_layer(path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE TDX_streamnet_7020000010_01 SET LINKNO = 'unknown' WHERE fid = 3")
    with pytest.raises(ValueError, match="LINKNO.*storage type"):
        list(read_layer(path, "rivers"))


def test_polygon_features_keep_distinct_identity_under_shared_stream_id(tmp_path: Path) -> None:
    path = tmp_path / "basins.gpkg"
    original_pair_layer(path)
    polygon = struct.pack("<BIII10d", 1, 3, 1, 5, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0)
    geometry = b"GP" + bytes([0, 3]) + struct.pack("<i4d", 4326, 0, 1, 0, 1) + polygon
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE TDX_streamnet_7020000010_01")
        connection.execute("UPDATE gpkg_contents SET table_name = 'basins'")
        connection.execute("UPDATE gpkg_geometry_columns SET table_name = 'basins', geometry_type_name = 'GEOMETRY'")
        connection.execute("CREATE TABLE basins (fid INTEGER PRIMARY KEY NOT NULL, geom GEOMETRY, streamID INTEGER)")
        connection.executemany("INSERT INTO basins VALUES (?, ?, ?)", [(1, geometry, 9), (2, geometry, 9)])
    table = pa.Table.from_batches(read_layer(path, "catchments"))
    assert table["fid"].to_pylist() == [1, 2]
    assert table["streamID"].to_pylist() == [9, 9]
    assert table["streamID"].type == pa.int64()
    assert table["geom"].to_pylist() == [polygon, polygon]


@pytest.mark.parametrize("flags", [0x11, 0x21, 0x81, 0x05])
def test_unsupported_geometry_headers_fail(tmp_path: Path, flags: int) -> None:
    path = tmp_path / "streamnet.gpkg"
    wkb = original_pair_layer(path)
    geometry = b"GP" + bytes([0, flags]) + struct.pack("<i", 4326) + wkb
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE TDX_streamnet_7020000010_01 SET geom = ?", (geometry,))
    with pytest.raises(ValueError, match="GeoPackage geometry"):
        list(read_layer(path, "rivers"))


def test_wrong_crs_refused_before_values(tmp_path: Path) -> None:
    path = tmp_path / "streamnet.gpkg"
    original_pair_layer(path)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE gpkg_contents SET srs_id = 3857")
    with pytest.raises(ValueError, match="EPSG:4326"):
        list(read_layer(path, "rivers"))


def test_pair_production_preserves_originals_and_builds_only_supplied_graph(tmp_path: Path) -> None:
    import hashlib
    import json

    import pyarrow.ipc as ipc
    import pyarrow.parquet as pq

    from scripts.produce_tdx import produce

    rivers = tmp_path / "rivers.gpkg"
    original_pair_layer(rivers)
    with sqlite3.connect(rivers) as connection:
        connection.execute("ALTER TABLE TDX_streamnet_7020000010_01 ADD COLUMN USLINKNO1 MEDIUMINT")
        connection.execute("ALTER TABLE TDX_streamnet_7020000010_01 ADD COLUMN USLINKNO2 MEDIUMINT")
        connection.execute(
            "UPDATE TDX_streamnet_7020000010_01 SET USLINKNO1 = CASE WHEN LINKNO=42 THEN 9 ELSE -1 END, USLINKNO2=-1"
        )
    polygons = tmp_path / "basins.gpkg"
    original_pair_layer(polygons)
    polygon = struct.pack("<BIII10d", 1, 3, 1, 5, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0)
    geometry = b"GP" + bytes([0, 1]) + struct.pack("<i", 4326) + polygon
    with sqlite3.connect(polygons) as connection:
        connection.execute("DROP TABLE TDX_streamnet_7020000010_01")
        connection.execute("UPDATE gpkg_contents SET table_name = 'basins'")
        connection.execute("UPDATE gpkg_geometry_columns SET table_name = 'basins', geometry_type_name = 'GEOMETRY'")
        connection.execute("CREATE TABLE basins (fid INTEGER PRIMARY KEY NOT NULL, geom GEOMETRY, streamID INTEGER)")
        connection.executemany("INSERT INTO basins VALUES (?, ?, ?)", [(1, geometry, 9), (2, geometry, 9)])
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "release": "NGA-TDX-Hydro-20230126",
                "sources": [
                    {
                        "basin": "7020000010",
                        "catchments": {
                            "path": str(polygons),
                            "sha256": hashlib.sha256(polygons.read_bytes()).hexdigest(),
                        },
                        "rivers": {"path": str(rivers), "sha256": hashlib.sha256(rivers.read_bytes()).hexdigest()},
                    }
                ],
            }
        )
    )
    output = tmp_path / "normalized"
    produce(inventory, output)
    manifest = json.loads((output / "manifest.json").read_text())
    assert "graph" not in manifest
    assert "river_nodes" not in manifest
    assert manifest["catchment_connectivity"] == [{"level": 0, "status": "not_supplied"}]
    assert ipc.open_file(output / "catchments.arrow").read_all()["fid"].to_pylist() == [1, 2]
    assert pq.read_table(output / "local-associations.parquet").to_pylist() == [
        {"river_id": 1, "catchment_id": 1},
        {"river_id": 1, "catchment_id": 2},
    ]
    assert pq.read_table(output / "river-graph.parquet")["upstream_ids"].to_pylist() == [[], [1]]
    from scripts.verify_tdx import verify_originals

    receipt = verify_originals(inventory, output)
    assert receipt["features"] == {"catchments": 2, "rivers": 2}
    # Re-pin artifact hashes so this tests independent source comparison, not hashing.
    from hfx.candidates import fingerprint

    catchment_file = output / "catchments.arrow"
    native_bytes = catchment_file.read_bytes()
    table = ipc.open_file(catchment_file).read_all()
    corrupted = table.set_column(
        table.schema.get_field_index("streamID"), table.schema.field("streamID"), pa.array([42, 9], type=pa.int64())
    )
    with ipc.new_file(catchment_file, corrupted.schema) as writer:
        writer.write_table(corrupted)
    manifest["artifacts"]["catchments.arrow"] = fingerprint(catchment_file)
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Native value"):
        verify_originals(inventory, output)
    catchment_file.write_bytes(native_bytes)
    manifest["artifacts"]["catchments.arrow"] = fingerprint(catchment_file)
    (output / "manifest.json").write_text(json.dumps(manifest))

    with sqlite3.connect(polygons) as connection:
        connection.execute("UPDATE basins SET streamID = 42 WHERE fid = 1")
    with pytest.raises(ValueError, match="digest"):
        verify_originals(inventory, output)
