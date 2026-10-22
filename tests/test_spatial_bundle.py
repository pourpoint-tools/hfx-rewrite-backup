"""Production bundle retains source declarations without retaining duplicate vectors."""

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from hfx.candidates import fingerprint
from tests.test_data_interface_relationships import _source


def normalized_source(path: Path) -> str:
    _source(path)
    for name in ("catchments.arrow", "rivers.arrow", "river-nodes.arrow"):
        table = ipc.open_file(str(path / name)).read_all()
        count = table.num_rows
        table = table.append_column("level", pa.array([0] * count, pa.int16()))
        bounds = pa.struct([pa.field(n, pa.float32(), False) for n in ("xmin", "ymin", "xmax", "ymax")])
        table = table.append_column(
            pa.field("bbox", bounds, False),
            pa.array([{"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0}] * count, bounds),
        )
        import struct

        table = table.append_column(
            pa.field("geometry", pa.binary(), False), pa.array([struct.pack("<BIdd", 1, 1, 0.0, 0.0)] * count)
        )
        with ipc.new_file(str(path / name), table.schema) as writer:
            writer.write_table(table, max_chunksize=2)
    manifest = json.loads((path / "manifest.json").read_text())
    manifest.update(
        format_version="0.4.0",
        fabric_name="grit",
        crs="EPSG:4326",
        rivers={"data": "rivers.arrow", "graph": "river-graph.parquet", "topology": "dag"},
        auxiliary=[{"retained": "exact declaration"}],
        external_artifacts={"raster": {"url": "https://example.test/unchanged.tif", "retention": "unchanged"}},
    )
    (path / "NOTICE").write_text("GRIT CC BY-NC 4.0 attribution")
    manifest["artifacts"] = {p.name: fingerprint(p) for p in path.iterdir() if p.name != "manifest.json"}
    (path / "manifest.json").write_text(json.dumps(manifest))
    return hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()


def test_bundle_preserves_rasters_and_provenance_and_verifies_every_domain(tmp_path: Path) -> None:
    from hfx.spatial_bundle import build, verify

    source, output = tmp_path / "source", tmp_path / "output"
    digest = normalized_source(source)
    build(source, output, source_manifest_sha256=digest, rows=2)
    manifest = json.loads((output / "manifest.json").read_text())
    original = json.loads((source / "manifest.json").read_text())
    assert manifest["representation"] == "spatial-geoparquet-adjacency"
    assert manifest["source_domain_metadata"]["rivers"] == {"topology": "dag"}
    assert manifest["auxiliary"] == original["auxiliary"]
    assert manifest["external_artifacts"] == original["external_artifacts"]
    assert (output / "source-manifest.json").read_bytes() == (source / "manifest.json").read_bytes()
    assert set(manifest["families"]) == {"catchments", "rivers", "river_nodes"}
    assert not any(
        name.endswith(".arrow") and "lookup" not in name and "relationships" not in name
        for name in manifest["artifacts"]
    )
    assert verify(source, output, source_manifest_sha256=digest)["status"] == "passed"
    manifest["auxiliary"] = []
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="source declarations"):
        verify(source, output, source_manifest_sha256=digest)


def test_build_rejects_untrusted_input_before_output(tmp_path: Path) -> None:
    from hfx.spatial_bundle import build

    source = tmp_path / "source"
    normalized_source(source)
    with pytest.raises(ValueError, match="manifest"):
        build(source, tmp_path / "output", source_manifest_sha256="0" * 64)
    assert not (tmp_path / "output").exists()


def test_verifier_rejects_rebound_provenance(tmp_path: Path) -> None:
    from hfx.spatial_bundle import build, verify

    source, output = tmp_path / "source", tmp_path / "output"
    digest = normalized_source(source)
    build(source, output, source_manifest_sha256=digest, rows=2)
    manifest = json.loads((output / "manifest.json").read_text())
    (output / "NOTICE").write_text("different attribution")
    manifest["artifacts"]["NOTICE"] = fingerprint(output / "NOTICE")
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="provenance"):
        verify(source, output, source_manifest_sha256=digest)


def test_verifier_rejects_changed_address_semantics(tmp_path: Path) -> None:
    from hfx.spatial_bundle import build, verify

    source, output = tmp_path / "source", tmp_path / "output"
    digest = normalized_source(source)
    build(source, output, source_manifest_sha256=digest, rows=2)
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["addressing"]["block"] = "IPC batch"
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="address"):
        verify(source, output, source_manifest_sha256=digest)


def node_free_source(path: Path) -> str:
    import pyarrow.parquet as pq

    normalized_source(path)
    for name in ("catchments.arrow", "rivers.arrow"):
        table = ipc.open_file(str(path / name)).read_all()
        table = table.drop([n for n in table.column_names if n.endswith("_id")])
        for column in (
            ["parent_id"]
            if name == "catchments.arrow"
            else ["parent_id", "component_catchment_id", "upstream_node_id", "downstream_node_id"]
        ):
            table = table.append_column(column, pa.nulls(table.num_rows, pa.int64()))
        with ipc.new_file(str(path / name), table.schema) as writer:
            writer.write_table(table)
    (path / "river-nodes.arrow").unlink()
    (path / "graph.parquet").unlink()
    pq.write_table(
        pa.table({"river_id": pa.array([10, 10, 20], pa.int64()), "catchment_id": pa.array([10, 40, 20], pa.int64())}),
        path / "local-associations.parquet",
    )
    manifest = json.loads((path / "manifest.json").read_text())
    manifest.update(
        fabric_name="tdx",
        catchments="catchments.arrow",
        rivers={"data": "rivers.arrow", "graph": "river-graph.parquet", "topology": "tree"},
        catchment_connectivity=[{"level": 0, "status": "not_supplied"}],
        auxiliary=[],
        external_artifacts={},
        local_associations={
            "data": "local-associations.parquet",
            "river_column": "river_id",
            "catchment_column": "catchment_id",
        },
    )
    manifest.pop("river_nodes", None)
    manifest.pop("graph", None)
    manifest["artifacts"] = {p.name: fingerprint(p) for p in path.iterdir() if p.name != "manifest.json"}
    (path / "manifest.json").write_text(json.dumps(manifest))
    return hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()


def test_node_free_bundle_preserves_plural_and_absent_local_associations(tmp_path: Path) -> None:
    from hfx.spatial_bundle import build, verify
    from tests.test_data_interface_relationships import _records

    source, output = tmp_path / "source", tmp_path / "output"
    digest = node_free_source(source)
    manifest = build(source, output, source_manifest_sha256=digest, rows=2)
    assert set(manifest["families"]) == {"catchments", "rivers"}
    assert set(manifest["relationships"]["catchments"]["columns"]) == {"local_river_ids"}
    rivers = _records(output, manifest["relationships"]["rivers"])
    catchments = _records(output, manifest["relationships"]["catchments"])
    assert rivers[10]["local_catchment_ids"] == [10, 40]
    assert rivers[900]["local_catchment_ids"] == []
    assert catchments[40]["local_river_ids"] == [10]
    assert catchments[70]["local_river_ids"] == []
    assert rivers[10]["downstream_ids"] == [20, 40]
    assert "local_associations" not in manifest
    assert verify(source, output, source_manifest_sha256=digest)["status"] == "passed"


@pytest.mark.parametrize("values", [[10, None, 20, 10, 40], [None] * 5])
def test_plural_associations_reject_ambiguous_scalar(tmp_path: Path, values: list[int | None]) -> None:
    from hfx.spatial_bundle import build

    source = tmp_path / "source"
    node_free_source(source)
    path = source / "rivers.arrow"
    table = ipc.open_file(str(path)).read_all().append_column("local_catchment_id", pa.array(values, pa.int64()))
    with ipc.new_file(str(path), table.schema) as writer:
        writer.write_table(table)
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["artifacts"][path.name] = fingerprint(path)
    (source / "manifest.json").write_text(json.dumps(manifest))
    digest = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="scalar"):
        build(source, tmp_path / "output", source_manifest_sha256=digest)


@pytest.mark.parametrize("mutation", ["fractional", "duplicate", "unresolved"])
def test_invalid_local_association_edges_are_rejected(tmp_path: Path, mutation: str) -> None:
    import pyarrow.parquet as pq

    from hfx.spatial_bundle import build

    source = tmp_path / "source"
    node_free_source(source)
    values = (
        [10.5, 40.0, 20.0] if mutation == "fractional" else ([10, 10, 20] if mutation == "duplicate" else [10, 999, 20])
    )
    path = source / "local-associations.parquet"
    pq.write_table(pa.table({"river_id": pa.array([10, 10, 20], pa.int64()), "catchment_id": values}), path)
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["artifacts"][path.name] = fingerprint(path)
    (source / "manifest.json").write_text(json.dumps(manifest))
    digest = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="int64|Duplicate|Unresolved"):
        build(source, tmp_path / "output", source_manifest_sha256=digest)


def test_plural_reverse_edges_and_bindings_are_independently_verified(tmp_path: Path) -> None:
    from hfx.spatial_bundle import build, verify

    source, output = tmp_path / "source", tmp_path / "output"
    digest = node_free_source(source)
    manifest = build(source, output, source_manifest_sha256=digest, rows=2)
    declaration = manifest["relationships"]["catchments"]
    binding = declaration["columns"]["local_river_ids"]
    binding["source_column"] = "river_id"
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="source binding"):
        verify(source, output, source_manifest_sha256=digest)
    binding["source_column"] = "catchment_id"
    path = output / declaration["data"]
    table = ipc.open_file(str(path)).read_all()
    index = table.schema.get_field_index("local_river_ids")
    table = table.set_column(
        index, table.schema.field(index), pa.array([[10], [20], [20], [], []], pa.list_(pa.int64()))
    )
    with ipc.new_file(str(path), table.schema) as writer:
        writer.write_table(table, max_chunksize=2)
    manifest["artifacts"][path.name] = fingerprint(path)
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="local_river_ids differs from source"):
        verify(source, output, source_manifest_sha256=digest)
