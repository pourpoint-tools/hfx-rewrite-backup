"""Production bundle retains source declarations without retaining duplicate vectors."""

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from hfx.candidates import fingerprint
from tests.relationship_fixtures import _source


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
    from tests.relationship_fixtures import _records

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


def test_missing_local_association_declaration_is_not_empty_evidence(tmp_path: Path) -> None:
    from hfx.spatial_bundle import build

    source = tmp_path / "source"
    node_free_source(source)
    manifest = json.loads((source / "manifest.json").read_text())
    del manifest["local_associations"]
    (source / "manifest.json").write_text(json.dumps(manifest))
    digest = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Local association evidence"):
        build(source, tmp_path / "output", source_manifest_sha256=digest)


def test_explicit_empty_local_associations_are_valid(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    from hfx.spatial_bundle import build, verify
    from tests.relationship_fixtures import _records

    source, output = tmp_path / "source", tmp_path / "output"
    node_free_source(source)
    path = source / "local-associations.parquet"
    pq.write_table(pa.table({"river_id": pa.array([], pa.int64()), "catchment_id": pa.array([], pa.int64())}), path)
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["artifacts"][path.name] = fingerprint(path)
    (source / "manifest.json").write_text(json.dumps(manifest))
    digest = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    final = build(source, output, source_manifest_sha256=digest)
    assert all(row["local_catchment_ids"] == [] for row in _records(output, final["relationships"]["rivers"]).values())
    assert verify(source, output, source_manifest_sha256=digest)["status"] == "passed"


def local_raster_source(path: Path) -> str:
    """A readable native-grid GRASS D8 pair, independent of conversion."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    normalized_source(path)
    manifest = json.loads((path / "manifest.json").read_text())
    artifacts = {"flow_dir": "aux/d8/flow_dir.tif", "flow_acc": "aux/d8/flow_acc.tif"}
    for role, name in artifacts.items():
        raster = path / name
        raster.parent.mkdir(parents=True, exist_ok=True)
        direction = role == "flow_dir"
        values = np.zeros((32, 32), dtype="uint8" if direction else "float32")
        with rasterio.open(
            raster,
            "w",
            driver="GTiff",
            width=32,
            height=32,
            count=1,
            dtype=values.dtype,
            crs="EPSG:4326",
            transform=from_origin(0, 1, 1 / 32, 1 / 32),
            nodata=255 if direction else -9999,
            tiled=True,
            blockxsize=16,
            blockysize=16,
        ) as dataset:
            dataset.write(values, 1)
        with rasterio.open(raster) as dataset:
            np.testing.assert_array_equal(dataset.read(1), values)
            assert dataset.crs.to_epsg() == 4326
            assert dataset.block_shapes == [(16, 16)]
            assert dataset.nodata == (255 if direction else -9999)
        manifest["artifacts"][name] = fingerprint(raster)
    manifest["auxiliary"] = [
        {
            "schema": "hfx.aux.d8_raster.v2",
            "artifacts": artifacts,
            "metadata": {"crs": "EPSG:4326", "flow_dir_encoding": "grass", "flow_acc_units": "cells"},
        }
    ]
    (path / "manifest.json").write_text(json.dumps(manifest))
    return hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()


def test_local_raster_pair_is_preserved_and_verified(tmp_path: Path) -> None:
    from hfx.spatial_bundle import build, verify

    source, output = tmp_path / "source", tmp_path / "output"
    digest = local_raster_source(source)
    manifest = build(source, output, source_manifest_sha256=digest, rows=2)
    # Verify first: the original implementation incorrectly accepts the omission.
    assert verify(source, output, source_manifest_sha256=digest)["status"] == "passed"
    original = json.loads((source / "manifest.json").read_text())
    assert manifest["auxiliary"] == original["auxiliary"]
    for name in original["auxiliary"][0]["artifacts"].values():
        assert (output / name).is_file(), f"accepted dangling local raster: {name}"
        assert (output / name).read_bytes() == (source / name).read_bytes()
        assert manifest["artifacts"][name] == original["artifacts"][name]


@pytest.mark.parametrize("mutation", ["file", "identity", "both", "rebound"])
def test_verifier_checks_local_raster_references_independently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    from hfx import spatial_bundle

    source, output = tmp_path / "source", tmp_path / "output"
    digest = local_raster_source(source)
    manifest = spatial_bundle.build(source, output, source_manifest_sha256=digest, rows=2)
    name = "aux/d8/flow_dir.tif"
    if mutation in {"file", "both"}:
        (output / name).unlink()
    if mutation in {"identity", "both"}:
        del manifest["artifacts"][name]
    if mutation == "rebound":
        (output / name).write_bytes(b"different raster")
        manifest["artifacts"][name] = fingerprint(output / name)
    (output / "manifest.json").write_text(json.dumps(manifest))
    # Recreate the shared-filter omission: references must be checked independently.
    provenance = spatial_bundle._provenance
    monkeypatch.setattr(
        spatial_bundle,
        "_provenance",
        lambda original: {key: value for key, value in provenance(original).items() if key != name},
    )
    with pytest.raises(ValueError, match="local raster"):
        spatial_bundle.verify(source, output, source_manifest_sha256=digest)


@pytest.mark.parametrize("mutation", ["file", "identity", "mismatch", "escape"])
def test_build_checks_local_rasters_before_output(tmp_path: Path, mutation: str) -> None:
    from hfx.spatial_bundle import build

    source, output = tmp_path / "source", tmp_path / "output"
    local_raster_source(source)
    manifest = json.loads((source / "manifest.json").read_text())
    name = "aux/d8/flow_dir.tif"
    if mutation == "file":
        (source / name).unlink()
    elif mutation == "identity":
        del manifest["artifacts"][name]
    elif mutation == "mismatch":
        (source / name).write_bytes(b"different raster")
    else:
        manifest["auxiliary"][0]["artifacts"]["flow_dir"] = "../escape.tif"
    (source / "manifest.json").write_text(json.dumps(manifest))
    digest = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="local raster|escapes bundle"):
        build(source, output, source_manifest_sha256=digest)
    assert not output.exists()


def test_external_raster_reference_is_retained_without_local_file(tmp_path: Path) -> None:
    from hfx.spatial_bundle import build, verify

    source, output = tmp_path / "source", tmp_path / "output"
    local_raster_source(source)
    manifest = json.loads((source / "manifest.json").read_text())
    for role, name in list(manifest["auxiliary"][0]["artifacts"].items()):
        manifest["external_artifacts"][role] = {
            **manifest["artifacts"].pop(name),
            "url": f"https://example.test/{name}",
            "retention": "Publisher retains the exact object for the bundle lifetime.",
        }
        manifest["auxiliary"][0]["artifacts"][role] = {"external": role}
        (source / name).unlink()
    (source / "manifest.json").write_text(json.dumps(manifest))
    digest = hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()
    final = build(source, output, source_manifest_sha256=digest)
    assert final["auxiliary"] == manifest["auxiliary"]
    assert final["external_artifacts"] == manifest["external_artifacts"]
    assert verify(source, output, source_manifest_sha256=digest)["status"] == "passed"
