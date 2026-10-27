"""Independent examples for the source-specific GRIT producer."""

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("numpy")
pytest.importorskip("pyproj")
pytest.importorskip("shapely")

from scripts.produce_grit import Identities


def test_source_namespaces_preserve_colliding_native_ids(tmp_path: Path) -> None:
    with sqlite3.connect(tmp_path / "identities.sqlite") as connection:
        identities = Identities(connection)
        segment = identities.add("rivers", "grit:1.0:SP:segments:lines", 10)
        reach = identities.add("rivers", "grit:1.0:SP:reaches:lines", 10)
        node = identities.add("nodes", "grit:1.0:SP:segments:nodes", 10)
        assert segment != reach
        assert min(segment, reach, node) > 0
        assert identities.get("grit:1.0:SP:segments:lines", 10) == segment
        assert identities.get("grit:1.0:SP:reaches:lines", 10) == reach
        with pytest.raises(ValueError, match="duplicate source identity"):
            identities.add("rivers", "grit:1.0:SP:segments:lines", 10)
        with pytest.raises(ValueError, match="unresolved source reference"):
            identities.get("grit:1.0:SP:reaches:lines", 11)


def test_geometry_export_area_and_outward_bounds() -> None:
    import struct

    from shapely import MultiPolygon, Point, Polygon, from_wkb, to_wkb

    from scripts.produce_grit import export_geometry, geodesic_area, outward_bounds

    native = b"GP" + bytes([0, 1]) + struct.pack("<i", 8857) + to_wkb(Point(0, 0))
    point = from_wkb(export_geometry(native))
    assert point.equals_exact(Point(0, 0), 1e-12)
    west, south, east, north = outward_bounds(Point(0.1, -0.1))
    assert west <= 0.1 <= east
    assert south <= -0.1 <= north
    outer = [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]
    hole = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8), (0.2, 0.2)]
    polygon = Polygon(outer, [hole])
    reverse = Polygon(list(reversed(outer)), [list(reversed(hole))])
    assert geodesic_area(MultiPolygon([polygon, reverse])) == pytest.approx(2 * geodesic_area(polygon))
    assert geodesic_area(polygon) == pytest.approx(7877.655572414087, rel=1e-10)
    bad_crs = native[:4] + struct.pack("<i", 4326) + native[8:]
    with pytest.raises(ValueError, match="8857"):
        export_geometry(bad_crs)


def test_original_layer_mapping(tmp_path: Path) -> None:
    import json
    import struct

    import pyarrow.ipc as ipc
    from shapely import LineString, Point, Polygon, to_wkb

    from scripts.produce_grit import produce

    def blob(geometry: object) -> bytes:
        return b"GP" + bytes([0, 1]) + struct.pack("<i", 8857) + to_wkb(geometry)

    sources = []
    for product in ("segments", "reaches", "component_catchments", "segment_catchments", "reach_catchments"):
        path = tmp_path / f"{product}.gpkg"
        region = "GLOBAL" if product == "component_catchments" else "SP"
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE gpkg_geometry_columns (table_name TEXT,column_name TEXT,geometry_type_name TEXT,srs_id INTEGER,z INTEGER,m INTEGER)"
            )
            if product in ("segments", "reaches"):
                connection.execute(
                    "CREATE TABLE lines (fid INTEGER PRIMARY KEY,geom BLOB,global_id INTEGER,catchment_id INTEGER,segment_id INTEGER,upstream_node_id INTEGER,downstream_node_id INTEGER,upstream_line_ids TEXT,downstream_line_ids TEXT,name TEXT)"
                )
                connection.execute(
                    "INSERT INTO lines VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        1,
                        blob(LineString([(0, 0), (100, 100)])),
                        10,
                        10,
                        10 if product == "reaches" else None,
                        10,
                        11,
                        "",
                        "",
                        None,
                    ),
                )
                connection.execute(
                    "CREATE TABLE nodes (fid INTEGER PRIMARY KEY,geom BLOB,global_id INTEGER,segment_node_id REAL,upstream_line_ids TEXT,downstream_line_ids TEXT)"
                )
                connection.executemany(
                    "INSERT INTO nodes VALUES (?,?,?,?,?,?)",
                    [
                        (1, blob(Point(0, 0)), 10, 10.0 if product == "reaches" else None, "", "10"),
                        (2, blob(Point(100, 100)), 11, None, "10", ""),
                    ],
                )
                tables = [("lines", "LINESTRING"), ("nodes", "POINT")]
            else:
                table = product + "__1"
                connection.execute(
                    f"CREATE TABLE {table} (fid INTEGER PRIMARY KEY,geom BLOB,global_id INTEGER,catchment_id INTEGER,segment_id INTEGER,area REAL)"
                )
                connection.execute(
                    f"INSERT INTO {table} VALUES (?,?,?,?,?,?)",
                    (1, blob(Polygon([(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)])), 10, 10, 10, 0.04),
                )
                tables = [(table, "POLYGON")]
            connection.executemany("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, 8857, 0, 0)", tables)
        sources.append({"path": str(path), "region": region, "product": product})
    import hashlib

    license_path = tmp_path / "LICENSE.md"
    license_path.write_text("synthetic source license")
    inventory = {
        "sources": sources,
        "components": [10],
        "synthetic_fixture": True,
        "documents": [
            {
                "name": "LICENSE.md",
                "path": str(license_path),
                "size_bytes": license_path.stat().st_size,
                "md5": hashlib.md5(license_path.read_bytes()).hexdigest(),
            }
        ],
    }
    inventory_path = tmp_path / "inputs.json"
    inventory_path.write_text(json.dumps(inventory))
    output = tmp_path / "output"
    produce(inventory_path, output)
    rivers = ipc.open_file(str(output / "rivers.arrow")).read_all().to_pylist()
    nodes = ipc.open_file(str(output / "river-nodes.arrow")).read_all().to_pylist()
    catches = ipc.open_file(str(output / "catchments.arrow")).read_all().to_pylist()
    segment, reach = sorted(rivers, key=lambda r: r["level"])
    assert segment["id"] != reach["id"]
    assert reach["parent_id"] == segment["id"]
    assert segment["source_global_id"] == reach["source_global_id"] == 10
    assert segment["source_name"] is None
    assert len({c["id"] for c in catches}) == 3
    assert [c["level"] for c in catches] == [0, 1, 2]
    assert catches[0]["outlet_lon"] is None
    assert reach["local_catchment_id"] == catches[2]["id"]
    assert reach["component_catchment_id"] == catches[0]["id"]
    mapped = next(n for n in nodes if n["level"] == 1 and n["source_global_id"] == 10)
    assert mapped["source_segment_node_id"] == 10.0
    assert mapped["coarser_node_id"] == segment["upstream_node_id"]
    unmapped = next(n for n in nodes if n["level"] == 1 and n["source_global_id"] == 11)
    assert unmapped["coarser_node_id"] is None
    assert unmapped["source_segment_node_id"] is None
    manifest = json.loads((output / "manifest.json").read_text())
    assert {p.name for p in output.iterdir()} == set(manifest["artifacts"]) | {"manifest.json"}
    assert output.with_name(output.name + "-production.sqlite").is_file()
    assert (output / "GRIT-original-LICENSE.md").read_bytes() == license_path.read_bytes()
    assert manifest["unit_count"] == 3
    assert manifest["rivers"]["count"] == 2
    assert manifest["river_nodes"]["count"] == 4
    assert manifest["catchment_connectivity"][0] == {"level": 0, "status": "not_supplied"}
    assert catches[1]["outlet_lon"] is not None
    assert catches[1]["outlet_lat"] is not None
    lookup = ipc.open_file(str(output / "lookup.arrow"))
    assert b"hfx:catchments_sha256" in lookup.schema.metadata


def test_directed_diamond_and_cycle_rejection(tmp_path: Path) -> None:
    from scripts.produce_grit import check_dag

    with sqlite3.connect(tmp_path / "graph.sqlite") as connection:
        connection.execute(
            "CREATE TABLE edges (family TEXT, upstream INTEGER, downstream INTEGER, PRIMARY KEY(family,upstream,downstream))"
        )
        connection.executemany("INSERT INTO edges VALUES ('rivers',?,?)", [(1, 2), (1, 3), (2, 4), (3, 4)])
        check_dag(connection, "rivers")
        assert connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 4
        connection.execute("INSERT INTO edges VALUES ('rivers',4,1)")
        with pytest.raises(ValueError, match="cycle"):
            check_dag(connection, "rivers")
        assert connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 5


def test_archive_identity_binds_loose_geopackage(tmp_path: Path) -> None:
    import hashlib
    import zipfile

    from scripts.produce_grit import verify_archives

    source = tmp_path / "original.gpkg"
    source.write_bytes(b"original source bytes")
    archive = tmp_path / "original.gpkg.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr(source.name, source.read_bytes())
    inventory: dict[str, object] = {
        "sources": [
            {
                "path": str(source),
                "archive": {"path": str(archive), "md5": hashlib.md5(archive.read_bytes()).hexdigest()},
            }
        ]
    }
    verify_archives(inventory)
    source.write_bytes(b"different loose source")
    with pytest.raises(ValueError, match="extracted source differs"):
        verify_archives(inventory)


def test_node_incidence_lookup_work_is_bounded(tmp_path: Path) -> None:
    from scripts.produce_grit import source_graph

    with sqlite3.connect(tmp_path / "incidence.sqlite") as connection:
        identities = Identities(connection)
        source_graph([], identities)
        connection.executemany("INSERT INTO endpoints VALUES (?,?,?)", ((i, i, i + 1) for i in range(1, 10001)))
        steps = 0

        def count_steps() -> int:
            nonlocal steps
            steps += 1
            return 0

        connection.set_progress_handler(count_steps, 1)
        for endpoint, value, expected in (("upstream", 5000, 5000), ("downstream", 5000, 4999)):
            assert connection.execute(f"SELECT river FROM endpoints WHERE {endpoint}=?", (value,)).fetchall() == [
                (expected,)
            ]
        connection.set_progress_handler(None, 0)
        # Indexed point queries must not visit the 10,000 unrelated endpoint rows.
        assert steps < 500


def test_global_delivery_requires_exact_release_inventory() -> None:
    from scripts.produce_grit import verify_global_inventory

    with pytest.raises(ValueError, match="29"):
        verify_global_inventory({"sources": [], "external_rasters": True})
    import json

    pinned = json.loads((Path(__file__).parents[1] / "scripts/provenance/grit-original-inventory.json").read_text())
    assert len(pinned["archives"]) == 29
    assert sum(item["size_bytes"] for item in pinned["archives"]) == 21_319_552_599
    inventory = {
        "sources": [
            {
                "region": item["region"],
                "product": item["product"],
                "path": item["member"],
                "archive": {"md5": item["md5"]},
            }
            for item in pinned["archives"]
        ],
        "documents": pinned["documents"],
    }
    verify_global_inventory(inventory)
    inventory["sources"][0]["archive"]["md5"] = "0" * 32
    with pytest.raises(ValueError, match="pinned release"):
        verify_global_inventory(inventory)


def test_catchment_upstream_join_does_not_scan_unrelated_edges(tmp_path: Path) -> None:
    from scripts.produce_grit import source_graph

    with sqlite3.connect(tmp_path / "upstream.sqlite") as db:
        identities = Identities(db)
        source_graph([], identities)
        for key in range(1, 10001):
            identities.add("rivers", "original-segments", key)
        db.executemany("INSERT INTO edges VALUES ('rivers',?,?)", ((key, key + 1) for key in range(1, 10000)))
        steps = 0

        def count_steps() -> int:
            nonlocal steps
            steps += 1
            return 0

        db.set_progress_handler(count_steps, 1)
        upstream = db.execute(
            "SELECT i.source_id FROM edges e JOIN identities i ON i.family='rivers' AND i.id=e.upstream WHERE e.family='rivers' AND e.downstream=? ORDER BY i.source_id",
            (5000,),
        ).fetchall()
        db.set_progress_handler(None, 0)
        assert upstream == [(4999,)]
        # A point lookup must not visit the other 9,998 source edges.
        assert steps < 500
