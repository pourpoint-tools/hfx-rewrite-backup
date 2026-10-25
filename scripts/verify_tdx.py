"""Independently compare normalized TDX staging against acquired original GeoPackages."""

import argparse
import hashlib
import json
import sqlite3
import struct
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
from pyproj import Geod
from shapely import from_wkb, get_coordinates

from hfx.candidates import fingerprint


def _rows(path: Path) -> Generator[dict[str, Any]]:
    with ipc.open_file(str(path)) as reader:
        for index in range(reader.num_record_batches):
            yield from reader.get_batch(index).to_pylist()


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def _actual_relations(output: Path) -> Iterator[sqlite3.Connection]:
    """Disk-backed actual evidence preserves arbitrary physical relation order."""
    with TemporaryDirectory(prefix="hfx-verify-") as scratch:
        connection = sqlite3.connect(Path(scratch) / "actual.sqlite")
        try:
            connection.execute("PRAGMA cache_size = -8192")
            connection.execute("PRAGMA temp_store = FILE")
            connection.execute(
                "CREATE TABLE graph (id INTEGER PRIMARY KEY, level INTEGER NOT NULL, xmin REAL NOT NULL, ymin REAL NOT NULL, xmax REAL NOT NULL, ymax REAL NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE edge (origin INTEGER NOT NULL, target INTEGER NOT NULL, PRIMARY KEY(origin, target))"
            )
            connection.execute("CREATE INDEX edge_target ON edge(target)")
            connection.execute(
                "CREATE TABLE association (river INTEGER NOT NULL, catchment INTEGER NOT NULL, PRIMARY KEY(river, catchment))"
            )
            connection.execute("CREATE INDEX association_catchment ON association(catchment)")
            for batch in pq.ParquetFile(output / "river-graph.parquet").iter_batches(batch_size=4096):
                with connection:
                    for row in batch.to_pylist():
                        identity, level, upstream = row["id"], row["level"], row["upstream_ids"]
                        bounds = [row[name] for name in ("bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy")]
                        if (
                            type(identity) is not int
                            or type(level) is not int
                            or not isinstance(upstream, list)
                            or any(type(value) is not int for value in upstream)
                        ):
                            raise ValueError("Invalid graph identity or adjacency")
                        if any(type(value) is not float or not np.isfinite(value) for value in bounds):
                            raise ValueError("Invalid graph bounds")
                        connection.execute("INSERT INTO graph VALUES (?, ?, ?, ?, ?, ?)", (identity, level, *bounds))
                        connection.executemany(
                            "INSERT INTO edge VALUES (?, ?)", ((origin, identity) for origin in upstream)
                        )
            for batch in pq.ParquetFile(output / "local-associations.parquet").iter_batches(batch_size=4096):
                with connection:
                    for row in batch.to_pylist():
                        pair = row["river_id"], row["catchment_id"]
                        if any(type(value) is not int for value in pair):
                            raise ValueError("Invalid local association")
                        connection.execute("INSERT INTO association VALUES (?, ?)", pair)
            yield connection
        except sqlite3.IntegrityError as error:
            raise ValueError("Duplicate or invalid normalized relation") from error
        finally:
            connection.close()


def _verify_basin(
    item: dict[str, Any],
    schemas: dict[str, pa.Schema],
    iterators: dict[str, Generator[dict[str, Any]]],
    counts: dict[str, int],
    source_hashes: dict[str, str],
    relations: sqlite3.Connection,
) -> tuple[int, int, int]:
    """Independently prove one basin, releasing its topology before the next."""
    rivers: dict[tuple[str, int], int] = {}
    polygons: list[tuple[str, int, int]] = []
    downstream: set[tuple[str, int, int]] = set()
    upstream: set[tuple[str, int, int]] = set()
    river_bounds: dict[int, dict[str, float]] = {}
    degenerate = 0
    unavailable = item["catchments"].get("status") == "unavailable"
    geod = Geod(ellps="WGS84")
    for domain in ("catchments", "rivers"):
        if domain == "catchments" and unavailable:
            continue
        schema = schemas[domain]
        actual_rows = iterators[domain]
        count = counts[domain]
        basin = item["basin"]
        source = Path(item[domain]["path"])
        digest = _digest(source)
        if digest != item[domain]["sha256"]:
            raise ValueError("Original source digest differs")
        source_hashes[str(source)] = digest
        connection = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            (layer,) = connection.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchone()
            quoted = '"' + layer.replace('"', '""') + '"'
            fields = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
            geometry, srs, z, m = connection.execute(
                "SELECT column_name, srs_id, z, m FROM gpkg_geometry_columns WHERE table_name=?", (layer,)
            ).fetchone()
            if (srs, z, m) != (4326, 0, 0):
                raise ValueError("Original geometry declaration differs")
            expected_types = {"INTEGER": pa.int64(), "MEDIUMINT": pa.int32(), "REAL": pa.float64()}
            for _, name, declared, nonnull, _, _ in fields:
                if name == geometry:
                    continue
                field = schema.field(name)
                mapped = domain == "catchments" and name == "streamID"
                if mapped and declared not in ("INTEGER", "MEDIUMINT"):
                    raise ValueError("Unsupported original streamID declaration")
                expected_type = pa.int64() if mapped else expected_types[declared]
                metadata = (
                    {b"hfx:source_mapping": b"streamID INTEGER/MEDIUMINT to int64, lossless"}
                    if mapped
                    else {b"gpkg:declared_type": declared.encode()}
                )
                if field.type != expected_type or field.nullable != (not nonnull) or field.metadata != metadata:
                    raise ValueError(f"Native schema differs: {name}")
            for values in connection.execute(f"SELECT * FROM {quoted} ORDER BY fid"):
                original = dict(zip((field[1] for field in fields), values, strict=True))
                actual = next(actual_rows, None)
                if actual is None:
                    raise ValueError("Missing source feature")
                count += 1
                if (
                    actual["id"] != count
                    or actual["source_id"] != str(original["fid"])
                    or actual["processing_basin"] != basin
                    or actual["source_namespace"] != f"NGA-TDX-Hydro-20230126/{basin}/{domain}"
                ):
                    raise ValueError("Source feature identity differs")
                for name, value in original.items():
                    if name == geometry:
                        continue
                    stored = actual[name]
                    equal = (
                        struct.pack("!d", value) == struct.pack("!d", stored)
                        if isinstance(value, float) and isinstance(stored, float)
                        else value == stored and type(value) is type(stored)
                    )
                    if not equal:
                        raise ValueError(f"Native value or null differs: {name}")
                blob = original[geometry]
                if blob[:3] != b"GP\x00" or blob[3] & 0xF0:
                    raise ValueError("Unsupported original geometry header")
                envelope = (blob[3] >> 1) & 7
                if envelope not in (0, 1):
                    raise ValueError("Unsupported source dimensions")
                wkb = blob[8 + (32 if envelope == 1 else 0) :]
                if actual["geometry"] != wkb:
                    raise ValueError("Original geometry bytes/order differ")
                shape = from_wkb(wkb)
                coordinates = get_coordinates(shape)
                allowed = {"Polygon", "MultiPolygon"} if domain == "catchments" else {"LineString", "MultiLineString"}
                if (
                    shape.geom_type not in allowed
                    or shape.is_empty
                    or not np.isfinite(coordinates).all()
                    or (np.abs(coordinates[:, 0]) > 180).any()
                    or (np.abs(coordinates[:, 1]) > 90).any()
                ):
                    raise ValueError("Original geometry coordinates/type do not conform")
                bounds = actual["bbox"]
                xmin, ymin, xmax, ymax = shape.bounds
                if not all(np.isfinite(list(bounds.values()))) or not (
                    bounds["xmin"] <= xmin <= xmax <= bounds["xmax"]
                    and bounds["ymin"] <= ymin <= ymax <= bounds["ymax"]
                ):
                    raise ValueError("Geometry bounds do not cover source")
                if actual["level"] != 0 or actual["parent_id"] is not None:
                    raise ValueError("Invented hierarchy")
                if domain == "catchments":
                    parts = shape.geoms if shape.geom_type == "MultiPolygon" else [shape]
                    area = 0.0
                    for polygon in parts:
                        x, y = polygon.exterior.xy
                        part_area = abs(geod.polygon_area_perimeter(x, y)[0])
                        for ring in polygon.interiors:
                            x, y = ring.xy
                            part_area -= abs(geod.polygon_area_perimeter(x, y)[0])
                        area += part_area / 1e6
                    if not shape.is_valid or actual["area_km2"] != float(np.float32(area)):
                        raise ValueError("Original polygon/derived geodesic area differs")
                    if any(actual[name] is not None for name in ("up_area_km2", "outlet_lon", "outlet_lat")):
                        raise ValueError("Invented upstream area or outlet")
                    polygons.append((basin, original["streamID"], count))
                else:
                    if actual["local_catchment_coverage"] != ("unavailable" if unavailable else "supplied"):
                        raise ValueError("Local catchment coverage differs from original inventory")
                    if actual["geometry_orientation"] != 0 or any(
                        actual[name] is not None
                        for name in ("component_catchment_id", "upstream_node_id", "downstream_node_id")
                    ):
                        raise ValueError("Invented river orientation or incidence")
                    if shape.length == 0:
                        degenerate += 1
                    link = original["LINKNO"]
                    if (basin, link) in rivers:
                        raise ValueError("Duplicate source LINKNO")
                    rivers[basin, link] = count
                    river_bounds[count] = bounds
                    if original["DSLINKNO"] != -1:
                        downstream.add((basin, link, original["DSLINKNO"]))
                    for name in ("USLINKNO1", "USLINKNO2"):
                        if original[name] != -1:
                            edge = (basin, original[name], link)
                            if edge in upstream:
                                raise ValueError("Duplicate original upstream edge")
                            upstream.add(edge)
        finally:
            connection.close()
        counts[domain] = count
    if not rivers or (not unavailable and not polygons):
        raise ValueError("Empty original basin domain")
    if downstream != upstream:
        raise ValueError("Original supplied graph directions disagree")
    if any((basin, origin) not in rivers or (basin, target) not in rivers for basin, origin, target in downstream):
        raise ValueError("Unresolved original river relationship")
    expected_edges = {(rivers[basin, origin], rivers[basin, target]) for basin, origin, target in downstream}
    # Independent downstream-chain cycle check (producer uses Kahn traversal).
    successor = dict(expected_edges)
    completed: set[int] = set()
    for identity in rivers.values():
        path_ids: set[int] = set()
        current = identity
        while current in successor and current not in completed:
            if current in path_ids:
                raise ValueError("Original graph contains a cycle")
            path_ids.add(current)
            current = successor[current]
        completed.update(path_ids)
    low, high = min(river_bounds), max(river_bounds)
    graph_count = 0
    for identity, level, xmin, ymin, xmax, ymax in relations.execute(
        "SELECT * FROM graph WHERE id BETWEEN ? AND ? ORDER BY id", (low, high)
    ):
        if identity not in river_bounds or level != 0:
            raise ValueError("Graph feature coverage differs")
        if list(river_bounds[identity].values()) != [xmin, ymin, xmax, ymax]:
            raise ValueError("Graph bounds differ")
        graph_count += 1
    if graph_count != len(river_bounds):
        raise ValueError("Graph feature coverage differs")
    actual_edges = set(relations.execute("SELECT origin, target FROM edge WHERE target BETWEEN ? AND ?", (low, high)))
    if actual_edges != expected_edges:
        raise ValueError("Complete supplied flow differs")
    if any((basin, stream) not in rivers for basin, stream, _ in polygons):
        raise ValueError("Unmatched original polygon streamID")
    expected_associations = {(rivers[basin, stream], identity) for basin, stream, identity in polygons}
    polygon_ids = [identity for _, _, identity in polygons]
    if unavailable:
        if relations.execute("SELECT 1 FROM association WHERE river BETWEEN ? AND ? LIMIT 1", (low, high)).fetchone():
            raise ValueError("Invented associations for unavailable catchment source")
        return len(expected_edges), 0, degenerate
    actual_associations = set(
        relations.execute(
            "SELECT river, catchment FROM association WHERE catchment BETWEEN ? AND ?",
            (min(polygon_ids), max(polygon_ids)),
        )
    )
    if actual_associations != expected_associations:
        raise ValueError("Complete local associations differ")
    return len(expected_edges), len(expected_associations), degenerate


def _verify_source_metadata(inventory: dict[str, Any], output: Path) -> None:
    """Compare provenance declarations directly with each original SQLite file."""
    recorded = json.loads((output / "source-metadata.json").read_bytes())
    expected: list[dict[str, Any]] = []
    sources = inventory["sources"]
    basins = [item["basin"] for item in sources]
    if not basins or len(set(basins)) != len(basins):
        raise ValueError("Invalid source basin coverage")
    supplied_polygons = 0
    for item in sorted(sources, key=lambda value: value["basin"]):
        for domain in ("catchments", "rivers"):
            entry = item.get(domain)
            if not isinstance(entry, dict):
                raise ValueError("Missing source coverage declaration")
            base = {"basin": item["basin"], "domain": domain}
            if "status" in entry:
                if (
                    domain != "catchments"
                    or entry.get("status") != "unavailable"
                    or set(entry) != {"status", "reason"}
                    or not isinstance(entry["reason"], str)
                    or not entry["reason"].strip()
                ):
                    raise ValueError("Invalid unavailable source coverage declaration")
                expected.append({**base, **entry})
                continue
            if not {"path", "sha256"}.issubset(entry):
                raise ValueError("Missing supplied source coverage declaration")
            supplied_polygons += domain == "catchments"
            source = Path(entry["path"])
            digest = entry["sha256"]
            connection = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                connection.row_factory = sqlite3.Row
                contents = [dict(row) for row in connection.execute("SELECT * FROM gpkg_contents")]
                schemas = {}
                for layer in contents:
                    if layer["data_type"] == "features":
                        name = layer["table_name"]
                        quoted = '"' + name.replace('"', '""') + '"'
                        schemas[name] = [dict(row) for row in connection.execute(f"PRAGMA table_info({quoted})")]
                expected.append(
                    {
                        **base,
                        "status": "supplied",
                        "sha256": digest,
                        "contents": contents,
                        "geometry_columns": [
                            dict(row) for row in connection.execute("SELECT * FROM gpkg_geometry_columns")
                        ],
                        "schemas": schemas,
                    }
                )
            finally:
                connection.close()
    if not supplied_polygons:
        raise ValueError("No supplied catchment source coverage")
    if recorded != expected:
        raise ValueError("Source metadata differs from originals or coverage inventory")


def verify_originals(inventory_path: Path, output: Path) -> dict[str, object]:
    """Full source/value/geometry/edge comparison; no polygon-overlap certification.

    Reads SQLite originals directly, not the normalizer or its ingestion helper.
    Numeric topology is basin-local; actual relations are disk-backed and geometry is streamed.
    """
    inventory = json.loads(inventory_path.read_bytes())
    manifest = json.loads((output / "manifest.json").read_bytes())
    if (output / "original-inventory.json").read_bytes() != inventory_path.read_bytes():
        raise ValueError("Original inventory bytes differ")
    for name, identity in manifest["artifacts"].items():
        path = output / name
        if not path.resolve().is_relative_to(output.resolve()) or fingerprint(path) != identity:
            raise ValueError("Normalized artifact identity differs")
    if (
        manifest.get("graph")
        or manifest.get("river_nodes")
        or manifest["catchment_connectivity"] != [{"level": 0, "status": "not_supplied"}]
    ):
        raise ValueError("Invented catchment graph or node domain")
    expected_categories = [
        {
            "artifact": "rivers.arrow",
            "column": "local_catchment_coverage",
            "physical_type": "string",
            "codes": [
                {"code": "supplied", "meaning": "Polygon source supplied; local associations exhaustively checked"},
                {"code": "unavailable", "meaning": "Polygon source unavailable; local associations unknown"},
            ],
            "null_meaning": "not permitted",
        }
    ]
    if manifest.get("categorical_columns") != expected_categories:
        raise ValueError("Manifest local catchment coverage semantics differ")
    _verify_source_metadata(inventory, output)
    counts = {"catchments": 0, "rivers": 0}
    source_hashes: dict[str, str] = {}
    schemas: dict[str, pa.Schema] = {}
    iterators: dict[str, Generator[dict[str, Any]]] = {}
    for domain in counts:
        with ipc.open_file(str(output / f"{domain}.arrow")) as reader:
            schemas[domain] = reader.schema
        iterators[domain] = _rows(output / f"{domain}.arrow")
    coverage_field = schemas["rivers"].field("local_catchment_coverage")
    if coverage_field.type != pa.string() or coverage_field.nullable:
        raise ValueError("Invalid local catchment coverage schema")
    flow_edges = associations = degenerate = 0
    try:
        with _actual_relations(output) as actual:
            for item in sorted(inventory["sources"], key=lambda value: value["basin"]):
                edges, pairs, zeros = _verify_basin(item, schemas, iterators, counts, source_hashes, actual)
                flow_edges += edges
                associations += pairs
                degenerate += zeros
            for table, expected in (("graph", counts["rivers"]), ("edge", flow_edges), ("association", associations)):
                if actual.execute(f"SELECT count(*) FROM {table}").fetchone()[0] != expected:
                    raise ValueError("Extra normalized relations")
            if any(next(rows, None) is not None for rows in iterators.values()):
                raise ValueError("Extra normalized feature")
    finally:
        for rows in iterators.values():
            rows.close()
    if counts["catchments"] != manifest["unit_count"] or counts["rivers"] != manifest["rivers"]["count"]:
        raise ValueError("Manifest feature counts differ")
    for path, digest in source_hashes.items():
        if _digest(Path(path)) != digest:
            raise ValueError("Source changed during verification")
    return {
        "status": "passed",
        "features": counts,
        "flow_edges": flow_edges,
        "local_associations": associations,
        "zero_length_rivers": degenerate,
        "manifest_sha256": _digest(output / "manifest.json"),
        "inventory_sha256": _digest(inventory_path),
        "geometry_coverage": "all features, exact embedded WKB and bounds",
        "polygon_overlap_coverage": "not checked",
        "scope": "Original-to-normalized staging only; final spatial artifacts and publication require separate verification.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists() or args.report.resolve().is_relative_to(args.output.resolve()):
        raise ValueError("Report must be new and outside bundle")
    result = verify_originals(args.inventory, args.output)
    with args.report.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
