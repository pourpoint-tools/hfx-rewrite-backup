"""Read original TDX GeoPackage values without geometry or hydrology repair."""

import sqlite3
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import pyarrow as pa


def _identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _wkb(value: bytes) -> bytes:
    # GeoPackage binary header (OGC 12-128r18 §2.1.3), not a geometry reserialization.
    if len(value) < 8 or value[:3] != b"GP\x00":
        raise ValueError("Invalid GeoPackage geometry header")
    flags = value[3]
    envelope = (flags >> 1) & 7
    if flags & 0xF0 or envelope not in (0, 1):
        raise ValueError("Unsupported empty, extended or dimensional GeoPackage geometry")
    srs = struct.unpack("<i" if flags & 1 else ">i", value[4:8])[0]
    offset = 8 + (32 if envelope else 0)
    if srs != 4326 or len(value) < offset + 5:
        raise ValueError("GeoPackage geometry CRS or payload differs")
    return value[offset:]


def read_layer(
    path: Path, domain: Literal["catchments", "rivers"], *, batch_rows: int = 4096
) -> Iterator[pa.RecordBatch]:
    """Yield fid-ordered native values and unchanged embedded WKB in bounded groups.

    Only observed original TDX declarations are supported. SQLite values are
    checked before Arrow conversion, not silently coerced. This reader does not
    certify topology, coordinate validity, source acquisition or global coverage.
    """
    if batch_rows <= 0:
        raise ValueError("batch_rows must be positive")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        layers = connection.execute(
            "SELECT table_name, srs_id FROM gpkg_contents WHERE data_type = 'features'"
        ).fetchall()
        if len(layers) != 1 or layers[0][1] != 4326:
            raise ValueError("Expected one EPSG:4326 original feature layer")
        layer = str(layers[0][0])
        if (domain == "catchments" and layer != "basins") or (
            domain == "rivers" and not layer.startswith("TDX_streamnet_")
        ):
            raise ValueError("Unexpected TDX source layer")
        geometry = connection.execute(
            "SELECT column_name, geometry_type_name, srs_id, z, m FROM gpkg_geometry_columns WHERE table_name = ?",
            (layer,),
        ).fetchall()
        allowed = {"GEOMETRY", "POLYGON", "MULTIPOLYGON"} if domain == "catchments" else {"LINESTRING"}
        if len(geometry) != 1 or geometry[0][1] not in allowed or tuple(geometry[0][2:]) != (4326, 0, 0):
            raise ValueError("Unsupported original geometry declaration")
        geom = str(geometry[0][0])
        declarations = connection.execute(f"PRAGMA table_info({_identifier(layer)})").fetchall()
        types = {"INTEGER": pa.int64(), "MEDIUMINT": pa.int32(), "REAL": pa.float64()}
        fields: list[pa.Field] = []
        for _, name, declared, nonnull, _, primary in declarations:
            if primary and (name != "fid" or declared != "INTEGER"):
                raise ValueError("Expected native fid INTEGER primary key")
            if name != geom and declared not in types:
                raise ValueError(f"Unsupported native declared type: {name} {declared}")
            fields.append(
                pa.field(
                    name,
                    pa.binary() if name == geom else types[declared],
                    nullable=not nonnull,
                    metadata={"gpkg:declared_type": declared},
                )
            )
        if not any(row[1] == "fid" and row[5] == 1 for row in declarations):
            raise ValueError("Missing native fid primary key")
        required = {"streamID"} if domain == "catchments" else {"LINKNO", "DSLINKNO"}
        if not required.issubset({field.name for field in fields}):
            raise ValueError("Missing TDX identity or association columns")
        schema = pa.schema(fields, metadata={"gpkg:layer": layer, "gpkg:geometry_column": geom})
        cursor = connection.execute(
            f"SELECT {', '.join(_identifier(field.name) for field in fields)} FROM {_identifier(layer)} ORDER BY fid"
        )
        while rows := cursor.fetchmany(batch_rows):
            columns: list[pa.Array] = []
            for index, field in enumerate(fields):
                values: list[object] = []
                for row in rows:
                    value = row[index]
                    expected = bytes if field.name == geom else float if pa.types.is_floating(field.type) else int
                    if value is None:
                        if not field.nullable or field.name == geom:
                            raise ValueError(f"{field.name}: unexpected null")
                    elif type(value) is not expected:
                        raise ValueError(f"{field.name}: unexpected SQLite storage type")
                    elif field.name == geom:
                        value = _wkb(value)
                    values.append(value)
                columns.append(pa.array(values, type=field.type))
            yield pa.RecordBatch.from_arrays(columns, schema=schema)
    finally:
        connection.close()
