"""Spatially ordered GeoParquet with native Arrow preservation and full verification."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from hfx.candidates import fingerprint
from hfx.vector_storage import budget_batches, write_address_index

VERIFY_WINDOW_BYTES = 128 * 1024 * 1024
VERIFY_WINDOW_ROWS = 8192

BBOX_NAMES = ("xmin", "ymin", "xmax", "ymax")
BBOX_LEAVES = [f"bbox.{name}" for name in BBOX_NAMES]
GEO = {
    "version": "1.1.0",
    "primary_column": "geometry",
    "columns": {
        "geometry": {
            "encoding": "WKB",
            "geometry_types": [],
            "covering": {"bbox": {name: ["bbox", name] for name in BBOX_NAMES}},
        }
    },
}
IntArray = npt.NDArray[np.int64]


def geo_schema(schema: pa.Schema) -> pa.Schema:
    if b"geo" in (schema.metadata or {}):
        raise ValueError("source already has geo metadata")
    bounds = pa.struct([pa.field(name, pa.float32(), False) for name in BBOX_NAMES])
    if (
        schema.field("geometry").type != pa.binary()
        or schema.field("bbox").type != bounds
        or schema.field("bbox").nullable
    ):
        raise ValueError("expected binary WKB and nonnull native float32 bbox")
    return schema.with_metadata({**(schema.metadata or {}), b"geo": json.dumps(GEO).encode()})


def morton(batch: pa.RecordBatch) -> npt.NDArray[np.uint64]:
    bounds = cast(pa.StructArray, batch.column("bbox"))
    values = [bounds.field(name).to_numpy().astype(np.float64) for name in BBOX_NAMES]
    if bounds.null_count or any(not np.all(np.isfinite(value)) for value in values):
        raise ValueError("bounds must be finite and nonnull")
    if np.any(values[0] > values[2]) or np.any(values[1] > values[3]):
        raise ValueError("invalid bounds")
    x = np.clip(((values[0] + values[2]) * 0.5 + 180) / 360 * 65535, 0, 65535).astype(np.uint64)
    y = np.clip(((values[1] + values[3]) * 0.5 + 90) / 180 * 65535, 0, 65535).astype(np.uint64)
    result = np.zeros(batch.num_rows, dtype=np.uint64)
    for bit in range(16):
        result |= ((x >> bit) & 1) << (2 * bit)
        result |= ((y >> bit) & 1) << (2 * bit + 1)
    return result


def _source_ids(reader: ipc.RecordBatchFileReader) -> tuple[IntArray, IntArray, int]:
    ids: list[IntArray] = []
    starts = [0]
    logical_bytes = 0
    for index in range(reader.num_record_batches):
        batch = reader.get_batch(index)
        logical_bytes += batch.nbytes
        column = batch.column("id")
        if column.type != pa.int64() or column.null_count:
            raise ValueError("IDs must be nonnull int64")
        ids.append(column.to_numpy().copy())
        starts.append(starts[-1] + batch.num_rows)
    all_ids = np.concatenate(ids) if ids else np.array([], dtype=np.int64)
    ordered = np.sort(all_ids)
    if not len(ordered) or ordered[0] <= 0 or np.any(ordered[1:] <= ordered[:-1]):
        raise ValueError("IDs must be unique positive int64; features must not be empty")
    return all_ids, np.asarray(starts, dtype=np.int64), logical_bytes


def build_features(source: Path, output: Path, family: str, rows: int = 8192, budget: int = 8388608) -> dict[str, Any]:
    """Sort numeric keys only; gather original Arrow records without scalar conversion.

    Numeric arrays scale with domain size. Geometry memory is limited to source
    batches and one gathered batch (a single oversized record is not split).
    Scattered source addresses can require repeated source batch decompression.
    """
    if rows <= 0 or budget <= 0:
        raise ValueError("batch limits must be positive")
    data = output / f"{family}.parquet"
    lookup = output / f"{family}-lookup.arrow"
    directory = output / f"{family}-lookup-directory.json"
    for path in (data, lookup, directory):
        if path.exists():
            raise FileExistsError(path)
    with pa.OSFile(str(source), "r") as stream:
        reader = ipc.open_file(stream)
        schema = geo_schema(reader.schema)
        ids, starts, source_logical_bytes = _source_ids(reader)
        levels: list[IntArray] = []
        codes: list[npt.NDArray[np.uint64]] = []
        source_batch_reads = 2 * reader.num_record_batches
        source_decoded_bytes = 0
        for index in range(reader.num_record_batches):
            batch = reader.get_batch(index)
            if batch.column("level").null_count:
                raise ValueError("level must be nonnull")
            source_decoded_bytes += 2 * batch.nbytes  # ID validation and key scan
            levels.append(batch.column("level").to_numpy().copy())
            codes.append(morton(batch))
        order = np.lexsort((ids, np.concatenate(codes), np.concatenate(levels)))

        def batches() -> Iterator[pa.RecordBatch]:
            nonlocal source_batch_reads, source_decoded_bytes
            for offset in range(0, len(order), rows):
                selected = order[offset : offset + rows]
                blocks = np.searchsorted(starts, selected, side="right") - 1
                pieces = []
                positions = []
                for block in np.unique(blocks):
                    places = np.flatnonzero(blocks == block)
                    incoming = reader.get_batch(int(block))
                    source_batch_reads += 1
                    source_decoded_bytes += incoming.nbytes
                    pieces.append(incoming.take(pa.array(selected[places] - starts[block])))
                    del incoming
                    positions.append(places)
                table = pa.Table.from_batches(pieces).take(
                    pa.array(np.argsort(np.concatenate(positions)), type=pa.int64())
                )
                yield table.combine_chunks().to_batches()[0].replace_schema_metadata(schema.metadata)

        with pq.ParquetWriter(
            data,
            schema,
            compression="zstd",
            use_dictionary=False,
            write_statistics=BBOX_LEAVES,
            store_schema=True,
            use_compliant_nested_type=False,
        ) as writer:
            for batch in budget_batches(batches(), budget):
                writer.write_batch(batch, row_group_size=batch.num_rows)
    digest = fingerprint(data)["sha256"]
    with pq.ParquetFile(data) as parquet:
        entries = write_address_index(
            lookup,
            (
                parquet.read_row_group(i, columns=["id"]).column(0).combine_chunks()
                for i in range(parquet.num_row_groups)
            ),
            {b"hfx:data_sha256": digest.encode()},
            65536,
        )
    directory.write_text(json.dumps(entries))
    return {
        "data": data.name,
        "data_sha256": digest,
        "lookup": lookup.name,
        "directory": directory.name,
        "count": len(ids),
        "source_artifact": source.name,
        "rows": rows,
        "budget": budget,
        "ordering": "level, 16-bit longitude/latitude Morton center, id",
        "index_batch_rows": 65536,
        "source_batch_reads": source_batch_reads,
        "source_decoded_bytes": source_decoded_bytes,
        "source_logical_bytes": source_logical_bytes,
        "source_decode_amplification": source_decoded_bytes / source_logical_bytes,
    }


def exact_array(left: pa.Array, right: pa.Array) -> bool:
    """Ignore undefined null storage, but compare every valid floating-point bit."""
    if left.type != right.type or not left.is_valid().equals(right.is_valid()):
        return False
    left = pc.filter(left, left.is_valid())
    right = pc.filter(right, right.is_valid())
    if pa.types.is_struct(left.type):
        return all(
            exact_array(cast(pa.StructArray, left).field(i), cast(pa.StructArray, right).field(i))
            for i in range(left.type.num_fields)
        )
    if pa.types.is_floating(left.type):
        unsigned = {16: pa.uint16(), 32: pa.uint32(), 64: pa.uint64()}[left.type.bit_width]
        return left.view(unsigned).equals(right.view(unsigned))
    if pa.types.is_list(left.type) or pa.types.is_large_list(left.type) or pa.types.is_fixed_size_list(left.type):
        return all(exact_array(a.values, b.values) for a, b in zip(left, right, strict=True))
    return left.equals(right)


def verify_features(source: Path, output: Path, declaration: dict[str, Any]) -> dict[str, Any]:
    """Compare every original value using independent ID resolution, not a feature sort.

    Coalesce physical groups into byte- and row-limited comparison windows. One
    oversized physical group is accepted alone. Live geometry includes the window,
    one incoming group, one source batch, and selected comparison arrays; the limits
    bound retained output, not process RSS. Numeric address arrays scale with rows.
    """
    data = output / declaration["data"]
    digest = fingerprint(data)["sha256"]
    lookup = ipc.open_file(str(output / declaration["lookup"]))
    if (
        declaration["data_sha256"] != digest
        or (lookup.schema.metadata or {}).get(b"hfx:data_sha256") != digest.encode()
    ):
        raise ValueError("data binding differs")
    lookup_schema = pa.schema(
        [pa.field("id", pa.int64(), False), pa.field("block", pa.int32(), False), pa.field("row", pa.int32(), False)],
        metadata={b"hfx:data_sha256": digest.encode()},
    )
    if not lookup.schema.equals(lookup_schema, check_metadata=True):
        raise ValueError("lookup schema differs")
    with pa.OSFile(str(source), "r") as stream, pq.ParquetFile(data) as parquet:
        original = ipc.open_file(stream)
        if not geo_schema(original.schema).equals(parquet.schema_arrow, check_metadata=True):
            raise ValueError("schema or metadata differs")
        source_ids, starts, source_logical_bytes = _source_ids(original)
        source_batch_reads = original.num_record_batches
        source_decoded_bytes = source_logical_bytes
        source_order = np.argsort(source_ids)
        sorted_ids = source_ids[source_order]
        seen = np.zeros(len(source_ids), dtype=bool)
        physical_ids = []
        group_starts = [0]
        window: list[pa.Table] = []
        window_positions: list[IntArray] = []
        window_bytes = 0
        window_rows = 0

        def compare_window() -> None:
            nonlocal source_batch_reads, source_decoded_bytes
            group = pa.concat_tables(window)
            positions = np.concatenate(window_positions)
            source_blocks = np.searchsorted(starts, positions, side="right") - 1
            for block in np.unique(source_blocks):
                places = np.flatnonzero(source_blocks == block)
                incoming = original.get_batch(int(block))
                source_batch_reads += 1
                source_decoded_bytes += incoming.nbytes
                expected = incoming.take(pa.array(positions[places] - starts[block]))
                del incoming
                actual = group.take(pa.array(places, type=pa.int64()))
                for name in original.schema.names:
                    if not exact_array(expected.column(name), actual.column(name).combine_chunks()):
                        raise ValueError(f"source column {name} differs")
            window.clear()
            window_positions.clear()

        for index in range(parquet.num_row_groups):
            group = parquet.read_row_group(index).combine_chunks()
            ids = group.column("id").chunk(0).to_numpy()
            ranks = np.searchsorted(sorted_ids, ids)
            if np.any(ranks >= len(sorted_ids)) or not np.array_equal(sorted_ids[ranks], ids):
                raise ValueError("source IDs differ")
            positions = source_order[ranks]
            if np.any(seen[positions]) or len(np.unique(positions)) != len(positions):
                raise ValueError("duplicate output IDs")
            seen[positions] = True
            bounds = cast(pa.StructArray, group.column("bbox").chunk(0))
            for column_index in range(parquet.metadata.num_columns):
                column = parquet.metadata.row_group(index).column(column_index)
                if column.path_in_schema in BBOX_LEAVES:
                    values = bounds.field(column.path_in_schema.split(".")[1])
                    stats = column.statistics
                    if (
                        values.null_count
                        or not np.all(np.isfinite(values.to_numpy()))
                        or stats is None
                        or not stats.has_min_max
                        or stats.null_count != 0
                        or stats.min > pc.min(values).as_py()
                        or stats.max < pc.max(values).as_py()
                    ):
                        raise ValueError("bbox statistics are not conservative")
            physical_ids.append(ids.copy())
            group_starts.append(group_starts[-1] + len(ids))
            if window and (
                window_bytes + group.nbytes > VERIFY_WINDOW_BYTES or window_rows + group.num_rows > VERIFY_WINDOW_ROWS
            ):
                compare_window()
                window_bytes = 0
                window_rows = 0
            window.append(group)
            window_positions.append(positions)
            window_bytes += group.nbytes
            window_rows += group.num_rows
        if window:
            compare_window()
        if not np.all(seen) or len(source_ids) != declaration["count"]:
            raise ValueError("source row coverage differs")
        stored_ids = np.concatenate(physical_ids)
        offsets = np.asarray(group_starts, dtype=np.int64)
        sizes = np.diff(offsets)
        entries = json.loads((output / declaration["directory"]).read_text())["batches"]
        if len(entries) != lookup.num_record_batches:
            raise ValueError("lookup directory coverage differs")
        previous = 0
        count = 0
        for index, entry in enumerate(entries):
            batch = lookup.get_batch(index)
            ids = batch.column("id").to_numpy()
            blocks = batch.column("block").to_numpy()
            positions = batch.column("row").to_numpy()
            if (
                not len(ids)
                or ids[0] <= previous
                or np.any(ids[1:] <= ids[:-1])
                or entry != {"batch": index, "min_id": int(ids[0]), "max_id": int(ids[-1]), "rows": len(ids)}
            ):
                raise ValueError("lookup IDs or directory differ")
            if (
                np.any(blocks < 0)
                or np.any(blocks >= len(sizes))
                or np.any(positions < 0)
                or np.any(positions >= sizes[blocks])
            ):
                raise ValueError("lookup address out of bounds")
            if not np.array_equal(stored_ids[offsets[blocks] + positions], ids):
                raise ValueError("lookup address differs")
            count += len(ids)
            previous = int(ids[-1])
        if count != len(source_ids):
            raise ValueError("lookup count differs")
        return {
            "status": "passed",
            "rows": count,
            "row_groups": parquet.num_row_groups,
            "source_batch_reads": source_batch_reads,
            "source_decoded_bytes": source_decoded_bytes,
            "source_logical_bytes": source_logical_bytes,
            "source_decode_amplification": source_decoded_bytes / source_logical_bytes,
        }
