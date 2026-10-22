"""Normalize original TDX vectors without source geometry or hydrology repair."""

import argparse
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import chain
from pathlib import Path
from typing import Literal

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Geod
from shapely import from_wkb, get_coordinates

from hfx.candidates import fingerprint
from hfx.tdx_source import read_layer
from hfx.vector_storage import write_vectors

BOUNDS = pa.struct([pa.field(name, pa.float32(), nullable=False) for name in ("xmin", "ymin", "xmax", "ymax")])


def normalized_batch(
    source: pa.RecordBatch, domain: Literal["catchments", "rivers"], basin: str, *, first_id: int
) -> pa.RecordBatch:
    """Map one fid-ordered native batch; numbering is dataset-local, not a source ID."""
    if not basin.isdecimal() or first_id <= 0:
        raise ValueError("Invalid basin identity or first dataset ID")
    common = [
        pa.field("id", pa.int64(), nullable=False),
        pa.field("level", pa.int16(), nullable=False),
        pa.field("parent_id", pa.int64()),
        pa.field("source_namespace", pa.string(), nullable=False),
        pa.field("source_id", pa.string(), nullable=False),
        pa.field("processing_basin", pa.string(), nullable=False),
        pa.field("bbox", BOUNDS, nullable=False),
        pa.field("geometry", pa.binary(), nullable=False),
    ]
    extra = (
        [
            pa.field("area_km2", pa.float32(), nullable=False),
            pa.field("up_area_km2", pa.float32()),
            pa.field("outlet_lon", pa.float64()),
            pa.field("outlet_lat", pa.float64()),
        ]
        if domain == "catchments"
        else [
            pa.field("component_catchment_id", pa.int64()),
            pa.field("upstream_node_id", pa.int64()),
            pa.field("downstream_node_id", pa.int64()),
            pa.field("geometry_orientation", pa.int8(), nullable=False),
        ]
    )
    native = [field for field in source.schema if field.name != "geom"]
    if {field.name for field in native} & {field.name for field in common + extra}:
        raise ValueError("Native column collides with normalized field; explicit rename required")
    schema = pa.schema(common + extra + native)
    rows: list[dict[str, object]] = []
    geod = Geod(ellps="WGS84")
    allowed = {"Polygon", "MultiPolygon"} if domain == "catchments" else {"LineString", "MultiLineString"}
    for offset, row in enumerate(source.to_pylist()):
        wkb = row.pop("geom")
        shape = from_wkb(wkb)
        if shape.geom_type not in allowed or shape.is_empty or shape.has_z or shape.has_m:
            raise ValueError("Unsupported original geometry type, dimensions or empty geometry")
        coordinates = get_coordinates(shape)
        if (
            not np.all(np.isfinite(coordinates))
            or np.any(np.abs(coordinates[:, 0]) > 180)
            or np.any(np.abs(coordinates[:, 1]) > 90)
        ):
            raise ValueError("Original coordinate outside finite longitude/latitude domain")
        bounds = np.asarray(shape.bounds)
        narrowed = bounds.astype(np.float32)
        for index in range(4):
            if (index < 2 and narrowed[index] > bounds[index]) or (index >= 2 and narrowed[index] < bounds[index]):
                narrowed[index] = np.nextafter(narrowed[index], np.float32(-np.inf if index < 2 else np.inf))
        row.update(
            id=first_id + offset,
            level=0,
            parent_id=None,
            source_namespace=f"NGA-TDX-Hydro-20230126/{basin}/{domain}",
            source_id=str(row["fid"]),
            processing_basin=basin,
            bbox=dict(zip(("xmin", "ymin", "xmax", "ymax"), narrowed.tolist(), strict=True)),
            geometry=wkb,
        )
        if domain == "catchments":
            if not shape.is_valid:
                raise ValueError("Invalid original polygon requires explicit source decision")
            # Sum native parts, never union/dissolve; absolute signed geodesic ring area.
            parts = list(shape.geoms) if shape.geom_type == "MultiPolygon" else [shape]
            area = 0.0
            for part in parts:
                exterior = abs(geod.polygon_area_perimeter(*part.exterior.xy)[0])
                holes = sum(abs(geod.polygon_area_perimeter(*ring.xy)[0]) for ring in part.interiors)
                area += (exterior - holes) / 1e6
            if not np.isfinite(area) or area <= 0:
                raise ValueError("Original polygon has no positive finite geodesic area")
            row.update(area_km2=area, up_area_km2=None, outlet_lon=None, outlet_lat=None)
        else:
            row.update(
                component_catchment_id=None, upstream_node_id=None, downstream_node_id=None, geometry_orientation=0
            )
        rows.append(row)
    return pa.RecordBatch.from_pylist(rows, schema=schema)


def source_relationships(
    rivers: list[tuple[int, int, int, int, int]], polygons: list[tuple[int, int]]
) -> tuple[dict[int, list[int]], list[tuple[int, int]]]:
    """Validate both supplied directions before mapping one processing basin.

    River tuples contain HFX ID, LINKNO, DSLINKNO, USLINKNO1, USLINKNO2.
    Polygon tuples contain HFX ID and native association streamID.
    No graph contraction through polygonless rivers and no cross-basin inference.
    """
    native = {link: identity for identity, link, _, _, _ in rivers}
    if len(native) != len(rivers) or len({row[0] for row in rivers}) != len(rivers):
        raise ValueError("Duplicate native river or dataset identity")
    downstream: set[tuple[int, int]] = set()
    upstream: set[tuple[int, int]] = set()
    for _, link, target, first, second in rivers:
        if link < 0:
            raise ValueError("Invalid native river identity")
        for other in (target, first, second):
            if other != -1 and other not in native:
                raise ValueError("Unresolved supplied river relationship")
            if other == link:
                raise ValueError("Self-linked supplied river relationship")
        if target != -1:
            downstream.add((link, target))
        for origin in (first, second):
            if origin != -1:
                edge = (origin, link)
                if edge in upstream:
                    raise ValueError("Duplicate supplied upstream relationship")
                upstream.add(edge)
    if upstream != downstream:
        raise ValueError("Supplied upstream and downstream relationships disagree")
    incoming: dict[int, list[int]] = {identity: [] for identity in native.values()}
    successors: dict[int, list[int]] = {link: [] for link in native}
    degree = dict.fromkeys(native, 0)
    for origin, target in downstream:
        incoming[native[target]].append(native[origin])
        successors[origin].append(target)
        degree[target] += 1
    pending = [link for link, count in degree.items() if count == 0]
    visited = 0
    while pending:
        origin = pending.pop()
        visited += 1
        for target in successors[origin]:
            degree[target] -= 1
            if degree[target] == 0:
                pending.append(target)
    if visited != len(native):
        raise ValueError("Supplied river graph contains a cycle")
    associations: list[tuple[int, int]] = []
    if len({identity for identity, _ in polygons}) != len(polygons):
        raise ValueError("Duplicate polygon feature identity")
    for identity, stream in polygons:
        if stream not in native:
            raise ValueError("Unmatched polygon streamID")
        associations.append((native[stream], identity))
    return {identity: sorted(values) for identity, values in incoming.items()}, sorted(associations)


def produce(inventory_path: Path, output: Path) -> None:
    """Create private normalized staging; independent verification is required."""
    inventory = json.loads(inventory_path.read_bytes())
    if inventory["release"] != "NGA-TDX-Hydro-20230126":
        raise ValueError("Unsupported source release")
    sources = sorted(inventory["sources"], key=lambda item: item["basin"])
    basins = [item["basin"] for item in sources]
    if not basins or len(set(basins)) != len(basins):
        raise ValueError("Source processing basins must be nonempty and unique")
    before: dict[Path, str] = {}
    source_metadata: list[dict[str, object]] = []
    for item in sources:
        for domain in ("catchments", "rivers"):
            path = Path(item[domain]["path"])
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != item[domain]["sha256"]:
                raise ValueError("Original source digest differs from acquisition inventory")
            before[path] = digest
            connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                connection.row_factory = sqlite3.Row
                contents = [dict(row) for row in connection.execute("SELECT * FROM gpkg_contents")]
                layers = [row["table_name"] for row in contents if row["data_type"] == "features"]
                schemas = {}
                for layer in layers:
                    quoted = '"' + layer.replace('"', '""') + '"'
                    schemas[layer] = [dict(row) for row in connection.execute(f"PRAGMA table_info({quoted})")]
                source_metadata.append(
                    {
                        "basin": item["basin"],
                        "domain": domain,
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

    output.mkdir(parents=True, exist_ok=False)
    counts = {"catchments": 0, "rivers": 0}
    overall = [float("inf"), float("inf"), -float("inf"), -float("inf")]
    # Numeric topology only: geometry streams in bounded incoming groups.
    river_rows: dict[str, list[tuple[int, int, int, int, int]]] = {}
    polygon_rows: dict[str, list[tuple[int, int]]] = {}
    graph_bounds: dict[int, dict[str, float]] = {}
    for domain in ("catchments", "rivers"):

        def batches(domain: Literal["catchments", "rivers"] = domain) -> Iterator[pa.RecordBatch]:
            for item in sources:
                basin = item["basin"]
                river_rows.setdefault(basin, [])
                polygon_rows.setdefault(basin, [])
                for incoming in read_layer(Path(item[domain]["path"]), domain):
                    mapped = normalized_batch(incoming, domain, basin, first_id=counts[domain] + 1)
                    counts[domain] += len(mapped)
                    for row in mapped.select(
                        ["id", "bbox", "streamID"]
                        if domain == "catchments"
                        else ["id", "bbox", "LINKNO", "DSLINKNO", "USLINKNO1", "USLINKNO2"]
                    ).to_pylist():
                        identity = row["id"]
                        bbox = row["bbox"]
                        for index, name in enumerate(("xmin", "ymin", "xmax", "ymax")):
                            overall[index] = (
                                min(overall[index], bbox[name]) if index < 2 else max(overall[index], bbox[name])
                            )
                        if domain == "catchments":
                            if type(row["streamID"]) is not int:
                                raise ValueError("Null or noninteger streamID")
                            polygon_rows[basin].append((identity, row["streamID"]))
                        else:
                            values = [row[name] for name in ("LINKNO", "DSLINKNO", "USLINKNO1", "USLINKNO2")]
                            if any(type(value) is not int for value in values):
                                raise ValueError("Null or noninteger native connectivity")
                            river_rows[basin].append((identity, *values))
                            graph_bounds[identity] = bbox
                    yield mapped

        incoming = batches()
        first = next(incoming)

        prefix = "" if domain == "catchments" else "river-"
        directory = write_vectors(
            first.schema,
            chain([first], incoming),
            output / f"{domain}.arrow",
            output / f"{prefix}lookup.arrow",
            lookup_binding="hfx:catchments_sha256" if domain == "catchments" else "hfx:data_sha256",
        )
        (output / f"{prefix}lookup-directory.json").write_text(json.dumps(directory) + "\n")
    graph_schema = pa.schema(
        [
            pa.field("id", pa.int64(), nullable=False),
            pa.field("level", pa.int16(), nullable=False),
            pa.field("upstream_ids", pa.list_(pa.int64()), nullable=False),
        ]
        + [pa.field("bbox_" + name, pa.float32(), nullable=False) for name in ("minx", "miny", "maxx", "maxy")]
    )
    association_schema = pa.schema(
        [pa.field("river_id", pa.int64(), nullable=False), pa.field("catchment_id", pa.int64(), nullable=False)]
    )
    with (
        pq.ParquetWriter(output / "river-graph.parquet", graph_schema) as graph,
        pq.ParquetWriter(output / "local-associations.parquet", association_schema) as local,
    ):
        for basin in basins:
            flow, associations = source_relationships(river_rows[basin], polygon_rows[basin])
            ids = sorted(flow)
            for start in range(0, len(ids), 4096):
                rows = [
                    {
                        "id": identity,
                        "level": 0,
                        "upstream_ids": flow[identity],
                        **dict(
                            zip(
                                ("bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"),
                                graph_bounds[identity].values(),
                                strict=True,
                            )
                        ),
                    }
                    for identity in ids[start : start + 4096]
                ]
                graph.write_table(pa.Table.from_pylist(rows, schema=graph_schema))
            for start in range(0, len(associations), 4096):
                local.write_table(
                    pa.Table.from_pylist(
                        [
                            {"river_id": river, "catchment_id": catchment}
                            for river, catchment in associations[start : start + 4096]
                        ],
                        schema=association_schema,
                    )
                )
    for path, digest in before.items():
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("Original source changed during normalization")
    (output / "original-inventory.json").write_bytes(inventory_path.read_bytes())
    (output / "source-metadata.json").write_text(json.dumps(source_metadata, indent=2) + "\n")
    (output / "NOTICE").write_text(
        "Original NGA TDX-Hydro, CC BY-SA 4.0. Source release NGA-TDX-Hydro-20230126. GeoPackage headers removed; embedded WKB retained unchanged. Native fields, including raw area values, retained. Derived local area is WGS84 geodesic km2; upstream area and outlets unknown. Native zero-length rivers retained. Missing links do not classify terminals; processing-boundary truncation and coastal/dateline cuts remain source limitations. No invented catchment connectivity or source nodes. Source schemas must match across basin inputs.\n"
    )
    manifest = {
        "format_version": "0.4.0",
        "fabric_name": "tdx",
        "fabric_version": inventory["release"],
        "crs": "EPSG:4326",
        "has_up_area": False,
        "topology": "tree",
        "bbox": overall,
        "unit_count": counts["catchments"],
        "created_at": datetime.now(UTC).isoformat(),
        "adapter_version": "tdx-original-1",
        "region": ",".join(basins),
        "catchments": "catchments.arrow",
        "lookup": "lookup.arrow",
        "directory": "lookup-directory.json",
        "index_batch_rows": 65536,
        "catchment_batch_bytes": 8388608,
        "auxiliary": [],
        "catchment_connectivity": [{"level": 0, "status": "not_supplied"}],
        "rivers": {
            "data": "rivers.arrow",
            "graph": "river-graph.parquet",
            "lookup": "river-lookup.arrow",
            "directory": "river-lookup-directory.json",
            "count": counts["rivers"],
            "topology": "tree",
            "batch_bytes": 8388608,
            "index_batch_rows": 65536,
        },
        "local_associations": {
            "data": "local-associations.parquet",
            "river_column": "river_id",
            "catchment_column": "catchment_id",
        },
        "artifacts": {path.name: fingerprint(path) for path in output.iterdir() if path.is_file()},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    produce(args.inventory, args.output)


if __name__ == "__main__":
    main()
