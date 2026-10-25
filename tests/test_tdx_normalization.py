"""TDX source mapping expectations use independently defined source values."""

import struct

import pyarrow as pa
import pytest

from scripts.produce_tdx import normalized_batch


def test_distinct_polygons_native_fields_and_no_invented_outlets() -> None:
    polygon = struct.pack("<BIII10d", 1, 3, 1, 5, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0)
    source = pa.record_batch(
        {
            "fid": pa.array([7, 8], type=pa.int64()),
            "geom": [polygon, polygon],
            "streamID": pa.array([42, 42], type=pa.int64()),
        }
    )
    result = normalized_batch(source, "catchments", "7020000010", first_id=101)
    assert result["id"].to_pylist() == [101, 102]
    assert result["source_id"].to_pylist() == ["7", "8"]
    assert result["streamID"].to_pylist() == [42, 42]
    assert result["geometry"].to_pylist() == [polygon, polygon]
    assert result["parent_id"].to_pylist() == [None, None]
    assert result["outlet_lon"].to_pylist() == [None, None]
    assert result["up_area_km2"].to_pylist() == [None, None]
    assert result["area_km2"][0].as_py() == pytest.approx(12308.778, abs=0.01)
    assert result["bbox"][0].as_py() == {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0}


def test_zero_length_river_preserved_without_orientation_or_terminal_inference() -> None:
    line = struct.pack("<BII4d", 1, 2, 2, 3, 4, 3, 4)
    source = pa.record_batch(
        {
            "fid": [1],
            "geom": [line],
            "LINKNO": pa.array([42], type=pa.int32()),
            "DSLINKNO": pa.array([-1], type=pa.int32()),
        }
    )
    result = normalized_batch(source, "rivers", "7020000010", first_id=1)
    assert result["geometry"].to_pylist() == [line]
    assert result["geometry_orientation"].to_pylist() == [0]
    assert "local_catchment_id" not in result.schema.names
    assert result["DSLINKNO"].to_pylist() == [-1]


@pytest.mark.parametrize("x", [181, float("inf"), float("nan")])
def test_bad_coordinate_fails_without_clamp(x: float) -> None:
    line = struct.pack("<BII4d", 1, 2, 2, 3, 4, x, 4)
    source = pa.record_batch({"fid": [1], "geom": [line], "LINKNO": pa.array([42], type=pa.int32())})
    with pytest.raises(ValueError, match="coordinate"):
        normalized_batch(source, "rivers", "7020000010", first_id=1)


def test_complete_native_edges_and_plural_associations() -> None:
    from scripts.produce_tdx import source_relationships

    rivers = [(10, 9, 42, -1, -1), (11, 42, 70, 9, -1), (12, 70, -1, 42, -1)]
    polygons = [(101, 9), (102, 9), (103, 70)]
    flow, associations = source_relationships(rivers, polygons)
    assert flow == {10: [], 11: [10], 12: [11]}
    assert associations == [(10, 101), (10, 102), (12, 103)]


def test_conflicting_supplied_connectivity_is_not_resolved_by_preference() -> None:
    from scripts.produce_tdx import source_relationships

    with pytest.raises(ValueError, match="upstream.*downstream"):
        source_relationships([(10, 9, 42, -1, -1), (11, 42, -1, -1, -1)], [])


def test_cycle_is_rejected_without_removing_edges() -> None:
    from scripts.produce_tdx import source_relationships

    with pytest.raises(ValueError, match="cycle"):
        source_relationships([(10, 9, 42, 42, -1), (11, 42, 9, 9, -1)], [])


def test_hole_area_is_subtracted_even_when_ring_orientation_matches_exterior() -> None:
    # Both rings counterclockwise; source order is preserved, not rewritten.
    exterior = (0, 0, 2, 0, 2, 2, 0, 2, 0, 0)
    hole = (0.5, 0.5, 1.5, 0.5, 1.5, 1.5, 0.5, 1.5, 0.5, 0.5)
    polygon = struct.pack("<BII", 1, 3, 2) + struct.pack("<I10d", 5, *exterior) + struct.pack("<I10d", 5, *hole)
    source = pa.record_batch({"fid": [1], "geom": [polygon], "streamID": [42]})
    result = normalized_batch(source, "catchments", "7020000010", first_id=1)
    # Independently tabulated WGS84 geodesic square areas: 49231.584297 - 12307.409724 km².
    assert result["area_km2"][0].as_py() == pytest.approx(36924.174573, abs=0.01)
    assert result["geometry"][0].as_py() == polygon


@pytest.mark.parametrize(
    "source_type,values",
    [
        (pa.int32(), [-2147483648, 2147483647, None]),
        (pa.int64(), [-9223372036854775808, 9223372036854775807, None]),
    ],
)
def test_stream_id_widening_preserves_values_and_nulls(source_type: pa.DataType, values: list[int | None]) -> None:
    polygon = struct.pack("<BIII10d", 1, 3, 1, 5, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0)
    source = pa.record_batch(
        {
            "fid": [1, 2, 3],
            "geom": [polygon] * 3,
            "streamID": pa.array(values, type=source_type),
        }
    )
    result = normalized_batch(source, "catchments", "10", first_id=1)
    assert result.schema.field("streamID").type == pa.int64()
    assert result["streamID"].to_pylist() == values


def test_stream_id_mapping_does_not_authorize_float_conversion() -> None:
    polygon = struct.pack("<BIII10d", 1, 3, 1, 5, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0)
    source = pa.record_batch({"fid": [1], "geom": [polygon], "streamID": [9.5]})
    with pytest.raises(ValueError, match="streamID.*integer"):
        normalized_batch(source, "catchments", "10", first_id=1)
