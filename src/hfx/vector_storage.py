"""Bounded vector batches and disk-backed physical address lookup production."""

import hashlib
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, TypedDict

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc


class IndexBatch(TypedDict):
    batch: int
    min_id: int
    max_id: int
    rows: int


class Directory(TypedDict):
    version: int
    batches: list[IndexBatch]


def budget_batches(batches: Iterable[pa.RecordBatch], budget: int) -> Iterator[pa.RecordBatch]:
    """Keep incoming boundaries; emit an oversized single row without splitting it."""
    if budget <= 0:
        raise ValueError("vector byte budget must be positive")
    for incoming in batches:
        offset = 0
        while offset < incoming.num_rows:
            low, high = 1, incoming.num_rows - offset
            while low < high:
                middle = (low + high + 1) // 2
                if incoming.slice(offset, middle).nbytes <= budget:
                    low = middle
                else:
                    high = middle - 1
            yield incoming.slice(offset, low)
            offset += low


@contextmanager
def _addresses(parent: Path) -> Iterator[sqlite3.Connection]:
    # Scratch and SQLite sidecars are owned by this call, never another producer.
    with TemporaryDirectory(prefix="hfx-addresses-", dir=parent) as scratch:
        connection = sqlite3.connect(Path(scratch) / "addresses.sqlite")
        try:
            connection.execute("PRAGMA cache_size = -8192")
            connection.execute("PRAGMA temp_store = FILE")
            connection.execute(
                "CREATE TABLE addresses (id INTEGER PRIMARY KEY, block INTEGER NOT NULL, row INTEGER NOT NULL)"
            )
            yield connection
        finally:
            connection.close()


def _add_addresses(connection: sqlite3.Connection, ids: pa.Array, block: int) -> None:
    if ids.type != pa.int64():
        raise ValueError("IDs must have int64 type")
    if ids.null_count or (len(ids) and pc.min(ids).as_py() <= 0):
        raise ValueError("IDs must be positive, unique, non-null")
    try:
        connection.executemany(
            "INSERT INTO addresses VALUES (?, ?, ?)", ((value, block, row) for row, value in enumerate(ids.to_pylist()))
        )
        connection.commit()
    except sqlite3.IntegrityError as error:
        raise ValueError("IDs must be positive, unique, non-null") from error


def _write_lookup(
    connection: sqlite3.Connection, path: Path, metadata: dict[bytes | str, bytes | str], batch_rows: int
) -> Directory:
    schema = pa.schema(
        [
            pa.field("id", pa.int64(), nullable=False),
            pa.field("block", pa.int32(), nullable=False),
            pa.field("row", pa.int32(), nullable=False),
        ],
        metadata=metadata,
    )
    cursor = connection.execute("SELECT id, block, row FROM addresses ORDER BY id")
    rows = cursor.fetchmany(batch_rows)
    if not rows:
        raise ValueError("vectors must not be empty")
    directory: Directory = {"version": 1, "batches": []}
    with ipc.new_file(str(path), schema, options=ipc.IpcWriteOptions(compression=None)) as writer:
        while rows:
            batch = pa.RecordBatch.from_arrays(
                [pa.array([row[column] for row in rows], type=field.type) for column, field in enumerate(schema)],
                schema=schema,
            )
            writer.write_batch(batch)
            directory["batches"].append(
                {"batch": len(directory["batches"]), "min_id": rows[0][0], "max_id": rows[-1][0], "rows": len(rows)}
            )
            rows = cursor.fetchmany(batch_rows)
    return directory


def write_address_index(
    path: Path, blocks: Iterable[pa.Array], metadata: dict[bytes | str, bytes | str], batch_rows: int
) -> Directory:
    """Sort addresses on disk; retain only one input and one output batch in memory."""
    if batch_rows <= 0:
        raise ValueError("index batch rows must be positive")
    with _addresses(path.parent) as connection:
        for block, ids in enumerate(blocks):
            _add_addresses(connection, ids, block)
        return _write_lookup(connection, path, metadata, batch_rows)


def write_vectors(
    schema: pa.Schema,
    batches: Iterable[pa.RecordBatch],
    path: Path,
    lookup_path: Path,
    *,
    batch_bytes: int = 8 * 1024 * 1024,
    index_batch_rows: int = 65536,
    format_version: str = "0.4.0",
    lookup_binding: Literal["hfx:data_sha256", "hfx:catchments_sha256"] = "hfx:data_sha256",
) -> Directory:
    """Write typed vectors and their bound lookup. Failed outputs remain for diagnosis.

    Producers bound incoming batches; this function bounds output batches, SQLite's
    page cache (8 MiB), and lookup batches. The returned directory grows with lookup
    batch count. Callers own output paths and publish only after verification.
    """
    if batch_bytes <= 0 or index_batch_rows <= 0:
        raise ValueError("batch budgets must be positive")
    id_column = schema.get_field_index("id")
    if id_column < 0 or schema.field(id_column).type != pa.int64():
        raise ValueError("IDs must have int64 type")
    if path.resolve() == lookup_path.resolve():
        raise ValueError("data and lookup paths must differ")
    with _addresses(lookup_path.parent) as connection:
        with ipc.new_file(str(path), schema, options=ipc.IpcWriteOptions(compression="zstd")) as writer:
            for block, batch in enumerate(budget_batches(batches, batch_bytes)):
                if not batch.schema.equals(schema, check_metadata=True):
                    raise ValueError("incoming batch schema differs from declared schema")
                _add_addresses(connection, batch.column(id_column), block)
                writer.write_batch(batch)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return _write_lookup(
            connection,
            lookup_path,
            {lookup_binding.encode(): digest.encode(), b"hfx:format_version": format_version.encode()},
            index_batch_rows,
        )
