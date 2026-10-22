"""Independently compare normalized TDX staging against acquired original GeoPackages."""

import argparse
import hashlib
import json
import sqlite3
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
from pyproj import Geod
from shapely import from_wkb, get_coordinates

from hfx.candidates import fingerprint


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    with ipc.open_file(str(path)) as reader:
        for index in range(reader.num_record_batches):
            yield from reader.get_batch(index).to_pylist()


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_originals(inventory_path: Path, output: Path) -> dict[str, object]:
    """Full source/value/geometry/edge comparison; no polygon-overlap certification.

    Reads SQLite originals directly, not the normalizer or its ingestion helper.
    Numeric identity and edge sets require measured memory; geometry is streamed.
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
    counts: dict[str, int] = {}
    source_hashes: dict[str, str] = {}
    rivers: dict[tuple[str, int], int] = {}
    polygons: list[tuple[str, int, int]] = []
    downstream: set[tuple[str, int, int]] = set()
    upstream: set[tuple[str, int, int]] = set()
    river_bounds: dict[int, dict[str, float]] = {}
    degenerate = 0
    geod = Geod(ellps="WGS84")
    for domain in ("catchments", "rivers"):
        path = output / f"{domain}.arrow"
        with ipc.open_file(str(path)) as reader:
            schema = reader.schema
        actual_rows = _rows(path)
        count = 0
        for item in sorted(inventory["sources"], key=lambda value: value["basin"]):
            basin = item["basin"]
            source = Path(item[domain]["path"])
            digest = _digest(source)
            if digest != item[domain]["sha256"]:
                raise ValueError("Original source digest differs")
            source_hashes[str(source)] = digest
            connection = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                (layer,) = connection.execute(
                    "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
                ).fetchone()
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
                    if (
                        field.type != expected_types[declared]
                        or field.nullable != (not nonnull)
                        or field.metadata != {b"gpkg:declared_type": declared.encode()}
                    ):
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
                    allowed = (
                        {"Polygon", "MultiPolygon"} if domain == "catchments" else {"LineString", "MultiLineString"}
                    )
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
                        polygons.append((basin, original["streamID"], actual["id"]))
                    else:
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
                        rivers[basin, link] = actual["id"]
                        river_bounds[actual["id"]] = bounds
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
        if next(actual_rows, None) is not None:
            raise ValueError("Extra normalized feature")
        counts[domain] = count
    if downstream != upstream:
        raise ValueError("Original supplied graph directions disagree")
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
    actual_edges: set[tuple[int, int]] = set()
    graph_ids: set[int] = set()
    for batch in pq.ParquetFile(output / "river-graph.parquet").iter_batches():
        for row in batch.to_pylist():
            identity = row["id"]
            if identity in graph_ids or identity not in river_bounds or row["level"] != 0:
                raise ValueError("Graph feature coverage differs")
            graph_ids.add(identity)
            if list(river_bounds[identity].values()) != [
                row[name] for name in ("bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy")
            ]:
                raise ValueError("Graph bounds differ")
            for origin in row["upstream_ids"]:
                if (origin, identity) in actual_edges:
                    raise ValueError("Duplicate normalized flow edge")
                actual_edges.add((origin, identity))
    if graph_ids != set(rivers.values()) or actual_edges != expected_edges:
        raise ValueError("Complete supplied flow differs")
    expected_associations = {(rivers[basin, stream], identity) for basin, stream, identity in polygons}
    actual_associations: set[tuple[int, int]] = set()
    for batch in pq.ParquetFile(output / "local-associations.parquet").iter_batches():
        for row in batch.to_pylist():
            pair = (row["river_id"], row["catchment_id"])
            if pair in actual_associations:
                raise ValueError("Duplicate local association")
            actual_associations.add(pair)
    if actual_associations != expected_associations:
        raise ValueError("Complete local associations differ")
    for path, digest in source_hashes.items():
        if _digest(Path(path)) != digest:
            raise ValueError("Source changed during verification")
    return {
        "status": "passed",
        "features": counts,
        "flow_edges": len(expected_edges),
        "local_associations": len(expected_associations),
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
