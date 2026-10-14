"""Independent original-GRIT fidelity checks; not a supported reader."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.ipc as ipc
from rasterio.warp import transform_geom
from shapely import from_wkb
from shapely.geometry import mapping

from scripts.verify_vector import _ipc_compression

# Separate GDAL and pyproj paths can round differently; ~0.1 mm in latitude.
# Record the measured maximum; never widen this tolerance to accept a failure.
COORDINATE_TOLERANCE_DEGREES = 1e-9
SOURCE_TYPES = {"INTEGER": pa.int64(), "REAL": pa.float64(), "TEXT": pa.string()}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def source_schema(path: Path, layer: str) -> dict[str, str]:
    """Inspect declared physical source types, excluding only the geometry column."""
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
        geometry = connection.execute(
            "SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?", (layer,)
        ).fetchone()
        require(geometry is not None, f"missing source geometry declaration: {layer}")
        columns = connection.execute("SELECT name,type FROM pragma_table_info(?)", (layer,))
        result = {name: kind for name, kind in columns if name != geometry[0]}
    require(
        bool(result) and all(kind in SOURCE_TYPES for kind in result.values()), "unsupported original physical type"
    )
    return result


def coordinate_error(expected: object, actual: object) -> float:
    if isinstance(expected, (int, float)):
        require(isinstance(actual, (int, float)), "coordinate dimensionality differs")
        number = cast(float, actual)
        require(math.isfinite(expected) and math.isfinite(number), "nonfinite coordinate")
        difference = abs(expected - number)
        require(difference <= COORDINATE_TOLERANCE_DEGREES, f"coordinate differs by {difference} degrees")
        return difference
    require(isinstance(expected, Sequence) and isinstance(actual, Sequence), "coordinate structure differs")
    left, right = cast(Sequence[object], expected), cast(Sequence[object], actual)
    require(len(left) == len(right), "coordinate count differs")
    return max((coordinate_error(a, b) for a, b in zip(left, right, strict=True)), default=0.0)


def compare_feature(
    feature: Mapping[str, object], crs: object, schema: dict[str, str], batch: pa.RecordBatch, row: int
) -> float:
    """Compare one GDAL-exported original against one output row, including null types."""
    properties = dict(cast(Mapping[str, object], feature["properties"]))
    properties["fid"] = int(cast(str, feature["id"]))
    require(set(properties) == set(schema), "GDAL export differs from original field schema")
    for name, kind in schema.items():
        output_name = f"source_{name}"
        require(output_name in batch.schema.names, f"missing {output_name}")
        require(batch.schema.field(output_name).type == SOURCE_TYPES[kind], f"type differs: {output_name}")
        require(batch.column(output_name)[row].as_py() == properties[name], f"value/null differs: {output_name}")
    require(batch.schema.field("geometry").type == pa.binary(), "geometry type must be binary")
    original = transform_geom(crs, "EPSG:4326", feature["geometry"])
    actual = mapping(from_wkb(batch.column("geometry")[row].as_py()))
    require(original["type"] == actual["type"], "geometry type differs")
    return coordinate_error(original["coordinates"], actual["coordinates"])


def verify_lookup(db: sqlite3.Connection, entity: str, path: Path, directory: Path, digest: str, count: int) -> None:
    _ipc_compression(path, compressed=False)
    binding = b"hfx:catchments_sha256" if entity == "catchments" else b"hfx:data_sha256"
    expected = pa.schema(
        [pa.field("id", pa.int64(), False), pa.field("block", pa.int32(), False), pa.field("row", pa.int32(), False)],
        metadata={b"hfx:format_version": b"0.4.0", binding: digest.encode()},
    )
    entries: list[dict[str, int]] = []
    previous, seen = 0, 0
    with pa.memory_map(str(path), "r") as mapped:
        reader = ipc.open_file(mapped)
        require(reader.schema.equals(expected, check_metadata=True), "lookup schema/binding differs")
        for number in range(reader.num_record_batches):
            batch = reader.get_batch(number)
            require(batch.num_rows == min(65536, count - seen) and batch.num_rows > 0, "lookup batch size differs")
            records = batch.to_pylist()
            for record in records:
                identifier, block, row = record["id"], record["block"], record["row"]
                require(type(identifier) is int and identifier > previous, "lookup IDs not positive sorted unique")
                address = db.execute(
                    "SELECT block,row FROM addresses WHERE entity=? AND id=?", (entity, identifier)
                ).fetchone()
                require(address == (block, row), "lookup address differs")
                previous = identifier
                seen += 1
            entries.append({"batch": number, "min_id": records[0]["id"], "max_id": previous, "rows": batch.num_rows})
    require(seen == count, "lookup coverage differs")
    require(json.loads(directory.read_text()) == {"version": 1, "batches": entries}, "lookup directory differs")


PRODUCTS = {
    "component_catchments": ("catchments", 0, ("component_catchments__1",)),
    "segment_catchments": ("catchments", 1, ("segment_catchments__1",)),
    "reach_catchments": ("catchments", 2, ("reach_catchments__1",)),
    "segments": ("rivers", 0, ("lines", "nodes")),
    "reaches": ("rivers", 1, ("lines", "nodes")),
}


def namespace(region: str, product: str, layer: str) -> str:
    return f"grit:1.0:{region}:{product}:{layer}"


def prepare_database(path: Path) -> sqlite3.Connection:
    require(not path.exists(), "verification scratch already exists")
    db = sqlite3.connect(path)
    db.executescript("""
        PRAGMA cache_size=-16384;
        PRAGMA temp_store=FILE;
        CREATE TABLE addresses(entity TEXT, id INTEGER, block INTEGER, row INTEGER, PRIMARY KEY(entity,id));
        CREATE TABLE features(entity TEXT, id INTEGER, namespace TEXT, source_id TEXT, level INTEGER,
            attrs TEXT, geometry BLOB, seen INTEGER DEFAULT 0,
            PRIMARY KEY(entity,id), UNIQUE(entity,namespace,source_id));
        CREATE TABLE edges(entity TEXT, upstream INTEGER, downstream INTEGER,
            PRIMARY KEY(entity,upstream,downstream));
        CREATE INDEX edges_downstream ON edges(entity,downstream,upstream);
        CREATE TABLE expected_edges(entity TEXT, upstream INTEGER, downstream INTEGER,
            PRIMARY KEY(entity,upstream,downstream));
        CREATE TABLE reverse_edges(entity TEXT, upstream INTEGER, downstream INTEGER,
            PRIMARY KEY(entity,upstream,downstream));
        CREATE TABLE incidence(node INTEGER, river INTEGER, endpoint TEXT, PRIMARY KEY(node,river,endpoint));
        CREATE TABLE expected_incidence(node INTEGER, river INTEGER, endpoint TEXT, PRIMARY KEY(node,river,endpoint));
    """)
    return db


def structural_schema(entity: str) -> pa.Schema:
    bbox = pa.struct([pa.field(name, pa.float32(), False) for name in ("xmin", "ymin", "xmax", "ymax")])
    common: list[pa.Field] = [pa.field("id", pa.int64(), False), pa.field("level", pa.int16(), False)]
    if entity == "graph":
        return pa.schema(
            common
            + [pa.field("upstream_ids", pa.list_(pa.field("item", pa.int64(), False)), False)]
            + [pa.field(name, pa.float32(), False) for name in ("bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy")]
        )
    common += [
        pa.field("source_namespace", pa.string(), False),
        pa.field("source_id", pa.string(), False),
        pa.field("bbox", bbox, False),
        pa.field("geometry", pa.binary(), False),
    ]
    if entity == "catchments":
        extra = [
            pa.field("parent_id", pa.int64()),
            pa.field("area_km2", pa.float32(), False),
            pa.field("up_area_km2", pa.float32()),
            pa.field("outlet_lon", pa.float64()),
            pa.field("outlet_lat", pa.float64()),
        ]
    elif entity == "rivers":
        extra = [
            pa.field(name, pa.int64())
            for name in (
                "parent_id",
                "local_catchment_id",
                "component_catchment_id",
                "upstream_node_id",
                "downstream_node_id",
            )
        ] + [pa.field("geometry_orientation", pa.int8(), False)]
    else:
        extra = [pa.field("coarser_node_id", pa.int64())]
    return pa.schema(common + extra)


def check_schema(actual: pa.Schema, entity: str) -> None:
    for field in structural_schema(entity):
        require(
            field.name in actual.names and actual.field(field.name).equals(field),
            f"structural schema differs: {entity}.{field.name}",
        )


def check_nonnull(batch: pa.RecordBatch, entity: str) -> None:
    for field in structural_schema(entity):
        column = batch.column(field.name)
        if not field.nullable:
            require(column.null_count == 0, f"nonnull structural value missing: {field.name}")
        if field.name == "bbox":
            require(
                all(cast(pa.StructArray, column).field(child.name).null_count == 0 for child in field.type),
                "nonnull bbox child missing",
            )
        elif field.name == "upstream_ids":
            require(cast(pa.ListArray, column).values.null_count == 0, "nonnull graph edge missing")


def stage_output(db: sqlite3.Connection, entity: str, path: Path) -> pa.Schema:
    _ipc_compression(path, compressed=True)
    with pa.memory_map(str(path), "r") as mapped:
        reader = ipc.open_file(mapped)
        schema = reader.schema
        check_schema(schema, entity)
        for block in range(reader.num_record_batches):
            batch = reader.get_batch(block)
            check_nonnull(batch, entity)
            require(batch.num_rows > 0, "empty data batch")
            for row, record in enumerate(batch.to_pylist()):
                identifier, level = record["id"], record["level"]
                require(
                    type(identifier) is int and identifier > 0 and type(level) is int and level >= 0,
                    "invalid feature ID/level",
                )
                geometry = record.pop("geometry")
                require(isinstance(geometry, bytes), "null geometry")
                db.execute("INSERT INTO addresses VALUES (?,?,?,?)", (entity, identifier, block, row))
                db.execute(
                    "INSERT INTO features(entity,id,namespace,source_id,level,attrs,geometry) VALUES (?,?,?,?,?,?,?)",
                    (
                        entity,
                        identifier,
                        record["source_namespace"],
                        record["source_id"],
                        level,
                        json.dumps(record, allow_nan=False),
                        geometry,
                    ),
                )
                if entity == "rivers":
                    for endpoint in ("upstream_node_id", "downstream_node_id"):
                        if record[endpoint] is not None:
                            db.execute("INSERT INTO incidence VALUES (?,?,?)", (record[endpoint], identifier, endpoint))
    db.commit()
    return schema


def mapped_id(db: sqlite3.Connection, entity: str, ns: str, value: object) -> int:
    require(value is not None and not isinstance(value, bool), "missing original identity reference")
    if isinstance(value, float):
        require(math.isfinite(value) and value.is_integer(), "nonintegral original identity reference")
        value = int(value)
    result = db.execute(
        "SELECT id FROM features WHERE entity=? AND namespace=? AND source_id=?", (entity, ns, str(value))
    ).fetchone()
    require(result is not None, f"unresolved original reference: {ns}/{value}")
    return cast(int, result[0])


def source_ids(value: object) -> list[int]:
    if value is None:
        return []
    require(isinstance(value, str), "source incidence must be a string")
    result = [int(part) for part in cast(str, value).split(",") if part]
    require(len(result) == len(set(result)) and all(item > 0 for item in result), "invalid/duplicate source incidence")
    return result


def check_reference(
    db: sqlite3.Connection,
    record: dict[str, object],
    field: str,
    target_entity: str,
    ns: str,
    source_value: object,
    *,
    coarser: bool = False,
    same_level: bool = False,
) -> None:
    expected = None if source_value is None else mapped_id(db, target_entity, ns, source_value)
    require(record[field] == expected, f"source relationship differs: {field}")
    if expected is not None:
        level = db.execute("SELECT level FROM features WHERE entity=? AND id=?", (target_entity, expected)).fetchone()[
            0
        ]
        if coarser:
            require(level < record["level"], f"parent not strictly coarser: {field}")
        if same_level:
            require(level == record["level"], f"endpoint level differs: {field}")


def relationships(db: sqlite3.Connection, entity: str, product: str, region: str, record: dict[str, object]) -> None:
    identifier = cast(int, record["id"])

    def native(name: str) -> object:
        return record[f"source_{name}"]

    def ns(target: str, layer: str) -> str:
        return namespace("GLOBAL" if target == "component_catchments" else region, target, layer)

    if entity == "river_nodes":
        check_reference(
            db,
            record,
            "coarser_node_id",
            entity,
            ns("segments", "nodes"),
            native("segment_node_id") if product == "reaches" else None,
            coarser=True,
        )
        for source_field, endpoint in (
            ("upstream_line_ids", "downstream_node_id"),
            ("downstream_line_ids", "upstream_node_id"),
        ):
            for value in source_ids(native(source_field)):
                river = mapped_id(db, "rivers", ns(product, "lines"), value)
                db.execute("INSERT INTO expected_incidence VALUES (?,?,?)", (identifier, river, endpoint))
        return
    if entity == "rivers":
        check_reference(
            db,
            record,
            "parent_id",
            entity,
            ns("segments", "lines"),
            native("segment_id") if product == "reaches" else None,
            coarser=True,
        )
        for endpoint in ("upstream_node_id", "downstream_node_id"):
            check_reference(
                db, record, endpoint, "river_nodes", ns(product, "nodes"), native(endpoint), same_level=True
            )
        local = "segment_catchments" if product == "segments" else "reach_catchments"
        # GRIT originals supply local polygons; an absent polygon is an error, not an inferred null.
        check_reference(db, record, "local_catchment_id", "catchments", ns(local, local + "__1"), native("global_id"))
        check_reference(
            db,
            record,
            "component_catchment_id",
            "catchments",
            ns("component_catchments", "component_catchments__1"),
            native("catchment_id"),
        )
        require(record["geometry_orientation"] == 0, "GRIT orientation must remain explicitly unspecified")
    elif product == "component_catchments":
        require(
            record["parent_id"] is None and record["outlet_lon"] is None and record["outlet_lat"] is None,
            "component has invented parent/outlet",
        )
        return
    else:
        parent = "component_catchments" if product == "segment_catchments" else "segment_catchments"
        check_reference(
            db,
            record,
            "parent_id",
            entity,
            ns(parent, parent + "__1"),
            native("catchment_id" if product == "segment_catchments" else "segment_id"),
            coarser=True,
        )
        line_product = "segments" if product == "segment_catchments" else "reaches"
        river = mapped_id(db, "rivers", ns(line_product, "lines"), native("global_id"))
        line_attrs = json.loads(
            db.execute("SELECT attrs FROM features WHERE entity='rivers' AND id=?", (river,)).fetchone()[0]
        )
        node = db.execute(
            "SELECT geometry FROM features WHERE entity='river_nodes' AND id=?", (line_attrs["downstream_node_id"],)
        ).fetchone()
        point = from_wkb(node[0])
        require(
            record["outlet_lon"] == point.x and record["outlet_lat"] == point.y,
            "local polygon outlet differs from source downstream node",
        )
        return
    for source_field, table in (("downstream_line_ids", "expected_edges"), ("upstream_line_ids", "reverse_edges")):
        for value in source_ids(native(source_field)):
            other = mapped_id(db, "rivers", ns(product, "lines"), value)
            up, down = (identifier, other) if table == "expected_edges" else (other, identifier)
            require(up != down, "source self edge")
            db.execute(f"INSERT INTO {table} VALUES ('rivers',?,?)", (up, down))


def equal_tables(db: sqlite3.Connection, first: str, second: str, columns: str) -> None:
    for left, right in ((first, second), (second, first)):
        mismatch = db.execute(f"SELECT {columns} FROM {left} EXCEPT SELECT {columns} FROM {right} LIMIT 1").fetchone()
        require(mismatch is None, f"{first}/{second} differ: {mismatch}")


def verify_dag(db: sqlite3.Connection, entity: str) -> None:
    db.executescript("DROP TABLE IF EXISTS degrees; CREATE TEMP TABLE degrees(id INTEGER PRIMARY KEY, n INTEGER);")
    db.execute(
        "INSERT INTO degrees SELECT f.id,COUNT(e.upstream) FROM features f LEFT JOIN edges e ON e.entity=f.entity AND e.downstream=f.id WHERE f.entity=? GROUP BY f.id",
        (entity,),
    )
    db.execute("CREATE INDEX IF NOT EXISTS degree_count ON degrees(n)")
    while True:
        rows = db.execute("SELECT id FROM degrees WHERE n=0 LIMIT 4096").fetchall()
        if not rows:
            break
        for (identifier,) in rows:
            db.execute(
                "UPDATE degrees SET n=n-1 WHERE id IN (SELECT downstream FROM edges WHERE entity=? AND upstream=?)",
                (entity, identifier),
            )
            db.execute("DELETE FROM degrees WHERE id=?", (identifier,))
    require(db.execute("SELECT 1 FROM degrees LIMIT 1").fetchone() is None, f"{entity} cycle")


def verify_originals(
    db: sqlite3.Connection, inventory: dict[str, object], schemas: dict[str, pa.Schema]
) -> tuple[list[dict[str, object]], float]:
    import fiona

    components = cast(list[int], inventory.get("components", []))
    component_sql = ",".join(str(value) for value in components)
    counts: list[dict[str, object]] = []
    maximum_error = 0.0
    for source in cast(list[dict[str, object]], inventory["sources"]):
        path, region, product = (
            Path(cast(str, source["path"])),
            cast(str, source["region"]),
            cast(str, source["product"]),
        )
        entity, level, layers = PRODUCTS[product]
        for layer in layers:
            current_entity = "river_nodes" if layer == "nodes" else entity
            ns = namespace(region, product, layer)
            physical = source_schema(path, layer)
            count = 0
            with fiona.open(path, layer=layer) as original:
                require(original.crs.to_epsg() == 8857, "unexpected original CRS")
                where = None
                if components and layer != "nodes":
                    key = "global_id" if product == "component_catchments" else "catchment_id"
                    where = f"{key} IN ({component_sql})"
                # Nodes without component columns are selected independently from original line endpoints.
                if components and layer == "nodes":
                    db.execute("DROP TABLE IF EXISTS selected_nodes")
                    db.execute("CREATE TEMP TABLE selected_nodes(id INTEGER PRIMARY KEY)")
                    with fiona.open(path, layer="lines") as lines:
                        for feature in lines.filter(where=f"catchment_id IN ({component_sql})"):
                            props = feature.properties
                            db.executemany(
                                "INSERT OR IGNORE INTO selected_nodes VALUES (?)",
                                [(props["upstream_node_id"],), (props["downstream_node_id"],)],
                            )
                    # Selection remains disk backed even when production subsets are large.
                for feature in original.filter(where=where):
                    native_id = feature.properties["global_id"]
                    if (
                        components
                        and layer == "nodes"
                        and db.execute("SELECT 1 FROM selected_nodes WHERE id=?", (native_id,)).fetchone() is None
                    ):
                        continue
                    found = db.execute(
                        "SELECT id,attrs,geometry,seen FROM features WHERE entity=? AND namespace=? AND source_id=?",
                        (current_entity, ns, str(native_id)),
                    ).fetchone()
                    require(found is not None and found[3] == 0, f"missing/duplicate source feature: {ns}/{native_id}")
                    identifier, attributes, geometry, _ = found
                    record = json.loads(attributes)
                    require(record["level"] == level, "source tier differs")
                    record["geometry"] = geometry
                    batch = pa.RecordBatch.from_pylist([record], schema=schemas[current_entity])
                    for field in schemas[current_entity]:
                        if (
                            field.name.startswith("source_")
                            and field.name not in {"source_id", "source_namespace"}
                            and field.name[7:] not in physical
                        ):
                            require(record[field.name] is None, f"invented absent source attribute: {field.name}")
                    maximum_error = max(maximum_error, compare_feature(feature, original.crs, physical, batch, 0))
                    verify_bounds_area(record, current_entity)
                    relationships(db, current_entity, product, region, record)
                    db.execute("UPDATE features SET seen=1 WHERE entity=? AND id=?", (current_entity, identifier))
                    count += 1
            counts.append({"namespace": ns, "count": count, "fields": physical})
            db.commit()
    require(
        db.execute("SELECT entity,id FROM features WHERE seen=0 LIMIT 1").fetchone() is None,
        "output contains non-source/extra rows",
    )
    equal_tables(db, "expected_edges", "reverse_edges", "entity,upstream,downstream")
    equal_tables(db, "incidence", "expected_incidence", "node,river,endpoint")
    mismatch = db.execute("""SELECT e.upstream,e.downstream FROM expected_edges e
        JOIN features a ON a.entity='rivers' AND a.id=e.upstream
        JOIN features b ON b.entity='rivers' AND b.id=e.downstream
        WHERE json_extract(a.attrs,'$.downstream_node_id') != json_extract(b.attrs,'$.upstream_node_id') LIMIT 1""").fetchone()
    require(mismatch is None, f"source edge endpoint continuity differs: {mismatch}")
    return counts, maximum_error


def verify_bounds_area(record: dict[str, object], entity: str) -> None:
    from pyproj import Geod

    geometry = from_wkb(record["geometry"])
    require(not geometry.is_empty, "empty source geometry")
    bounds = cast(dict[str, float], record["bbox"])
    xmin, ymin, xmax, ymax = geometry.bounds
    require(all(math.isfinite(value) for value in bounds.values()), "nonfinite bbox")
    require(
        bounds["xmin"] <= xmin <= xmax <= bounds["xmax"] and bounds["ymin"] <= ymin <= ymax <= bounds["ymax"],
        "bbox does not cover geometry",
    )
    if entity == "catchments":
        require(record["up_area_km2"] is None, "unsupported upstream area")
        # Signed exterior/interior areas are accumulated separately; ring orientation must not change local area.
        polygons = list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
        geod = Geod(ellps="WGS84")
        area = 0.0
        for polygon in polygons:
            x, y = polygon.exterior.xy
            area += abs(geod.polygon_area_perimeter(x, y)[0])
            for interior in polygon.interiors:
                x, y = interior.xy
                area -= abs(geod.polygon_area_perimeter(x, y)[0])
        expected = pa.scalar(area / 1e6, type=pa.float32()).as_py()
        require(record["area_km2"] == expected, "geodesic polygon area differs")


def verify_graph(db: sqlite3.Connection, entity: str, path: Path) -> None:
    import pyarrow.parquet as pq

    graph = pq.ParquetFile(path)
    check_schema(graph.schema_arrow, "graph")
    db.execute("DROP TABLE IF EXISTS graph_seen")
    db.execute("CREATE TEMP TABLE graph_seen(id INTEGER PRIMARY KEY)")
    for batch in graph.iter_batches(batch_size=4096):
        check_nonnull(batch, "graph")
        for record in batch.to_pylist():
            identifier = record["id"]
            target = db.execute(
                "SELECT level,attrs FROM features WHERE entity=? AND id=?", (entity, identifier)
            ).fetchone()
            require(target is not None and target[0] == record["level"], "graph feature/level differs")
            db.execute("INSERT INTO graph_seen VALUES (?)", (identifier,))
            bbox = json.loads(target[1])["bbox"]
            require(
                all(
                    record[name] == bbox[key]
                    for name, key in (
                        ("bbox_minx", "xmin"),
                        ("bbox_miny", "ymin"),
                        ("bbox_maxx", "xmax"),
                        ("bbox_maxy", "ymax"),
                    )
                ),
                "graph bounds differ",
            )
            for upstream in record["upstream_ids"]:
                require(type(upstream) is int and upstream != identifier, "invalid graph reference")
                source = db.execute("SELECT level FROM features WHERE entity=? AND id=?", (entity, upstream)).fetchone()
                require(source is not None and source[0] == target[0], "graph reference absent/wrong tier")
                db.execute("INSERT INTO edges VALUES (?,?,?)", (entity, upstream, identifier))
    count = db.execute("SELECT COUNT(*) FROM features WHERE entity=?", (entity,)).fetchone()[0]
    require(db.execute("SELECT COUNT(*) FROM graph_seen").fetchone()[0] == count, "graph coverage differs")
    if entity == "catchments":
        # Catchment graphs inherit only the verified same-tier local line connections.
        db.execute("""INSERT INTO expected_edges SELECT 'catchments',
            json_extract(a.attrs,'$.local_catchment_id'),json_extract(b.attrs,'$.local_catchment_id')
            FROM expected_edges e JOIN features a ON a.entity='rivers' AND a.id=e.upstream
            JOIN features b ON b.entity='rivers' AND b.id=e.downstream WHERE e.entity='rivers'""")
    mismatch = db.execute(
        "SELECT upstream,downstream FROM edges WHERE entity=? EXCEPT SELECT upstream,downstream FROM expected_edges WHERE entity=? LIMIT 1",
        (entity, entity),
    ).fetchone()
    require(mismatch is None, "delivered graph contains non-source edges")
    mismatch = db.execute(
        "SELECT upstream,downstream FROM expected_edges WHERE entity=? EXCEPT SELECT upstream,downstream FROM edges WHERE entity=? LIMIT 1",
        (entity, entity),
    ).fetchone()
    require(mismatch is None, "delivered graph omits source edges")
    verify_dag(db, entity)


def verify_declarations(manifest: dict[str, object]) -> None:
    require(manifest.get("topology") in {"tree", "dag"}, "catchment topology declaration invalid")
    require(
        manifest.get("catchment_batch_bytes") == 8388608 and manifest.get("index_batch_rows") == 65536,
        "catchment storage declaration invalid",
    )
    for entity in ("rivers", "river_nodes"):
        declaration = cast(dict[str, object], manifest[entity])
        require(
            declaration.get("batch_bytes") == 8388608 and declaration.get("index_batch_rows") == 65536,
            f"{entity} storage declaration invalid",
        )
        require(
            type(declaration.get("count")) is int and cast(int, declaration["count"]) > 0,
            f"{entity} count declaration invalid",
        )
        if entity == "rivers":
            require(declaration.get("topology") in {"tree", "dag"}, "river topology declaration invalid")
    require(
        type(manifest.get("unit_count")) is int and cast(int, manifest["unit_count"]) > 0,
        "catchment count declaration invalid",
    )


def verify_declared_connectivity(db: sqlite3.Connection, manifest: dict[str, object]) -> None:
    levels = {row[0] for row in db.execute("SELECT DISTINCT level FROM features WHERE entity='catchments'")}
    declarations = cast(list[dict[str, object]], manifest.get("catchment_connectivity", []))
    require(
        len(declarations) == len(levels) and {entry.get("level") for entry in declarations} == levels,
        "catchment connectivity declaration coverage differs",
    )
    for entry in declarations:
        require(
            type(entry["level"]) is int and entry.get("status") in {"supplied", "not_supplied"},
            "catchment connectivity declaration invalid",
        )
        if entry["status"] == "not_supplied":
            require(
                db.execute(
                    "SELECT 1 FROM edges e JOIN features f ON f.entity=e.entity AND f.id=e.downstream WHERE e.entity='catchments' AND f.level=? LIMIT 1",
                    (entry["level"],),
                ).fetchone()
                is None,
                "not_supplied level contains edges",
            )
    for entity, topology in (
        ("catchments", manifest["topology"]),
        ("rivers", cast(dict[str, object], manifest["rivers"])["topology"]),
    ):
        if topology == "tree":
            require(
                db.execute(
                    "SELECT upstream FROM edges WHERE entity=? GROUP BY upstream HAVING COUNT(*)>1 LIMIT 1", (entity,)
                ).fetchone()
                is None,
                "tree declaration has multiple downstream neighbors",
            )


def verify_external_rasters(manifest: dict[str, object], receipt_path: Path) -> dict[str, object]:
    """Compare declarations only; trust the separately supplied historical receipt."""
    from hfx.verify_candidates import _fingerprint

    identity = _fingerprint(receipt_path)
    receipt = json.loads(receipt_path.read_text())
    require(receipt["format_version"] == "0.4.0", "raster receipt format differs")
    expected_external = {}
    for kind in ("dir", "acc"):
        name = f"aux/d8/flow_{kind}.tif"
        artifact = receipt["artifacts"][name]
        expected_external[f"grit-flow-{kind}"] = {
            "url": receipt["bundle_url"] + name,
            **{key: artifact[key] for key in ("size_bytes", "sha256", "head_sha256", "tail_sha256")},
            "retention": "The GRIT HFX publisher retains this exact public object unchanged for the lifetime of this dependent bundle.",
        }
    expected_auxiliary = [
        {
            "schema": "hfx.aux.d8_raster.v2",
            "artifacts": {"flow_dir": {"external": "grit-flow-dir"}, "flow_acc": {"external": "grit-flow-acc"}},
            "metadata": {"crs": "EPSG:8857", "flow_dir_encoding": "grass", "flow_acc_units": "km2"},
        }
    ]
    require(
        manifest.get("external_artifacts") == expected_external and manifest.get("auxiliary") == expected_auxiliary,
        "raster declarations differ from supplied receipt/contract",
    )
    require(identity == _fingerprint(receipt_path), "raster receipt changed during verification")
    return {
        "status": "declarations match supplied receipt",
        "receipt": {"path": str(receipt_path.resolve()), **identity},
        "limitation": "No fresh full raster scan or public accessibility check.",
    }


def verify(
    inventory_path: Path,
    output: Path,
    report: Path,
    scratch: Path,
    *,
    worked_example: bool = False,
    external_raster_receipt: Path | None = None,
) -> dict[str, object]:
    """Check local delivery against separately supplied originals; never overwrite a receipt."""
    from hfx.verify_candidates import _fingerprint

    output, report = output.resolve(), report.resolve()
    inventory_identity = _fingerprint(inventory_path)
    inventory = cast(dict[str, object], json.loads(inventory_path.read_text()))
    require(not report.exists() and not report.is_relative_to(output), "receipt must be new and outside output")
    sources = cast(list[dict[str, object]], inventory["sources"])
    require(bool(sources), "no independent originals supplied")
    source_paths = [Path(cast(str, source["path"])).resolve() for source in sources]
    require(
        all(not path.is_relative_to(output) and report != path for path in source_paths),
        "source/output/receipt overlap",
    )
    before = {str(path): _fingerprint(path) for path in source_paths}
    polygon_sample = verify_sample_polygons(inventory) if worked_example else None
    manifest_path = output / "manifest.json"
    manifest_identity = _fingerprint(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    require(manifest["format_version"] == "0.4.0" and manifest["crs"] == "EPSG:4326", "wrong format/CRS")
    verify_declarations(manifest)
    require(manifest["has_up_area"] is False, "GRIT upstream area not supplied")
    external_rasters: str | dict[str, object] = "not verified in local mode"
    if external_raster_receipt is None:
        require(
            not manifest.get("external_artifacts") and not manifest.get("auxiliary"),
            "local verification mode does not certify external rasters",
        )
    else:
        external_rasters = verify_external_rasters(manifest, external_raster_receipt)
    paths = list(output.rglob("*"))
    require(not any(path.is_symlink() for path in paths), "symlinked output")
    actual = {
        path.relative_to(output).as_posix(): _fingerprint(path)
        for path in paths
        if path.is_file() and path != manifest_path
    }
    require(actual == manifest["artifacts"], "artifact coverage/fingerprints differ")
    declarations = {
        "catchments": {
            "data": manifest["catchments"],
            "lookup": manifest["lookup"],
            "directory": manifest["directory"],
            "graph": manifest["graph"],
            "count": manifest["unit_count"],
        },
        "rivers": manifest["rivers"],
        "river_nodes": manifest["river_nodes"],
    }

    def local(name: str) -> Path:
        path = output / name
        require(
            not Path(name).is_absolute() and ".." not in Path(name).parts and name in actual, "unsafe/unbound artifact"
        )
        return path

    with prepare_database(scratch) as db:
        schemas: dict[str, pa.Schema] = {}
        for entity, declaration in declarations.items():
            schemas[entity] = stage_output(db, entity, local(declaration["data"]))
            count = db.execute("SELECT COUNT(*) FROM features WHERE entity=?", (entity,)).fetchone()[0]
            require(count == declaration["count"] and count > 0, "manifest count differs")
            verify_lookup(
                db,
                entity,
                local(declaration["lookup"]),
                local(declaration["directory"]),
                actual[declaration["data"]]["sha256"],
                count,
            )
        counts, error = verify_originals(db, inventory, schemas)
        verify_ledger(inventory, json.loads(local("source-provenance.json").read_text()), counts)
        for entity, schema in schemas.items():
            verify_grouping(db, entity, schema)
        verify_graph(db, "rivers", local(declarations["rivers"]["graph"]))
        verify_graph(db, "catchments", local(declarations["catchments"]["graph"]))
        verify_declared_connectivity(db, manifest)
        verify_categories(db, manifest, schemas, declarations)
    require(before == {str(path): _fingerprint(path) for path in source_paths}, "originals changed during verification")
    require(manifest_identity == _fingerprint(manifest_path), "manifest changed during verification")
    final_paths = list(output.rglob("*"))
    require(not any(path.is_symlink() for path in final_paths), "output changed during verification")
    require(
        actual
        == {
            path.relative_to(output).as_posix(): _fingerprint(path)
            for path in final_paths
            if path.is_file() and path != manifest_path
        },
        "output changed during verification",
    )
    require(inventory_identity == _fingerprint(inventory_path), "inventory changed during verification")
    if external_raster_receipt is not None:
        require(
            external_rasters == verify_external_rasters(manifest, external_raster_receipt),
            "raster receipt changed during verification",
        )
    import fiona
    import pyproj
    import rasterio

    receipt: dict[str, object] = {
        "status": "passed",
        "methods": {
            "original_read": f"Fiona {fiona.__version__}, GDAL {fiona.__gdal_version__}",
            "transform": f"rasterio {rasterio.__version__}, GDAL {rasterio.__gdal_version__}, PROJ {rasterio.__proj_version__}",
            "area": f"pyproj {pyproj.__version__}, PROJ {pyproj.proj_version_str}; derived consistency, not independent geodesic algorithm",
            "independence": "GDAL original decode and coordinate transform separate from producer calls; common PROJ mathematics and Shapely output WKB decode",
        },
        "inventory": inventory_identity,
        "originals": before,
        "manifest": manifest_identity,
        "artifacts": actual,
        "layers": counts,
        "geometry_tolerance_degrees": COORDINATE_TOLERANCE_DEGREES,
        "maximum_coordinate_error_degrees": error,
        "external_rasters": external_rasters,
        "sample_polygon_checks": polygon_sample,
        "checks": [
            "all source rows and native physical types/nulls",
            "required structural Arrow schemas and actual nonnull values including nested children",
            "manifest storage/count/topology declarations, connectivity levels and tree downstream degree",
            "inventory/original/manifest/artifact identity unchanged and final output file-set coverage",
            "source schema ledger",
            "parent and association mappings",
            "reciprocal edges and node incidence",
            "DAG",
            "all lookup addresses and fingerprints",
            "source order and 256-row incoming groups; maximal 8388608-byte source slices and oversized singletons",
            "GDAL coordinate sequence",
            "derived geodesic area consistency",
        ],
    }
    with report.open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    return receipt


def verify_categories(
    db: sqlite3.Connection,
    manifest: dict[str, object],
    schemas: dict[str, pa.Schema],
    declarations: dict[str, dict[str, object]],
) -> None:
    bound: set[tuple[str, str]] = set()
    for category in cast(list[dict[str, object]], manifest.get("categorical_columns", [])):
        artifact, column = cast(str, category["artifact"]), cast(str, category["column"])
        matches = [entity for entity, decl in declarations.items() if decl["data"] == artifact]
        require(len(matches) == 1 and (artifact, column) not in bound, "invalid/duplicate categorical binding")
        bound.add((artifact, column))
        entity = matches[0]
        kind = schemas[entity].field(column).type
        require(
            str(kind) == category["physical_type"]
            and (pa.types.is_integer(kind) or pa.types.is_string(kind) or pa.types.is_boolean(kind)),
            "categorical physical type differs",
        )
        require(isinstance(category["null_meaning"], str) and bool(category["null_meaning"]), "missing null meaning")
        codes: list[object] = []
        for entry in cast(list[dict[str, object]], category["codes"]):
            code = entry["code"]
            require(
                code is not None and code not in codes and isinstance(entry["meaning"], str) and bool(entry["meaning"]),
                "invalid category meaning/code",
            )
            require(
                (pa.types.is_integer(kind) and type(code) is int)
                or (pa.types.is_boolean(kind) and type(code) is bool)
                or (pa.types.is_string(kind) and type(code) is str),
                "categorical code type differs",
            )
            pa.scalar(code, type=kind)
            codes.append(code)
        for (attrs,) in db.execute("SELECT attrs FROM features WHERE entity=?", (entity,)):
            value = json.loads(attrs)[column]
            require(value is None or value in codes, "undeclared source categorical value")


def verify_ledger(inventory: dict[str, object], ledger: dict[str, object], observed: list[dict[str, object]]) -> None:
    require(ledger["inventory"] == inventory, "provenance inventory differs")
    expected = []
    for layer in observed:
        ns = cast(str, layer["namespace"])
        _, _, region, product, table = ns.split(":")
        sources = [
            source
            for source in cast(list[dict[str, object]], inventory["sources"])
            if source["region"] == region and source["product"] == product
        ]
        require(len(sources) == 1, "duplicate/missing original layer source")
        path = Path(cast(str, sources[0]["path"]))
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
            columns = connection.execute('SELECT name,type,"notnull" FROM pragma_table_info(?)', (table,))
            fields = [
                {"name": name, "type": kind, "nullable": not bool(nonnull), "output": "source_" + name}
                for name, kind, nonnull in columns
                if name in cast(dict[str, str], layer["fields"])
            ]
        expected.append(
            {
                "namespace": ns,
                "product": product,
                "region": region,
                "table": table,
                "count": layer["count"],
                "fields": fields,
            }
        )

    def key(item: dict[str, object]) -> str:
        return cast(str, item["namespace"])

    require(
        sorted(cast(list[dict[str, object]], ledger["layers"]), key=key) == sorted(expected, key=key),
        "source schema ledger differs",
    )


def verify_sample_polygons(inventory: dict[str, object]) -> dict[str, object]:
    """Native-plane containment/disjointness for the four original BORN groups only."""
    import fiona
    from shapely.geometry import shape
    from shapely.geometry.base import BaseGeometry

    selected = {70010735, 70010734, 70000197, 70008597}
    polygons: dict[str, dict[int, BaseGeometry]] = {}
    parent_ids: dict[int, int] = {}
    for source in cast(list[dict[str, object]], inventory["sources"]):
        product = cast(str, source["product"])
        if product not in {"component_catchments", "segment_catchments", "reach_catchments"}:
            continue
        if source["region"] not in {"SP", "GLOBAL"}:
            continue
        query = (
            "global_id=70000129"
            if product == "component_catchments"
            else ("global_id" if product == "segment_catchments" else "segment_id")
            + " IN (70010735,70010734,70000197,70008597)"
        )
        polygons[product] = {}
        with fiona.open(source["path"], layer=product + "__1") as original:
            require(original.crs.to_epsg() == 8857, "sample geometry CRS differs")
            for feature in original.filter(where=query):
                identifier = feature.properties["global_id"]
                geometry = shape(feature.geometry)
                require(geometry.is_valid, "invalid original sample polygon")
                polygons[product][identifier] = geometry
                if product == "reach_catchments":
                    parent_ids[identifier] = feature.properties["segment_id"]
    require(
        set(polygons["segment_catchments"]) == selected
        and len(parent_ids) == 21
        and set(polygons["component_catchments"]) == {70000129},
        "original worked polygon sample missing",
    )
    # Original equal-area metre coordinates share boundaries exactly. No numerical
    # allowance is needed in this native-plane sample; no transformed overlay claim.
    for identifier, parent in parent_ids.items():
        child = polygons["reach_catchments"][identifier]
        require(child.difference(polygons["segment_catchments"][parent]).area == 0, "sample child outside parent")
    for child in polygons["segment_catchments"].values():
        require(
            child.difference(polygons["component_catchments"][70000129]).area == 0, "sample segment outside component"
        )
    for product in ("segment_catchments", "reach_catchments"):
        values = list(polygons[product].values())
        for index, first in enumerate(values):
            for second in values[index + 1 :]:
                require(first.intersection(second).area == 0, "sample sibling interiors overlap")
    return {
        "coverage": "four BORN segment polygons, 21 reach polygons, component 70000129; not worldwide topology certification",
        "crs": "EPSG:8857",
        "method": "native GEOS difference/intersection area; independently GDAL-exported originals",
        "tolerance_square_metres": 0,
        "outside_parent_square_metres": 0,
        "sibling_overlap_square_metres": 0,
    }


def verify_group_batches(incoming: pa.RecordBatch, sizes: list[int], budget: int = 8388608) -> None:
    offset = 0
    for size in sizes:
        require(0 < size <= incoming.num_rows - offset, "batch crosses incoming group boundary")
        require(incoming.slice(offset, size).nbytes <= budget or size == 1, "batch exceeds source byte budget")
        require(
            offset + size == incoming.num_rows or incoming.slice(offset, size + 1).nbytes > budget,
            "batch not maximal source slice",
        )
        offset += size
    require(offset == incoming.num_rows, "incoming group coverage differs")


def verify_grouping(db: sqlite3.Connection, entity: str, schema: pa.Schema) -> None:
    # Rebuild the documented from_pylist representation after original fidelity
    # checks; do not use decoded IPC nbytes (validity buffers may differ).
    db.executescript(
        "DROP TABLE IF EXISTS source_order; CREATE TEMP TABLE source_order(id INTEGER PRIMARY KEY, product INTEGER, region TEXT, layer TEXT, fid INTEGER);"
    )
    order = tuple(PRODUCTS)
    for identifier, ns, attrs in db.execute("SELECT id,namespace,attrs FROM features WHERE entity=?", (entity,)):
        _, _, region, product, layer = ns.split(":")
        db.execute(
            "INSERT INTO source_order VALUES (?,?,?,?,?)",
            (identifier, order.index(product), region, layer, json.loads(attrs)["source_fid"]),
        )
    db.execute("CREATE INDEX source_order_keys ON source_order(product,region,layer,fid)")
    # Keep the ordered keys as the outer loop so SQLite does not sort attrs/WKB.
    incoming = db.execute(
        """SELECT f.attrs,f.geometry,a.block,a.row FROM source_order o
        CROSS JOIN features f ON f.entity=? AND f.id=o.id
        CROSS JOIN addresses a ON a.entity=f.entity AND a.id=f.id
        ORDER BY o.product,o.region,o.layer,o.fid""",
        (entity,),
    )
    previous_block = -1
    while group := incoming.fetchmany(256):
        rows: list[dict[str, object]] = []
        sizes: list[int] = []
        for attrs, geometry, block, row in group:
            record = json.loads(attrs)
            record["geometry"] = geometry
            rows.append(record)
            if not sizes or block != previous_block:
                require(block == previous_block + 1 and row == 0, "source order/group boundary differs")
                sizes.append(0)
                previous_block = block
            require(row == sizes[-1], "source fid/address order differs")
            sizes[-1] += 1
        verify_group_batches(pa.RecordBatch.from_pylist(rows, schema=schema), sizes)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("scratch", type=Path)
    parser.add_argument(
        "--worked-example", action="store_true", help="also reproduce original four-group BORN polygon checks"
    )
    parser.add_argument(
        "--external-raster-receipt",
        type=Path,
        help="compare unchanged external raster declarations with this historical receipt; no public raster check",
    )
    args = parser.parse_args()
    verify(
        args.inventory,
        args.output,
        args.report,
        args.scratch,
        worked_example=args.worked_example,
        external_raster_receipt=args.external_raster_receipt,
    )


if __name__ == "__main__":
    main()
