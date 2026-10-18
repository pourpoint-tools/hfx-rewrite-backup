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
        rivers={"data": "rivers.arrow", "topology": "dag"},
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
