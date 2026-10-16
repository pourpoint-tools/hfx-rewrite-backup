"""Small spatial IPC build and access probes; not a supported reader."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import duckdb
import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc

from hfx.vector_storage import budget_batches

IntArray = npt.NDArray[np.int64]


def morton(batch: pa.RecordBatch) -> npt.NDArray[np.uint64]:
    bounds = cast(pa.StructArray, batch.column("bbox"))
    x = (bounds.field("xmin").to_numpy() + bounds.field("xmax").to_numpy()) * 0.5
    y = (bounds.field("ymin").to_numpy() + bounds.field("ymax").to_numpy()) * 0.5
    coords = [
        np.clip((x.astype(np.float64) + 180) / 360 * 65535, 0, 65535).astype(np.uint64),
        np.clip((y.astype(np.float64) + 90) / 180 * 65535, 0, 65535).astype(np.uint64),
    ]
    result = np.zeros(batch.num_rows, dtype=np.uint64)
    for bit in range(16):
        result |= ((coords[0] >> bit) & 1) << (2 * bit)
        result |= ((coords[1] >> bit) & 1) << (2 * bit + 1)
    return result


def restored(batch: pa.RecordBatch, schema: pa.Schema) -> pa.RecordBatch:
    arrays = [batch.column(field.name).cast(field.type) for field in schema]
    return pa.RecordBatch.from_arrays(arrays, schema=schema)


def build_features(
    source: Path, output: Path, family: str, *, rows: int = 8192, budget: int = 8388608
) -> dict[str, Any]:
    if rows <= 0 or budget <= 0:
        raise ValueError("batch limits must be positive")
    data_path = output / f"{family}.arrow"
    if data_path.exists():
        raise FileExistsError(data_path)
    source_reader = ipc.open_file(str(source))
    schema = source_reader.schema
    keyed_schema = schema.append(pa.field("__morton", pa.uint64(), False))

    def incoming() -> Iterator[pa.RecordBatch]:
        for index in range(source_reader.num_record_batches):
            batch = source_reader.get_batch(index)
            yield pa.RecordBatch.from_arrays([*batch.columns, pa.array(morton(batch))], schema=keyed_schema)

    staging = output / f".{family}-sort"
    staging.mkdir()
    connection = duckdb.connect()
    connection.execute("SET memory_limit='8GB'")
    connection.execute("SET threads=1")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute("SET temp_directory=?", [str(staging)])
    connection.register("incoming", pa.RecordBatchReader.from_batches(keyed_schema, incoming()))
    try:
        ordered = connection.execute(
            "SELECT * EXCLUDE (__morton) FROM incoming ORDER BY level, __morton, id"
        ).to_arrow_reader(batch_size=rows)
    except Exception:
        connection.close()
        raise
    envelopes: list[dict[str, Any]] = []
    ids: list[IntArray] = []
    blocks: list[npt.NDArray[np.int32]] = []
    positions: list[npt.NDArray[np.int32]] = []
    count = 0
    temporary_bytes = sum(p.stat().st_size for p in staging.rglob("*") if p.is_file())
    try:
        with ipc.new_file(str(data_path), schema, options=ipc.IpcWriteOptions(compression="zstd")) as writer:
            batches = (restored(batch, schema) for batch in ordered)
            for block, batch in enumerate(budget_batches(batches, budget)):
                writer.write_batch(batch)
                bounds = cast(pa.StructArray, batch.column("bbox"))
                bbox = [float(pc.min(bounds.field(n)).as_py()) for n in ("xmin", "ymin")] + [
                    float(pc.max(bounds.field(n)).as_py()) for n in ("xmax", "ymax")
                ]
                envelopes.append(
                    {
                        "batch": block,
                        "rows": batch.num_rows,
                        "bbox": bbox,
                        "min_level": int(pc.min(batch.column("level")).as_py()),
                        "max_level": int(pc.max(batch.column("level")).as_py()),
                    }
                )
                ids.append(batch.column("id").to_numpy().copy())
                blocks.append(np.full(batch.num_rows, block, dtype=np.int32))
                positions.append(np.arange(batch.num_rows, dtype=np.int32))
                count += batch.num_rows
                temporary_bytes = max(temporary_bytes, sum(p.stat().st_size for p in staging.rglob("*") if p.is_file()))
    finally:
        connection.close()
    staging.rmdir()
    if not count:
        raise ValueError("empty features")
    all_ids = np.concatenate(ids)
    order = np.argsort(all_ids, kind="stable")
    sorted_ids = all_ids[order]
    if sorted_ids[0] <= 0 or np.any(sorted_ids[1:] <= sorted_ids[:-1]):
        raise ValueError("IDs must be unique positive int64")
    from hfx.candidates import fingerprint

    lookup_schema = pa.schema(
        [pa.field("id", pa.int64(), False), pa.field("block", pa.int32(), False), pa.field("row", pa.int32(), False)],
        metadata={b"hfx:data_sha256": fingerprint(data_path)["sha256"].encode()},
    )
    lookup = pa.Table.from_arrays(
        [pa.array(sorted_ids), pa.array(np.concatenate(blocks)[order]), pa.array(np.concatenate(positions)[order])],
        schema=lookup_schema,
    )
    lookup_name = f"{family}-lookup.arrow"
    directory = []
    with ipc.new_file(str(output / lookup_name), lookup_schema) as writer:
        for index, batch in enumerate(lookup.to_batches(max_chunksize=65536)):
            writer.write_batch(batch)
            directory.append(
                {
                    "batch": index,
                    "min_id": batch.column(0)[0].as_py(),
                    "max_id": batch.column(0)[-1].as_py(),
                    "rows": batch.num_rows,
                }
            )
    directory_name = f"{family}-lookup-directory.json"
    spatial_name = f"{family}-spatial.json"
    (output / directory_name).write_text(json.dumps({"version": 1, "batches": directory}))
    (output / spatial_name).write_text(json.dumps({"version": 1, "batches": envelopes}))
    return {
        "data": data_path.name,
        "data_sha256": fingerprint(data_path)["sha256"],
        "lookup": lookup_name,
        "directory": directory_name,
        "spatial": spatial_name,
        "count": count,
        "source_artifact": source.name,
        "rows": rows,
        "budget": budget,
        "observed_temporary_bytes": temporary_bytes,
    }


def projected(path: Path, columns: list[str] | None) -> ipc.RecordBatchFileReader:
    schema = ipc.open_file(str(path)).schema
    fields = None if columns is None else [schema.get_field_index(name) for name in columns]
    if fields is not None and (-1 in fields or not fields):
        raise ValueError("select at least one existing column")
    return ipc.open_file(str(path), options=ipc.IpcReadOptions(included_fields=fields))


def select_ids(
    root: Path, declaration: dict[str, Any], requested: list[int], columns: list[str] | None = None
) -> tuple[pa.Table, list[int]]:
    directory = json.loads((root / declaration["directory"]).read_text())["batches"]
    lookup = ipc.open_file(str(root / declaration["lookup"]))
    reader = projected(root / declaration["data"], columns)
    wanted = np.unique(np.asarray(requested, dtype=np.int64))
    addresses: dict[int, list[tuple[int, int]]] = {}
    for entry in directory:
        left, right = np.searchsorted(wanted, [entry["min_id"], entry["max_id"]], side="left")
        if right < len(wanted) and wanted[right] == entry["max_id"]:
            right += 1
        values = wanted[left:right]
        if not len(values):
            continue
        batch = lookup.get_batch(entry["batch"])
        ids = batch.column("id").to_numpy()
        for value in values:
            index = int(np.searchsorted(ids, value))
            if index < len(ids) and int(ids[index]) == value:
                addresses.setdefault(int(batch.column("block")[index].as_py()), []).append(
                    (int(batch.column("row")[index].as_py()), value)
                )
    # Always include ID in projection for address validation, then remove it if unrequested.
    if columns is not None and "id" not in columns:
        reader = projected(root / declaration["data"], [*columns, "id"])
    batches: list[pa.RecordBatch] = []
    received: list[npt.NDArray[np.int64]] = []
    for block, targets in addresses.items():
        batch = reader.get_batch(block)
        positions = np.asarray([row for row, _ in targets], dtype=np.int64)
        values = np.asarray([value for _, value in targets], dtype=np.int64)
        if (
            np.any(positions < 0)
            or np.any(positions >= batch.num_rows)
            or not np.array_equal(batch.column("id").to_numpy()[positions], values)
        ):
            raise ValueError("address ID mismatch")
        batches.append(batch.take(pa.array(positions, type=pa.int64())))
        received.append(values)
    table = pa.Table.from_batches(batches, schema=reader.schema)
    found = np.concatenate(received) if received else np.array([], dtype=np.int64)
    order = np.argsort(found)
    sorted_found = found[order]
    requested_values = np.asarray(requested, dtype=np.int64)
    positions = np.searchsorted(sorted_found, requested_values)
    exists = positions < len(sorted_found)
    if len(sorted_found):
        exists &= sorted_found[np.minimum(positions, len(sorted_found) - 1)] == requested_values
    if len(found):
        table = table.take(pa.array(order[positions[exists]], type=pa.int64()))
    if columns is not None:
        table = table.select(columns)
    return table, np.unique(requested_values[~exists]).tolist()


def overlaps(a: list[float] | tuple[float, ...], b: tuple[float, ...]) -> bool:
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def spatial_ids(
    root: Path, declaration: dict[str, Any], window: tuple[float, ...], level: int | None = None
) -> list[int]:
    entries = json.loads((root / declaration["spatial"]).read_text())["batches"]
    reader = projected(root / declaration["data"], ["id", "level", "bbox"])
    selected: list[int] = []
    for entry in entries:
        if not overlaps(entry["bbox"], window) or (
            level is not None and not entry["min_level"] <= level <= entry["max_level"]
        ):
            continue
        batch = reader.get_batch(entry["batch"])
        bounds = cast(pa.StructArray, batch.column("bbox"))
        mask = np.ones(batch.num_rows, dtype=np.bool_)
        for name, coordinate, less in [
            ("xmin", window[2], True),
            ("xmax", window[0], False),
            ("ymin", window[3], True),
            ("ymax", window[1], False),
        ]:
            values = bounds.field(name).to_numpy()
            mask &= values <= coordinate if less else values >= coordinate
        if level is not None:
            mask &= batch.column("level").to_numpy() == level
        selected.extend(batch.column("id").to_numpy()[mask].tolist())
    return sorted(selected)


def verify_features(source: Path, root: Path, declaration: dict[str, Any]) -> None:
    original = ipc.open_file(str(source))
    candidate = ipc.open_file(str(root / declaration["data"]))
    if not original.schema.equals(candidate.schema, check_metadata=True):
        raise ValueError("schema or metadata changed")
    envelopes = json.loads((root / declaration["spatial"]).read_text())["batches"]
    if len(envelopes) != candidate.num_record_batches:
        raise ValueError("spatial batch coverage differs")
    bounds_reader = projected(root / declaration["data"], ["level", "bbox"])
    for index, entry in enumerate(envelopes):
        batch = bounds_reader.get_batch(index)
        bounds = cast(pa.StructArray, batch.column("bbox"))
        expected = [float(pc.min(bounds.field(n)).as_py()) for n in ("xmin", "ymin")] + [
            float(pc.max(bounds.field(n)).as_py()) for n in ("xmax", "ymax")
        ]
        if (
            entry["batch"] != index
            or entry["rows"] != batch.num_rows
            or entry["bbox"] != expected
            or entry["min_level"] != pc.min(batch.column("level")).as_py()
            or entry["max_level"] != pc.max(batch.column("level")).as_py()
        ):
            raise ValueError("spatial directory differs")
    lookup = ipc.open_file(str(root / declaration["lookup"]))
    from hfx.candidates import fingerprint

    digest = fingerprint(root / declaration["data"])["sha256"]
    if (
        declaration["data_sha256"] != digest
        or (lookup.schema.metadata or {}).get(b"hfx:data_sha256") != digest.encode()
    ):
        raise ValueError("lookup/spatial data binding differs")
    directory = json.loads((root / declaration["directory"]).read_text())["batches"]
    if len(directory) != lookup.num_record_batches:
        raise ValueError("lookup directory coverage differs")
    previous = 0
    lookup_count = 0
    id_reader = projected(root / declaration["data"], ["id"])
    # Explicit producer verification retains only numeric IDs, not global feature rows.
    physical_ids: list[IntArray] = []
    starts = [0]
    for block in range(id_reader.num_record_batches):
        values = id_reader.get_batch(block).column(0).to_numpy().copy()
        physical_ids.append(values)
        starts.append(starts[-1] + len(values))
    all_ids = np.concatenate(physical_ids)
    del physical_ids
    offsets = np.asarray(starts, dtype=np.int64)
    sizes = np.diff(offsets)
    for index in range(lookup.num_record_batches):
        batch = lookup.get_batch(index)
        ids = batch.column("id").to_numpy()
        blocks = batch.column("block").to_numpy()
        rows = batch.column("row").to_numpy()
        entry = directory[index]
        if (
            ids[0] <= previous
            or np.any(ids[1:] <= ids[:-1])
            or entry != {"batch": index, "min_id": int(ids[0]), "max_id": int(ids[-1]), "rows": len(ids)}
        ):
            raise ValueError("lookup directory or IDs differ")
        if np.any(blocks < 0) or np.any(blocks >= len(sizes)) or np.any(rows < 0) or np.any(rows >= sizes[blocks]):
            raise ValueError("lookup address out of bounds")
        if not np.array_equal(all_ids[offsets[blocks] + rows], ids):
            raise ValueError("lookup address differs")
        previous = int(ids[-1])
        lookup_count += len(ids)
    del all_ids
    if lookup_count != declaration["count"]:
        raise ValueError("lookup count differs")
    from tempfile import TemporaryDirectory

    scratch = TemporaryDirectory(prefix="hfx-verify-", dir=root.parent)
    connections = [duckdb.connect(), duckdb.connect()]
    readers = []
    try:
        for connection, reader in zip(connections, [original, candidate], strict=True):
            connection.execute("SET memory_limit='8GB'")
            connection.execute("SET threads=1")
            connection.execute("SET preserve_insertion_order=false")
            connection.execute("SET temp_directory=?", [str(Path(scratch.name) / str(len(readers)))])
            connection.register(
                "records",
                pa.RecordBatchReader.from_batches(
                    reader.schema, (reader.get_batch(i) for i in range(reader.num_record_batches))
                ),
            )
            readers.append(connection.execute("SELECT * FROM records ORDER BY id").to_arrow_reader(batch_size=8192))
        count = 0
        for left, right in zip(readers[0], readers[1], strict=True):
            left = restored(left, original.schema)
            right = restored(right, original.schema)
            if not left.equals(right, check_metadata=True):
                raise ValueError("source rows differ")
            count += left.num_rows
        if count != declaration["count"]:
            raise ValueError("count differs")
    finally:
        for connection in connections:
            connection.close()
        scratch.cleanup()
