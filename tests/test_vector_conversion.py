"""Released vector production preserves source information without raster copies."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest

from scripts.convert_vector import convert


def test_vector_manifest_and_unchanged_links(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "aux").mkdir()
    metadata = {
        "format_version": "0.3.0",
        "unit_count": 3,
        "crs": "EPSG:4326",
        "topology": "dag",
        "fabric_name": "grit",
        "auxiliary": [
            {
                "schema": "hfx.aux.snap.v2",
                "artifacts": {"snap": "aux/snap.parquet"},
                "metadata": {"references_levels": [0]},
            },
            {"schema": "hfx.aux.d8_raster.v2", "artifacts": {"flow_dir": "missing.tif"}},
        ],
    }
    (source / "manifest.json").write_text(json.dumps(metadata))
    for name in ["graph.parquet", "aux/snap.parquet", "NOTICE", "CITATION.txt", "README.md"]:
        (source / name).write_bytes(name.encode())
    table = pa.table(
        {"id": pa.array([90, 2, 700], type=pa.int64()), "geometry": [b"a", b"bb", b"ccc"], "extra": [None, "yes", "no"]}
    )
    pq.write_table(table, source / "catchments.parquet")
    output = tmp_path / "output"
    convert(source, output)
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["format_version"] == "0.4.0"
    assert "candidate" not in manifest and "experimental" not in manifest
    assert manifest["auxiliary"] == metadata["auxiliary"][:1]
    assert manifest["graph"] == "graph.parquet"
    assert (output / "graph.parquet").stat().st_ino == (source / "graph.parquet").stat().st_ino
    assert (output / "source-README.md").read_bytes() == b"README.md"
    with ipc.open_file(str(output / "catchments.arrow")) as reader:
        assert reader.read_all().equals(table)
    with ipc.open_file(str(output / "lookup.arrow")) as reader:
        assert reader.schema.metadata[b"hfx:format_version"] == b"0.4.0"
        assert b"hfx:candidate" not in reader.schema.metadata
        assert reader.read_all()["id"].to_pylist() == [2, 90, 700]
    with pytest.raises(FileExistsError):
        convert(source, output)
