"""Independent verification catches coherent but incorrect vector bundles."""

import json
from pathlib import Path
from typing import Literal

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest

from hfx.verify_candidates import _fingerprint
from scripts import verify_vector


def test_nonmaximal_catchment_batch_is_rejected(tmp_path: Path) -> None:
    table = pa.table({"id": pa.array([90, 2, 700], type=pa.int64()), "geometry": [b"a", b"bb", b"ccc"]})
    source = tmp_path / "source.parquet"
    output = tmp_path / "catchments.arrow"
    pq.write_table(table, source)
    with ipc.new_file(str(output), table.schema, options=ipc.IpcWriteOptions(compression="zstd")) as writer:
        for batch in table.to_batches(max_chunksize=1):
            writer.write_batch(batch)
    with pytest.raises(ValueError, match="maximal"):
        verify_vector._catchments(pq.ParquetFile(source), output)


@pytest.mark.parametrize("change", ["values", "schema", "missing", "extra", "boundary"])
def test_catchment_source_corruption(tmp_path: Path, change: str) -> None:
    table = pa.table({"id": pa.array(range(1, 4100), type=pa.int64()), "geometry": [b"wkb"] * 4099})
    source = tmp_path / "source.parquet"
    output = tmp_path / "catchments.arrow"
    pq.write_table(table, source)
    changed = table
    if change == "values":
        changed = table.set_column(1, "geometry", pa.array([None] + [b"wkb"] * 4098, type=pa.binary()))
    elif change == "schema":
        changed = table.replace_schema_metadata({b"geo": b"wrong"})
    elif change == "missing":
        changed = table.slice(0, 4098)
    elif change == "extra":
        changed = pa.concat_tables([table, table.slice(0, 1)])
    with ipc.new_file(str(output), changed.schema, options=ipc.IpcWriteOptions(compression="zstd")) as writer:
        for batch in changed.to_batches(max_chunksize=4099 if change == "boundary" else 4096):
            writer.write_batch(batch)
    with pytest.raises(ValueError):
        verify_vector._catchments(pq.ParquetFile(source), output)


def test_exact_boundaries_nulls_schema_and_oversized_row(tmp_path: Path) -> None:
    schema = pa.schema(
        [
            pa.field("id", pa.int64(), nullable=False),
            pa.field("geometry", pa.binary()),
            pa.field("name", pa.string()),
        ],
        metadata={b"geo": b"preserved source metadata"},
    )
    table = pa.Table.from_arrays(
        [
            pa.array(range(1, 4098), type=pa.int64()),
            pa.array([b"x" * 8388609] + [None] * 4096, type=pa.binary()),
            pa.array([None] + ["name"] * 4096),
        ],
        schema=schema,
    )
    source = tmp_path / "source.parquet"
    output = tmp_path / "catchments.arrow"
    pq.write_table(table, source)
    with ipc.new_file(str(output), schema, options=ipc.IpcWriteOptions(compression="zstd")) as writer:
        # One oversize row, rest of the 4096-row source batch, final source batch.
        for offset, size in [(0, 1), (1, 4095), (4096, 1)]:
            writer.write_batch(table.slice(offset, size).to_batches()[0])
    ids, offsets = verify_vector._catchments(pq.ParquetFile(source), output)
    assert list(ids) == list(range(1, 4098))
    assert offsets == [0, 1, 4096, 4097]


@pytest.fixture
def bundle(tmp_path: Path) -> tuple[Path, Path]:
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    metadata = {
        "format_version": "0.3.0",
        "unit_count": 3,
        "crs": "EPSG:4326",
        "topology": "dag",
        "auxiliary": [
            {"schema": "hfx.aux.snap.v2", "artifacts": {"snap": "aux/snap.parquet"}, "metadata": {"name": "snap"}},
            {"schema": "hfx.aux.d8_raster.v2", "artifacts": {"flow_dir": "aux/flow.tif"}},
        ],
    }
    (source / "manifest.json").write_text(json.dumps(metadata))
    for name in ["graph.parquet", "aux/snap.parquet", "NOTICE", "CITATION.txt", "README.md"]:
        path = source / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("original " + name)
    table = pa.table({"id": pa.array([90, 2, 700], type=pa.int64()), "geometry": [b"a", None, b"ccc"]})
    pq.write_table(table, source / "catchments.parquet")
    for name in ["manifest.json", "graph.parquet", "aux/snap.parquet", "NOTICE", "CITATION.txt", "README.md"]:
        target = output / {"manifest.json": "source-manifest.json", "README.md": "source-README.md"}.get(name, name)
        target.parent.mkdir(exist_ok=True)
        target.write_bytes((source / name).read_bytes())
    (output / "README.md").write_text("generated delivery notes")
    with ipc.new_file(
        str(output / "catchments.arrow"), table.schema, options=ipc.IpcWriteOptions(compression="zstd")
    ) as writer:
        writer.write_batch(table.to_batches()[0])
    schema = pa.schema(
        [
            pa.field("id", pa.int64(), nullable=False),
            pa.field("block", pa.int32(), nullable=False),
            pa.field("row", pa.int32(), nullable=False),
        ],
        metadata={
            b"hfx:format_version": b"0.4.0",
            b"hfx:catchments_sha256": _fingerprint(output / "catchments.arrow")["sha256"].encode(),
        },
    )
    index = pa.RecordBatch.from_arrays(
        [pa.array([2, 90, 700]), pa.array([0, 0, 0], type=pa.int32()), pa.array([1, 0, 2], type=pa.int32())],
        schema=schema,
    )
    with ipc.new_file(str(output / "lookup.arrow"), schema) as writer:
        writer.write_batch(index)
    (output / "lookup-directory.json").write_text(
        json.dumps({"version": 1, "batches": [{"batch": 0, "min_id": 2, "max_id": 700, "rows": 3}]})
    )
    metadata.update(
        {
            "format_version": "0.4.0",
            "graph": "graph.parquet",
            "catchments": "catchments.arrow",
            "lookup": "lookup.arrow",
            "directory": "lookup-directory.json",
            "source_manifest": "source-manifest.json",
            "index_batch_rows": 65536,
            "catchment_batch_bytes": 8388608,
        }
    )
    metadata["auxiliary"] = metadata["auxiliary"][:1]
    (output / "manifest.json").write_text(json.dumps(metadata))
    rehash(output)
    return source, output


def rehash(output: Path) -> None:
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["artifacts"] = {
        path.relative_to(output).as_posix(): _fingerprint(path)
        for path in output.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    (output / "manifest.json").write_text(json.dumps(manifest))


def test_complete_release_and_report_safety(bundle: tuple[Path, Path], tmp_path: Path) -> None:
    source, output = bundle
    report = tmp_path / "receipt.json"
    result = verify_vector.verify(source, output, report)
    assert result["status"] == "passed"
    assert result["source_rows"] == 3
    assert result["verified_index_rows"] == 3
    assert json.loads(report.read_text()) == result
    with pytest.raises(FileExistsError):
        verify_vector.verify(source, output, report)
    with pytest.raises(ValueError, match="outside"):
        verify_vector.verify(source, output, output / "receipt.json")


@pytest.mark.parametrize(
    "change", ["metadata", "copied", "coverage", "directory", "address", "binding", "fingerprint", "count"]
)
def test_release_corruption(bundle: tuple[Path, Path], tmp_path: Path, change: str) -> None:
    source, output = bundle
    if change in {"metadata", "count"}:
        manifest = json.loads((output / "manifest.json").read_text())
        manifest["crs" if change == "metadata" else "unit_count"] = "wrong"
        (output / "manifest.json").write_text(json.dumps(manifest))
    elif change == "copied":
        (output / "NOTICE").write_text("changed")
    elif change == "coverage":
        (output / "unknown.txt").write_text("unexpected")
    elif change == "directory":
        directory = json.loads((output / "lookup-directory.json").read_text())
        directory["batches"][0]["max_id"] = 701
        (output / "lookup-directory.json").write_text(json.dumps(directory))
    elif change in {"address", "binding"}:
        with ipc.open_file(str(output / "lookup.arrow")) as reader:
            table = reader.read_all()
        if change == "address":
            table = table.set_column(2, table.schema.field(2), pa.array([0, 1, 2], type=pa.int32()))
        else:
            table = table.replace_schema_metadata({b"hfx:format_version": b"0.4.0", b"hfx:catchments_sha256": b"wrong"})
        with ipc.new_file(str(output / "lookup.arrow"), table.schema) as writer:
            writer.write_table(table)
    else:
        (output / "NOTICE").write_text("unhashed mutation")
    if change != "fingerprint":
        rehash(output)
    with pytest.raises(ValueError):
        verify_vector.verify(source, output, tmp_path / "receipt.json")
    assert not (tmp_path / "receipt.json").exists()


@pytest.mark.parametrize("ids", [[1, 1, 2], [0, 2, 3], [None, 2, 3]])
def test_invalid_source_identity(bundle: tuple[Path, Path], tmp_path: Path, ids: list[int | None]) -> None:
    source, output = bundle
    table = pa.table({"id": pa.array(ids, type=pa.int64()), "geometry": [b"a", None, b"ccc"]})
    pq.write_table(table, source / "catchments.parquet")
    with ipc.new_file(
        str(output / "catchments.arrow"), table.schema, options=ipc.IpcWriteOptions(compression="zstd")
    ) as writer:
        writer.write_table(table)
    with ipc.open_file(str(output / "lookup.arrow")) as reader:
        index = reader.read_all()
    index = index.replace_schema_metadata(
        {
            b"hfx:format_version": b"0.4.0",
            b"hfx:catchments_sha256": _fingerprint(output / "catchments.arrow")["sha256"].encode(),
        }
    )
    with ipc.new_file(str(output / "lookup.arrow"), index.schema) as writer:
        writer.write_table(index)
    rehash(output)
    with pytest.raises(ValueError):
        verify_vector.verify(source, output, tmp_path / "receipt.json")


def test_source_unit_count_is_checked(bundle: tuple[Path, Path], tmp_path: Path) -> None:
    source, output = bundle
    for path in (source / "manifest.json", output / "source-manifest.json", output / "manifest.json"):
        metadata = json.loads(path.read_text())
        metadata["unit_count"] = 4
        path.write_text(json.dumps(metadata))
    rehash(output)
    with pytest.raises(ValueError, match="unit count"):
        verify_vector.verify(source, output, tmp_path / "receipt.json")


@pytest.mark.parametrize(
    "artifact,codec",
    [("catchments.arrow", None), ("catchments.arrow", "lz4"), ("lookup.arrow", "zstd"), ("lookup.arrow", "lz4")],
)
def test_physical_compression_is_required(
    bundle: tuple[Path, Path], tmp_path: Path, artifact: str, codec: Literal["lz4", "zstd"] | None
) -> None:
    source, output = bundle
    with ipc.open_file(str(output / artifact)) as reader:
        table = reader.read_all()
    with ipc.new_file(str(output / artifact), table.schema, options=ipc.IpcWriteOptions(compression=codec)) as writer:
        writer.write_table(table)
    # Keep hashes and lookup binding coherent so only physical compression fails.
    with ipc.open_file(str(output / "lookup.arrow")) as reader:
        index = reader.read_all()
    index = index.replace_schema_metadata(
        {
            b"hfx:format_version": b"0.4.0",
            b"hfx:catchments_sha256": _fingerprint(output / "catchments.arrow")["sha256"].encode(),
        }
    )
    with ipc.new_file(
        str(output / "lookup.arrow"),
        index.schema,
        options=ipc.IpcWriteOptions(compression=codec if artifact == "lookup.arrow" else None),
    ) as writer:
        writer.write_table(index)
    rehash(output)
    with pytest.raises(ValueError, match="compression"):
        verify_vector.verify(source, output, tmp_path / "receipt.json")


@pytest.mark.parametrize("codec", [None, "zstd"])
def test_compression_inspection_includes_dictionary_batches(
    tmp_path: Path, codec: Literal["lz4", "zstd"] | None
) -> None:
    path = tmp_path / "dictionary.arrow"
    table = pa.table({"label": pa.array(["one", "two", None, "one"]).dictionary_encode()})
    with ipc.new_file(str(path), table.schema, options=ipc.IpcWriteOptions(compression=codec)) as writer:
        writer.write_table(table, max_chunksize=2)
    verify_vector._ipc_compression(path, compressed=codec == "zstd")
    with pytest.raises(ValueError, match="compression"):
        verify_vector._ipc_compression(path, compressed=codec != "zstd")
