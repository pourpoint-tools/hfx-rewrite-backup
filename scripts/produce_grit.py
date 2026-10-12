"""Produce GRIT v1.0 vectors from original GeoPackages, without changing source hydrology."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import struct
import time
import zipfile
from collections.abc import Iterator
from contextlib import ExitStack, closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Geod, Transformer
from shapely import from_wkb, to_wkb, transform
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from hfx.candidates import Fingerprint, fingerprint, write_json
from hfx.vector_storage import write_vectors


class Code(TypedDict):
    code: str | int
    meaning: str


class Category(TypedDict):
    artifact: str
    column: str
    physical_type: str
    codes: list[Code]
    null_meaning: str


def native_categories(artifact: str, schema: pa.Schema) -> list[Category]:
    """Describe retained source values, never classify nodes from their incidence."""
    definitions: dict[str, tuple[pa.DataType, list[Code]]] = {
        "source_node_type": (
            pa.string(),
            [
                {"code": "bifurcation", "meaning": "Source bifurcation label; not inferred from delivered incidence."},
                {"code": "confluence", "meaning": "Source confluence label; not inferred from delivered incidence."},
                {"code": "inlet", "meaning": "Source inlet label."},
                {"code": "coastal_outlet", "meaning": "Source coastal outlet label."},
                {"code": "sink_outlet", "meaning": "Source sink outlet label."},
                {"code": "grwl_change", "meaning": "Source GRWL code-change node label."},
                {
                    "code": "outlet",
                    "meaning": "Observed source outlet label, undocumented in GRIT README; specific termination meaning unknown.",
                },
            ],
        ),
        "source_continuity_violated": (
            pa.int64(),
            [
                {"code": 0, "meaning": "Source reports flow continuity not violated."},
                {"code": 1, "meaning": "Source reports flow continuity violated."},
            ],
        ),
        "source_is_mainstem": (
            pa.int64(),
            [
                {"code": 0, "meaning": "Source segment is not the widest segment of bifurcated flow."},
                {
                    "code": 1,
                    "meaning": "Source segment is the widest segment of bifurcated flow or has no upstream bifurcation.",
                },
            ],
        ),
    }
    categories: list[Category] = []
    for column, (expected_type, codes) in definitions.items():
        if column not in schema.names:
            continue
        field = schema.field(column)
        if field.type != expected_type:
            raise ValueError(f"unexpected retained native type for {column}: {field.type}")
        categories.append(
            {
                "artifact": artifact,
                "column": column,
                "physical_type": str(field.type),
                "codes": codes,
                "null_meaning": (
                    "Native source null or field absent from this source layer; source-provenance.json distinguishes these cases."
                    if field.nullable
                    else "not permitted"
                ),
            }
        )
    return categories


def external_rasters(*, production: bool) -> dict[str, object]:
    """Declare existing raster objects without reading or copying any raster bytes.

    Opting in carries the publisher retention commitment from the raster contract.
    Component samples must pass production=False.
    """
    if not production:
        return {"auxiliary": []}
    receipt_path = Path(__file__).resolve().parents[1] / "docs/v0.4.0/receipts/grit-raster-delivery.json"
    receipt = cast(dict[str, object], json.loads(receipt_path.read_text()))
    artifacts = cast(dict[str, dict[str, object]], receipt["artifacts"])
    external: dict[str, dict[str, object]] = {}
    for kind in ("dir", "acc"):
        path = f"aux/d8/flow_{kind}.tif"
        identity = artifacts[path]
        external[f"grit-flow-{kind}"] = {
            "url": str(receipt["bundle_url"]) + path,
            **{key: identity[key] for key in ("size_bytes", "sha256", "head_sha256", "tail_sha256")},
            "retention": "The GRIT HFX publisher retains this exact public object unchanged for the lifetime of this dependent bundle.",
        }
    return {
        "auxiliary": [
            {
                "schema": "hfx.aux.d8_raster.v2",
                "artifacts": {
                    "flow_dir": {"external": "grit-flow-dir"},
                    "flow_acc": {"external": "grit-flow-acc"},
                },
                "metadata": {"crs": "EPSG:8857", "flow_dir_encoding": "grass", "flow_acc_units": "km2"},
            }
        ],
        "external_artifacts": external,
    }


PROJECTION = Transformer.from_crs(8857, 4326, always_xy=True)
GEOD = Geod(ellps="WGS84")


class Identities:
    """Disk-backed source identities, with separate HFX feature ID domains."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        connection.execute("PRAGMA cache_size = -8192")
        connection.execute("PRAGMA temp_store = FILE")
        connection.execute(
            "CREATE TABLE identities (family TEXT, namespace TEXT, source_id INTEGER, id INTEGER, "
            "PRIMARY KEY(namespace, source_id), UNIQUE(family, id))"
        )
        self.counts: dict[str, int] = {}
        self.node_connections: dict[str, sqlite3.Connection] = {}

    def add(self, family: str, namespace: str, source_id: int) -> int:
        identity = self.counts.get(family, 0) + 1
        try:
            self.connection.execute("INSERT INTO identities VALUES (?,?,?,?)", (family, namespace, source_id, identity))
        except sqlite3.IntegrityError as error:
            raise ValueError(f"duplicate source identity: {namespace}/{source_id}") from error
        self.counts[family] = identity
        return identity

    def get(self, namespace: str, source_id: int) -> int:
        row = self.connection.execute(
            "SELECT id FROM identities WHERE namespace=? AND source_id=?", (namespace, source_id)
        ).fetchone()
        if row is None:
            raise ValueError(f"unresolved source reference: {namespace}/{source_id}")
        return int(row[0])


def export_geometry(blob: bytes) -> bytes:
    """Remove the GeoPackage transport header and reproject without changing order."""
    if len(blob) < 8 or blob[:3] != b"GP\x00":
        raise ValueError("invalid GeoPackage geometry header")
    flags = blob[3]
    envelope = (flags >> 1) & 7
    if flags & 0xF0 or envelope > 4:
        raise ValueError("unsupported empty/extended GeoPackage geometry")
    crs = struct.unpack("<i" if flags & 1 else ">i", blob[4:8])[0]
    if crs != 8857:
        raise ValueError("expected source EPSG:8857")
    offset = 8 + (0, 32, 48, 48, 64)[envelope]
    geometry = from_wkb(blob[offset:])
    if geometry.is_empty or geometry.has_z or geometry.has_m:
        raise ValueError("expected nonempty 2D source geometry")
    projected = transform(geometry, PROJECTION.transform, interleaved=False)
    if not np.isfinite(projected.bounds).all():
        raise ValueError("nonfinite projected geometry")
    return to_wkb(projected, byte_order=1)


def outward_bounds(geometry: BaseGeometry) -> tuple[float, float, float, float]:
    exact = geometry.bounds
    rounded = []
    for i, value in enumerate(exact):
        candidate = np.float32(value)
        if (i < 2 and float(candidate) > value) or (i >= 2 and float(candidate) < value):
            candidate = np.nextafter(candidate, np.float32(-np.inf if i < 2 else np.inf))
        rounded.append(float(candidate))
    return rounded[0], rounded[1], rounded[2], rounded[3]


def geodesic_area(geometry: BaseGeometry) -> float:
    """Sum WGS84 shell-minus-hole areas without orientation cancellation."""
    if isinstance(geometry, MultiPolygon):
        return sum(geodesic_area(part) for part in geometry.geoms)
    if not isinstance(geometry, Polygon):
        raise ValueError("expected Polygon or MultiPolygon")
    outer = abs(GEOD.polygon_area_perimeter(*geometry.exterior.xy)[0])
    holes = sum(abs(GEOD.polygon_area_perimeter(*ring.xy)[0]) for ring in geometry.interiors)
    return (outer - holes) / 1_000_000


Scalar = int | float | str | bytes | None
PRODUCTS = ("component_catchments", "segment_catchments", "reach_catchments", "segments", "reaches")
BBOX = pa.struct([pa.field(name, pa.float32(), nullable=False) for name in ("xmin", "ymin", "xmax", "ymax")])
TYPES = {"INTEGER": pa.int64(), "REAL": pa.float64(), "TEXT": pa.string()}


@dataclass(frozen=True)
class Layer:
    path: Path
    region: str
    product: str
    table: str
    fields: tuple[tuple[str, str, bool], ...]

    @property
    def namespace(self) -> str:
        return f"grit:1.0:{self.region}:{self.product}:{self.table}"

    @property
    def family(self) -> str:
        return "catchments" if "catchments" in self.product else "nodes" if self.table == "nodes" else "rivers"

    @property
    def level(self) -> int:
        return PRODUCTS.index(self.product) if self.family == "catchments" else int(self.product == "reaches")

    def rows(self) -> Iterator[dict[str, Scalar]]:
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(f'SELECT * FROM "{self.table}" ORDER BY fid')
            for row in cursor:
                yield dict(row)


def namespace(region: str, product: str, table: str | None = None) -> str:
    return f"grit:1.0:{region}:{product}:{table or product + '__1'}"


def native_integer(value: Scalar) -> int:
    if not isinstance(value, (int, float)) or not np.isfinite(value) or int(value) != value:
        raise ValueError(f"nonintegral source reference: {value}")
    return int(value)


def adjacent(value: Scalar) -> list[int]:
    if value is None or value == "":
        return []
    if not isinstance(value, str):
        raise ValueError("expected native comma-separated adjacency")
    result = [int(part) for part in value.split(",")]
    if len(set(result)) != len(result):
        raise ValueError("duplicate source edge")
    return result


def read_layers(inventory: dict[str, object]) -> list[Layer]:
    layers = []
    for source in cast(list[dict[str, object]], inventory["sources"]):
        path = Path(str(source["path"]))
        product, region = str(source["product"]), str(source["region"])
        if product not in PRODUCTS:
            raise ValueError(f"unsupported GRIT product {product}")
        tables = ("lines", "nodes") if product in ("segments", "reaches") else (product + "__1",)
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            for table in tables:
                metadata = connection.execute(
                    "SELECT column_name,srs_id,z,m FROM gpkg_geometry_columns WHERE table_name=?", (table,)
                ).fetchone()
                if metadata != ("geom", 8857, 0, 0):
                    raise ValueError(f"unexpected source geometry metadata: {path}/{table}")
                fields = tuple(
                    (str(r[1]), str(r[2]), not bool(r[3]))
                    for r in connection.execute(f'PRAGMA table_info("{table}")')
                    if r[1] != "geom"
                )
                if any(kind not in TYPES for _, kind, _ in fields):
                    raise ValueError("unsupported native field type")
                layers.append(Layer(path, region, product, table, fields))
    return sorted(layers, key=lambda layer: (PRODUCTS.index(layer.product), layer.region, layer.table))


def select_rows(layers: list[Layer], identities: Identities, components: set[int] | None) -> None:
    db = identities.connection
    db.execute("CREATE TABLE selected_rows (namespace TEXT,fid INTEGER,id INTEGER,PRIMARY KEY(namespace,fid))")
    db.execute("CREATE INDEX selected_identity ON selected_rows(namespace,id)")
    db.execute("CREATE TABLE needed_nodes (namespace TEXT,source_id INTEGER,PRIMARY KEY(namespace,source_id))")
    # Lines establish endpoint closure before node selection. Native GPKGs are never copied.
    ordered = [layer for layer in layers if layer.table != "nodes"] + [
        layer for layer in layers if layer.table == "nodes"
    ]
    for layer in ordered:
        for row in layer.rows():
            source_id = native_integer(row["global_id"])
            if components is not None:
                if layer.table == "nodes":
                    if (
                        db.execute(
                            "SELECT 1 FROM needed_nodes WHERE namespace=? AND source_id=?", (layer.namespace, source_id)
                        ).fetchone()
                        is None
                    ):
                        continue
                elif (
                    native_integer(row["global_id"] if layer.product == "component_catchments" else row["catchment_id"])
                    not in components
                ):
                    continue
            identity = identities.add(layer.family, layer.namespace, source_id)
            db.execute("INSERT INTO selected_rows VALUES (?,?,?)", (layer.namespace, row["fid"], identity))
            if layer.table == "lines":
                db.executemany(
                    "INSERT OR IGNORE INTO needed_nodes VALUES (?,?)",
                    (
                        (namespace(layer.region, layer.product, "nodes"), native_integer(row[key]))
                        for key in ("upstream_node_id", "downstream_node_id")
                    ),
                )
        db.commit()


def selected(layer: Layer, db: sqlite3.Connection) -> Iterator[tuple[int, dict[str, Scalar]]]:
    with sqlite3.connect(f"file:{layer.path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for fid, identity in db.execute(
            "SELECT fid,id FROM selected_rows WHERE namespace=? ORDER BY fid", (layer.namespace,)
        ):
            row = connection.execute(f'SELECT * FROM "{layer.table}" WHERE fid=?', (fid,)).fetchone()
            yield identity, dict(row)


def schema(family: str, layers: list[Layer]) -> pa.Schema:
    fields = [
        pa.field("id", pa.int64(), False),
        pa.field("level", pa.int16(), False),
        pa.field("source_namespace", pa.string(), False),
        pa.field("source_id", pa.string(), False),
    ]
    if family == "nodes":
        fields.append(pa.field("coarser_node_id", pa.int64()))
    else:
        fields.append(pa.field("parent_id", pa.int64()))
    if family == "rivers":
        fields.extend(
            pa.field(name, pa.int64())
            for name in ("local_catchment_id", "component_catchment_id", "upstream_node_id", "downstream_node_id")
        )
        fields.append(pa.field("geometry_orientation", pa.int8(), False))
    if family == "catchments":
        fields.extend(
            [
                pa.field("area_km2", pa.float32(), False),
                pa.field("up_area_km2", pa.float32()),
                pa.field("outlet_lon", pa.float64()),
                pa.field("outlet_lat", pa.float64()),
            ]
        )
    fields.extend([pa.field("bbox", BBOX, False), pa.field("geometry", pa.binary(), False)])
    native: dict[str, pa.DataType] = {}
    for layer in layers:
        for name, kind, _ in layer.fields:
            if name in native and native[name] != TYPES[kind]:
                raise ValueError(f"conflicting native field types: {name}")
            native[name] = TYPES[kind]
    fields.extend(pa.field("source_" + name, kind) for name, kind in native.items())
    return pa.schema(fields)


def mapped_row(layer: Layer, identity: int, row: dict[str, Scalar], identities: Identities) -> dict[str, object]:
    source_id = native_integer(row["global_id"])
    geometry = export_geometry(cast(bytes, row["geom"]))
    shape = from_wkb(geometry)
    allowed = {
        "nodes": {"Point"},
        "rivers": {"LineString", "MultiLineString"},
        "catchments": {"Polygon", "MultiPolygon"},
    }
    if shape.geom_type not in allowed[layer.family]:
        raise ValueError(f"unexpected {layer.family} geometry: {shape.geom_type}")
    result: dict[str, object] = {
        "id": identity,
        "level": layer.level,
        "source_namespace": layer.namespace,
        "source_id": str(source_id),
        "geometry": geometry,
        "bbox": dict(zip(("xmin", "ymin", "xmax", "ymax"), outward_bounds(shape), strict=True)),
    }
    result.update({"source_" + name: row[name] for name, _, _ in layer.fields})

    def reference(product: str, value: Scalar, table: str | None = None, region: str | None = None) -> int:
        return identities.get(namespace(region or layer.region, product, table), native_integer(value))

    if layer.family == "nodes":
        coarser = row.get("segment_node_id") if layer.product == "reaches" else None
        result["coarser_node_id"] = None if coarser is None else reference("segments", coarser, "nodes")
    elif layer.family == "rivers":
        result.update(
            parent_id=None if layer.level == 0 else reference("segments", row["segment_id"], "lines"),
            local_catchment_id=reference("segment_catchments" if layer.level == 0 else "reach_catchments", source_id),
            component_catchment_id=reference("component_catchments", row["catchment_id"], region="GLOBAL"),
            upstream_node_id=reference(layer.product, row["upstream_node_id"], "nodes"),
            downstream_node_id=reference(layer.product, row["downstream_node_id"], "nodes"),
            geometry_orientation=0,
        )
    else:
        result.update(parent_id=None, area_km2=geodesic_area(shape), up_area_km2=None, outlet_lon=None, outlet_lat=None)
        if layer.level:
            result["parent_id"] = (
                reference("component_catchments", row["catchment_id"], region="GLOBAL")
                if layer.level == 1
                else reference("segment_catchments", row["segment_id"])
            )
            river_space = namespace(layer.region, "segments" if layer.level == 1 else "reaches", "lines")
            river = identities.get(river_space, source_id)
            node = identities.connection.execute("SELECT downstream FROM endpoints WHERE river=?", (river,)).fetchone()[
                0
            ]
            node_space, fid = identities.connection.execute(
                "SELECT s.namespace,s.fid FROM selected_rows s JOIN identities i ON i.namespace=s.namespace AND i.id=s.id WHERE i.family='nodes' AND i.id=?",
                (node,),
            ).fetchone()
            blob = (
                identities.node_connections[node_space]
                .execute("SELECT geom FROM nodes WHERE fid=?", (fid,))
                .fetchone()[0]
            )
            point = from_wkb(export_geometry(blob))
            result.update(outlet_lon=point.x, outlet_lat=point.y)
    return result


def vector_batches(layers: list[Layer], identities: Identities, output_schema: pa.Schema) -> Iterator[pa.RecordBatch]:
    rows: list[dict[str, object]] = []
    for layer in layers:
        for identity, row in selected(layer, identities.connection):
            rows.append(mapped_row(layer, identity, row, identities))
            if len(rows) == 256:
                yield pa.RecordBatch.from_pylist(rows, schema=output_schema)
                rows = []
    if rows:
        yield pa.RecordBatch.from_pylist(rows, schema=output_schema)


def verify_global_inventory(inventory: dict[str, object]) -> None:
    """Bind a declared global delivery to all original release products."""
    pinned = json.loads(
        (Path(__file__).resolve().parents[1] / "docs/v0.4.0/receipts/grit-original-inventory.json").read_text()
    )
    expected = {(item["region"], item["product"]): item for item in pinned["archives"]}
    sources = cast(list[dict[str, object]], inventory["sources"])
    keys = [(source["region"], source["product"]) for source in sources]
    if len(keys) != 29 or set(keys) != set(expected) or "components" in inventory or inventory.get("synthetic_fixture"):
        raise ValueError("global delivery requires all 29 original products, without a sample filter")
    for source in sources:
        entry = expected[(source["region"], source["product"])]
        archive = cast(dict[str, object], source["archive"])
        if archive["md5"] != entry["md5"] or Path(str(source["path"])).name != entry["member"]:
            raise ValueError("global source differs from pinned release inventory")
    documents = cast(list[dict[str, object]], inventory.get("documents", []))
    if {str(item["name"]): item["md5"] for item in documents} != {
        item["name"]: item["md5"] for item in pinned["documents"]
    }:
        raise ValueError("global delivery requires original README and license")


def produce(inventory_path: Path, output: Path) -> None:
    started = time.perf_counter()
    inventory = cast(dict[str, object], json.loads(inventory_path.read_text()))
    if inventory.get("external_rasters") is True:
        verify_global_inventory(inventory)
    verify_archives(inventory)
    scratch = output.with_name(output.name + "-production.sqlite")
    if output.exists() or scratch.exists():
        raise FileExistsError(output if output.exists() else scratch)
    output.mkdir(parents=True)
    layers = read_layers(inventory)
    before = {path: fingerprint(path) for path in sorted({layer.path for layer in layers})}
    components = set(cast(list[int], inventory["components"])) if "components" in inventory else None
    with ExitStack() as stack, sqlite3.connect(scratch) as connection:
        identities = Identities(connection)
        select_rows(layers, identities, components)
        source_graph(layers, identities)
        identities.node_connections = {
            layer.namespace: stack.enter_context(closing(sqlite3.connect(f"file:{layer.path}?mode=ro", uri=True)))
            for layer in layers
            if layer.table == "nodes"
        }
        for family, data, lookup, directory in (
            ("catchments", "catchments.arrow", "lookup.arrow", "lookup-directory.json"),
            ("rivers", "rivers.arrow", "river-lookup.arrow", "river-lookup-directory.json"),
            ("nodes", "river-nodes.arrow", "river-node-lookup.arrow", "river-node-lookup-directory.json"),
        ):
            family_layers = [layer for layer in layers if layer.family == family]
            output_schema = schema(family, family_layers)
            value = write_vectors(
                output_schema,
                vector_batches(family_layers, identities, output_schema),
                output / data,
                output / lookup,
                lookup_binding="hfx:catchments_sha256" if family == "catchments" else "hfx:data_sha256",
            )
            write_json(output / directory, value)
        write_graph(layers, identities, "catchments", output / "graph.parquet")
        write_graph(layers, identities, "rivers", output / "river-graph.parquet")
        after = {path: fingerprint(path) for path in before}
        if before != after:
            raise ValueError("original GeoPackage changed during production")
        finish_manifest(inventory, layers, identities, output, time.perf_counter() - started, after)


def check_dag(connection: sqlite3.Connection, family: str) -> None:
    """Kahn traversal on disk, retaining the original edges for diagnostics."""
    connection.execute("DROP TABLE IF EXISTS indegree")
    connection.execute("CREATE TABLE indegree (id INTEGER PRIMARY KEY, degree INTEGER)")
    connection.execute(
        "INSERT INTO indegree SELECT upstream,0 FROM edges WHERE family=? UNION SELECT downstream,0 FROM edges WHERE family=?",
        (family, family),
    )
    connection.execute(
        "UPDATE indegree SET degree=(SELECT COUNT(*) FROM edges WHERE family=? AND downstream=id)", (family,)
    )
    connection.execute("CREATE INDEX IF NOT EXISTS ready ON indegree(degree)")
    while row := connection.execute("SELECT id FROM indegree WHERE degree=0 LIMIT 1").fetchone():
        identity = row[0]
        connection.execute("DELETE FROM indegree WHERE id=?", (identity,))
        connection.execute(
            "UPDATE indegree SET degree=degree-1 WHERE id IN (SELECT downstream FROM edges WHERE family=? AND upstream=?)",
            (family, identity),
        )
    remaining = connection.execute("SELECT id FROM indegree LIMIT 10").fetchall()
    if remaining:
        raise ValueError(f"source cycle in {family}, mapped IDs: {remaining}")


def source_graph(layers: list[Layer], identities: Identities) -> None:
    db = identities.connection
    db.execute(
        "CREATE TABLE edges (family TEXT,upstream INTEGER,downstream INTEGER,PRIMARY KEY(family,upstream,downstream))"
    )
    db.execute("CREATE INDEX edge_destinations ON edges(family,downstream)")
    db.execute("CREATE TABLE endpoints (river INTEGER PRIMARY KEY, upstream INTEGER, downstream INTEGER)")
    db.execute("CREATE INDEX endpoint_upstream ON endpoints(upstream)")
    db.execute("CREATE INDEX endpoint_downstream ON endpoints(downstream)")
    db.execute("CREATE TABLE declared_upstream (upstream INTEGER,downstream INTEGER,PRIMARY KEY(upstream,downstream))")
    for layer in layers:
        if layer.table != "lines":
            continue
        for identity, row in selected(layer, db):
            node_space = namespace(layer.region, layer.product, "nodes")
            db.execute(
                "INSERT INTO endpoints VALUES (?,?,?)",
                (
                    identity,
                    identities.get(node_space, native_integer(row["upstream_node_id"])),
                    identities.get(node_space, native_integer(row["downstream_node_id"])),
                ),
            )
            for target in adjacent(row["downstream_line_ids"]):
                downstream = identities.get(layer.namespace, target)
                if downstream == identity:
                    raise ValueError("source self edge")
                db.execute("INSERT INTO edges VALUES ('rivers',?,?)", (identity, downstream))
            for source in adjacent(row["upstream_line_ids"]):
                db.execute(
                    "INSERT INTO declared_upstream VALUES (?,?)", (identities.get(layer.namespace, source), identity)
                )
    mismatch = db.execute(
        "SELECT upstream,downstream FROM edges WHERE family='rivers' EXCEPT SELECT upstream,downstream FROM declared_upstream"
    ).fetchone()
    mismatch = (
        mismatch
        or db.execute(
            "SELECT upstream,downstream FROM declared_upstream EXCEPT SELECT upstream,downstream FROM edges WHERE family='rivers'"
        ).fetchone()
    )
    if mismatch:
        raise ValueError(f"nonreciprocal source edge: {mismatch}")
    mismatch = db.execute(
        "SELECT e.upstream,e.downstream FROM edges e JOIN endpoints u ON u.river=e.upstream JOIN endpoints d ON d.river=e.downstream WHERE u.downstream != d.upstream LIMIT 1"
    ).fetchone()
    if mismatch:
        raise ValueError(f"source endpoint mismatch: {mismatch}")
    for layer in layers:
        if layer.table != "nodes":
            continue
        river_space = namespace(layer.region, layer.product, "lines")
        for identity, row in selected(layer, db):
            for native_field, endpoint in (("upstream_line_ids", "downstream"), ("downstream_line_ids", "upstream")):
                declared = sorted(identities.get(river_space, key) for key in adjacent(row[native_field]))
                actual = [
                    r[0]
                    for r in db.execute(f"SELECT river FROM endpoints WHERE {endpoint}=? ORDER BY river", (identity,))
                ]
                if declared != actual:
                    raise ValueError(f"source node incidence mismatch: {layer.namespace}/{row['global_id']}")
    check_dag(db, "rivers")
    db.commit()


def graph_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.int64(), False),
            pa.field("level", pa.int16(), False),
            pa.field("upstream_ids", pa.list_(pa.field("item", pa.int64(), False)), False),
        ]
        + [pa.field("bbox_" + name, pa.float32(), False) for name in ("minx", "miny", "maxx", "maxy")]
    )


def write_graph(layers: list[Layer], identities: Identities, family: str, output: Path) -> None:
    output_schema = graph_schema()
    rows: list[dict[str, object]] = []
    with pq.ParquetWriter(output, output_schema, compression="zstd") as writer:
        for layer in layers:
            if layer.family != family:
                continue
            for identity, source in selected(layer, identities.connection):
                bounds = outward_bounds(from_wkb(export_geometry(cast(bytes, source["geom"]))))
                upstream: list[int] = []
                if family == "rivers":
                    upstream = [
                        r[0]
                        for r in identities.connection.execute(
                            "SELECT upstream FROM edges WHERE family='rivers' AND downstream=? ORDER BY upstream",
                            (identity,),
                        )
                    ]
                elif layer.level:
                    river_product = "segments" if layer.level == 1 else "reaches"
                    river = identities.get(
                        namespace(layer.region, river_product, "lines"), native_integer(source["global_id"])
                    )
                    upstream = [
                        identities.get(layer.namespace, r[0])
                        for r in identities.connection.execute(
                            "SELECT i.source_id FROM edges e JOIN identities i ON i.family='rivers' AND i.id=e.upstream WHERE e.family='rivers' AND e.downstream=? ORDER BY i.source_id",
                            (river,),
                        )
                    ]
                rows.append(
                    {
                        "id": identity,
                        "level": layer.level,
                        "upstream_ids": upstream,
                        **dict(zip(("bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"), bounds, strict=True)),
                    }
                )
                if len(rows) == 256:
                    writer.write_batch(pa.RecordBatch.from_pylist(rows, schema=output_schema))
                    rows = []
        if rows:
            writer.write_batch(pa.RecordBatch.from_pylist(rows, schema=output_schema))


def verify_archives(inventory: dict[str, object]) -> None:
    for document in cast(list[dict[str, object]], inventory.get("documents", [])):
        path = Path(str(document["path"]))
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "md5").hexdigest()
        if digest != document["md5"] or path.stat().st_size != document["size_bytes"]:
            raise ValueError(f"source document checksum/size mismatch: {path}")
    for source in cast(list[dict[str, object]], inventory["sources"]):
        if inventory.get("synthetic_fixture") is True:
            continue
        archive = cast(dict[str, str], source["archive"])
        with Path(archive["path"]).open("rb") as stream:
            digest = hashlib.file_digest(stream, "md5").hexdigest()
        if digest != archive["md5"]:
            raise ValueError(f"source archive checksum mismatch: {archive['path']}")
        path = Path(str(source["path"]))
        with zipfile.ZipFile(archive["path"]) as zipped:
            members = [item for item in zipped.infolist() if Path(item.filename).name == path.name]
            if len(members) != 1:
                raise ValueError(f"expected exactly one original GeoPackage member: {path.name}")
            with zipped.open(members[0]) as member, path.open("rb") as loose:
                member_digest = hashlib.file_digest(cast(zipfile.ZipExtFile, member), "sha256").hexdigest()
                loose_digest = hashlib.file_digest(loose, "sha256").hexdigest()
            if member_digest != loose_digest:
                raise ValueError(f"extracted source differs from verified archive: {path}")


def finish_manifest(
    inventory: dict[str, object],
    layers: list[Layer],
    identities: Identities,
    output: Path,
    elapsed: float,
    source_identities: dict[Path, Fingerprint],
) -> None:
    layer_ledger: list[dict[str, object]] = []
    for layer in layers:
        count = identities.connection.execute(
            "SELECT COUNT(*) FROM selected_rows WHERE namespace=?", (layer.namespace,)
        ).fetchone()[0]
        layer_ledger.append(
            {
                "namespace": layer.namespace,
                "product": layer.product,
                "region": layer.region,
                "table": layer.table,
                "count": count,
                "fields": [
                    {"name": name, "type": kind, "nullable": nullable, "output": "source_" + name}
                    for name, kind, nullable in layer.fields
                ],
            }
        )
    write_json(
        output / "source-provenance.json",
        {
            "inventory": inventory,
            "layers": layer_ledger,
            "sources": [{"path": str(path), **identity} for path, identity in source_identities.items()],
            "transformations": {
                "geometry": "GeoPackage header removed; EPSG:8857 to EPSG:4326 with pyproj always_xy; vertex/part/ring order retained; no repair, clipping, simplification or reversal",
                "area_km2": "WGS84 geodesic shell area minus holes per polygon; sum components; float32 km2. Native source_area remains equal-area km2.",
                "bounds": "float32 rounded outward",
                "source_columns": "All native nongeometry fields prefixed source_ to separate original identities from normalized references; ledger preserves exact names/types. Absent tier fields become null, distinct from source null via layer schema.",
                "grouping": "256 source rows per Arrow incoming batch, documented product/region/table order then fid ascending; 8388608 byte IPC budget",
                "geometry_orientation": "0 unspecified; source-directed endpoints and graph remain authoritative",
            },
            "selection": {"components": inventory.get("components"), "flow_edges_cut": 0},
            "elapsed_seconds": elapsed,
        },
    )
    (output / "NOTICE").write_text(
        "GRIT v1.0, Wortmann et al. (2025), Global River Topology vector datasets. CC BY-NC 4.0: https://creativecommons.org/licenses/by-nc/4.0/ . Source: https://doi.org/10.5281/zenodo.17435232 . Geometry reprojected and fields normalized; source attributes retained. Noncommercial redistribution only.\n"
    )
    (output / "CITATION.txt").write_text(
        "Wortmann et al. (2025), Global River Topology (GRIT) vector datasets, v1.0. https://doi.org/10.5281/zenodo.17435232\n"
    )
    raster_note = (
        "The manifest references the existing unchanged redesigned rasters; their retention is required for this bundle lifetime."
        if inventory.get("external_rasters") is True
        else "This local vector delivery does not declare production external raster references."
    )
    (output / "README.md").write_text(
        "# GRIT original vector conversion\n\nOriginal projected GeoPackage geometry is exported and reprojected without repair. Source fields, identities, types and nulls are retained under source_ names; source-provenance.json records exact mappings. Source partitioned and mainstem drainage areas are not upstream polygon-union areas. Components have no invented outlet or connectivity. Geometry orientation is unspecified. Source diagnostics do not certify hydrological continuity. Graph acyclicity and references are checked; independent fidelity verification is required before publication. No raster or snap copies are produced. "
        + raster_note
        + "\n"
    )
    for document in cast(list[dict[str, object]], inventory.get("documents", [])):
        name = str(document["name"])
        if name not in {"README.pdf", "LICENSE.md"}:
            raise ValueError(f"unexpected original source document: {name}")
        (output / ("GRIT-original-" + name)).write_bytes(Path(str(document["path"])).read_bytes())
    paths = [p for p in output.iterdir() if p.is_file() and p.suffix != ".sqlite"]
    artifacts = {p.name: fingerprint(p) for p in sorted(paths)}
    bounds = [float("inf"), float("inf"), float("-inf"), float("-inf")]
    for batch in pq.ParquetFile(output / "graph.parquet").iter_batches(
        columns=["bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"]
    ):
        for i in range(4):
            values = cast(list[float], batch.column(i).to_pylist())
            bounds[i] = min(bounds[i], min(values)) if i < 2 else max(bounds[i], max(values))

    def declaration(prefix: str, count: int) -> dict[str, object]:
        return {
            "data": "rivers.arrow" if prefix == "river" else "river-nodes.arrow",
            "lookup": prefix + "-lookup.arrow",
            "directory": prefix + "-lookup-directory.json",
            "count": count,
            "batch_bytes": 8388608,
            "index_batch_rows": 65536,
        }

    rivers = declaration("river", identities.counts["rivers"])
    rivers.update(graph="river-graph.parquet", topology="dag")
    categories: list[Category] = [
        {
            "artifact": artifact,
            "column": "level",
            "physical_type": "int16",
            "codes": [{"code": i, "meaning": meaning} for i, meaning in enumerate(meanings)],
            "null_meaning": "not permitted",
        }
        for artifact, meanings in (
            ("catchments.arrow", ("component", "segment local drainage unit", "reach local drainage unit")),
            ("rivers.arrow", ("segment", "reach")),
            ("river-nodes.arrow", ("segment node", "reach node")),
        )
    ]
    for family, artifact in (
        ("catchments", "catchments.arrow"),
        ("rivers", "rivers.arrow"),
        ("nodes", "river-nodes.arrow"),
    ):
        categories.extend(
            native_categories(artifact, schema(family, [layer for layer in layers if layer.family == family]))
        )
    categories.append(
        {
            "artifact": "rivers.arrow",
            "column": "geometry_orientation",
            "physical_type": "int8",
            "codes": [
                {
                    "code": 0,
                    "meaning": "unspecified coordinate orientation; source-directed connectivity is authoritative",
                }
            ],
            "null_meaning": "not permitted",
        }
    )
    write_json(
        output / "manifest.json",
        {
            "format_version": "0.4.0",
            "fabric_name": "grit",
            "fabric_version": "1.0",
            "crs": "EPSG:4326",
            "has_up_area": False,
            "topology": "dag",
            "bbox": bounds,
            "unit_count": identities.counts["catchments"],
            "created_at": datetime.now(UTC).isoformat(),
            "adapter_version": "grit-original-vectors-1",
            "region": "component sample" if "components" in inventory else "global",
            "catchments": "catchments.arrow",
            "graph": "graph.parquet",
            "lookup": "lookup.arrow",
            "directory": "lookup-directory.json",
            "index_batch_rows": 65536,
            "catchment_batch_bytes": 8388608,
            **external_rasters(production=inventory.get("external_rasters") is True),
            "rivers": rivers,
            "river_nodes": declaration("river-node", identities.counts["nodes"]),
            "catchment_connectivity": [
                {"level": 0, "status": "not_supplied"},
                {"level": 1, "status": "supplied"},
                {"level": 2, "status": "supplied"},
            ],
            "categorical_columns": categories,
            "artifacts": artifacts,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    produce(args.inventory, args.output)


if __name__ == "__main__":
    main()
