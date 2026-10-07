"""Independent, small physical-layout examples for full candidate verification."""

import hashlib
import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq
import pytest

from hfx.verify_candidates import verify


def fingerprint(path: Path) -> dict[str, int | str]:
    data = path.read_bytes()
    return {
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "head_sha256": hashlib.sha256(data[:65536]).hexdigest(),
        "tail_sha256": hashlib.sha256(data[-65536:]).hexdigest(),
    }


def refresh(bundle: Path) -> None:
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["artifacts"] = {p.name: fingerprint(p) for p in bundle.iterdir() if p.name != "manifest.json"}
    (bundle / "manifest.json").write_text(json.dumps(manifest))


@pytest.fixture
def bundles(tmp_path: Path) -> tuple[Path, Path, Path]:
    source, a, b = (tmp_path / name for name in ("source", "a", "b"))
    source.mkdir()
    table = pa.table({"id": pa.array([30, 10, 20], type=pa.int64()), "value": ["a", None, "c"]})
    table = table.replace_schema_metadata({b"origin": b"fixture"})
    pq.write_table(table, source / "catchments.parquet", row_group_size=2)
    (source / "manifest.json").write_text('{"source": true}')
    (source / "network.bin").write_bytes(b"unchanged")
    for bundle, candidate, catchments, addresses in (
        (a, "a-index", "catchments.parquet", [(0, 1), (1, 0), (0, 0)]),
        (b, "b-arrow", "catchments.arrow", [(1, 0), (1, 1), (0, 0)]),
    ):
        bundle.mkdir()
        shutil.copyfile(source / "manifest.json", bundle / "source-manifest.json")
        shutil.copyfile(source / "network.bin", bundle / "network.bin")
        if bundle == a:
            shutil.copyfile(source / "catchments.parquet", bundle / catchments)
        else:
            with ipc.new_file(
                bundle / catchments, table.schema, options=ipc.IpcWriteOptions(compression="zstd")
            ) as writer:
                writer.write_table(table.slice(0, 1))
                writer.write_table(table.slice(1, 2))
        schema = pa.schema(
            [
                pa.field("id", pa.int64(), nullable=False),
                pa.field("block", pa.int32(), nullable=False),
                pa.field("row", pa.int32(), nullable=False),
            ],
            metadata={
                b"hfx:catchments_sha256": fingerprint(bundle / catchments)["sha256"].encode(),
                b"hfx:candidate": candidate.encode(),
            },
        )
        index = pa.Table.from_arrays(
            [
                pa.array([10, 20, 30], type=pa.int64()),
                pa.array([x[0] for x in addresses], type=pa.int32()),
                pa.array([x[1] for x in addresses], type=pa.int32()),
            ],
            schema=schema,
        )
        with ipc.new_file(bundle / "lookup.arrow", schema) as writer:
            writer.write_table(index, max_chunksize=2)
        (bundle / "lookup-directory.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "batches": [
                        {"batch": 0, "min_id": 10, "max_id": 20, "rows": 2},
                        {"batch": 1, "min_id": 30, "max_id": 30, "rows": 1},
                    ],
                }
            )
        )
        (bundle / "manifest.json").write_text(
            json.dumps(
                {
                    "format_version": "0.4.0",
                    "experimental": True,
                    "candidate": candidate,
                    "source_manifest": "source-manifest.json",
                    "catchments": catchments,
                    "lookup": "lookup.arrow",
                    "directory": "lookup-directory.json",
                    "index_batch_rows": 2,
                    "catchment_batch_bytes": 8388608,
                }
            )
        )
        refresh(bundle)
    return source, a, b


def test_full_verification(bundles: tuple[Path, Path, Path]) -> None:
    result = verify(*bundles)
    assert result["status"] == "passed"
    assert result["source_rows"] == 3
    assert (bundles[0].parent / "verification.json").is_file()


def test_changed_copy_rejected_even_with_updated_manifest(bundles: tuple[Path, Path, Path]) -> None:
    (bundles[1] / "network.bin").write_bytes(b"changed")
    refresh(bundles[1])
    with pytest.raises(ValueError, match="copied artifact"):
        verify(*bundles)


@pytest.mark.parametrize("damage", ["values", "schema", "address", "directory", "hash"])
def test_corruption_rejected(bundles: tuple[Path, Path, Path], damage: str) -> None:
    source, a, b = bundles
    if damage in ("values", "schema"):
        with ipc.open_file(b / "catchments.arrow") as reader:
            table = reader.read_all()
        if damage == "values":
            table = table.set_column(1, "value", pa.array(["wrong", None, "c"]))
        else:
            table = table.replace_schema_metadata({b"origin": b"wrong"})
        with ipc.new_file(b / "catchments.arrow", table.schema) as writer:
            writer.write_table(table)
        refresh(b)
    elif damage == "address":
        with ipc.open_file(a / "lookup.arrow") as reader:
            table = reader.read_all()
        table = table.set_column(2, table.schema.field("row"), pa.array([0, 0, 0], type=pa.int32()))
        with ipc.new_file(a / "lookup.arrow", table.schema) as writer:
            writer.write_table(table, max_chunksize=2)
        refresh(a)
    elif damage == "directory":
        (a / "lookup-directory.json").write_text('{"version": 1, "batches": []}')
        refresh(a)
    else:
        (a / "network.bin").write_bytes(b"wrong")
    with pytest.raises(
        ValueError,
        match={
            "values": "B values",
            "schema": "B schema",
            "address": "wrong ID",
            "directory": "directory differs",
            "hash": "fingerprints",
        }[damage],
    ):
        verify(source, a, b)
    assert not (source.parent / "verification.json").exists()


def test_producer_output_verifies(bundles: tuple[Path, Path, Path]) -> None:
    from hfx.candidates import build

    source, _, _ = bundles
    (source / "manifest.json").write_text('{"format_version": "0.3.0", "unit_count": 3}')
    a, b = source.parent / "produced-a", source.parent / "produced-b"
    build(source, a, b, index_batch_rows=2, catchment_batch_bytes=32)
    result = verify(source, a, b)
    assert result["source_rows"] == 3
    assert result["candidates"]["a-index"]["data_blocks"] == 2
    assert result["candidates"]["b-arrow"]["index_batches"] == 2


def test_larger_configured_budgets_verify(bundles: tuple[Path, Path, Path]) -> None:
    from hfx.candidates import build

    source, _, _ = bundles
    (source / "manifest.json").write_text('{"format_version": "0.3.0", "unit_count": 3}')
    a, b = source.parent / "large-budget-a", source.parent / "large-budget-b"
    build(source, a, b, index_batch_rows=65537, catchment_batch_bytes=8388609)
    assert verify(source, a, b)["status"] == "passed"
