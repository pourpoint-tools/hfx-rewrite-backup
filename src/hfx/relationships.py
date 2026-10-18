"""Portable immediate relationships derived only from authoritative source records.

IDs are separate per domain. Empty adjacency is not a terminal classification;
catchment connectivity availability is carried in the returned declaration.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

IntArray = npt.NDArray[np.int64]

_FILES = {"catchments": "catchments.arrow", "rivers": "rivers.arrow", "river_nodes": "river-nodes.arrow"}
# Explicit scalar source references, with independent reverse access names.
_REFERENCES = [
    ("catchments", "parent_id", "catchments", "parent_ids", "child_ids"),
    ("rivers", "parent_id", "rivers", "parent_ids", "child_ids"),
    ("rivers", "upstream_node_id", "river_nodes", "upstream_node_ids", "outgoing_river_ids"),
    ("rivers", "downstream_node_id", "river_nodes", "downstream_node_ids", "incoming_river_ids"),
    ("river_nodes", "coarser_node_id", "river_nodes", "coarser_node_ids", "finer_node_ids"),
    ("rivers", "local_catchment_id", "catchments", "local_catchment_ids", "local_river_ids"),
    ("rivers", "component_catchment_id", "catchments", "component_catchment_ids", "component_river_ids"),
]


def _bindings(domain: str) -> dict[str, dict[str, str]]:
    bindings: dict[str, dict[str, str]] = {}
    if domain != "river_nodes":
        for name, direction in (("upstream_ids", "forward"), ("downstream_ids", "reverse")):
            bindings[name] = {
                "source_domain": domain,
                "target_domain": domain,
                "source_artifact": "graph.parquet" if domain == "catchments" else "river-graph.parquet",
                "source_column": "upstream_ids",
                "direction": direction,
            }
    for origin, column, target, forward, reverse in _REFERENCES:
        if domain == origin:
            bindings[forward] = {
                "source_domain": origin,
                "target_domain": target,
                "source_artifact": _FILES[origin],
                "source_column": column,
                "direction": "forward",
            }
        if domain == target:
            bindings[reverse] = {
                "source_domain": origin,
                "target_domain": origin,
                "source_artifact": _FILES[origin],
                "source_column": column,
                "direction": "reverse",
            }
    return bindings


def _source_artifacts(domain: str, bindings: dict[str, dict[str, str]]) -> list[str]:
    artifacts = {_FILES[domain]}
    for binding in bindings.values():
        artifacts.update(
            (binding["source_artifact"], _FILES[binding["source_domain"]], _FILES[binding["target_domain"]])
        )
    if domain == "catchments":
        artifacts.add("manifest.json")
    return sorted(artifacts)


def _project(path: Path, names: list[str]) -> pa.Table:
    """Use IPC projection before reading compressed record-batch buffers."""
    with pa.memory_map(str(path), "r") as source:
        schema = ipc.open_file(source).schema
        fields = [schema.get_field_index(name) for name in names]
        if -1 in fields:
            raise ValueError(f"Missing relationship columns in {path}: {names}")
        source.seek(0)
        options = ipc.IpcReadOptions(included_fields=fields)
        return ipc.open_file(source, options=options).read_all().combine_chunks()


def _numeric(column: pa.ChunkedArray | pa.Array) -> IntArray:
    if column.null_count:
        raise ValueError("Relationship IDs must not be null")
    return np.asarray(column.to_numpy(), dtype=np.int64)


def _ids(path: Path) -> IntArray:
    ids = np.sort(_numeric(_project(path, ["id"])["id"]))
    if np.any(ids <= 0) or np.any(ids[1:] == ids[:-1]):
        raise ValueError(f"IDs must be positive and unique: {path}")
    return ids


def _check_members(ids: IntArray, values: IntArray) -> IntArray:
    positions = np.searchsorted(ids, values)
    if len(values) and (not len(ids) or np.any(positions >= len(ids))):
        raise ValueError("Unresolved relationship ID")
    if not np.array_equal(ids[positions], values):
        raise ValueError("Unresolved relationship ID")
    return positions


def _lists(ids: IntArray, keys: IntArray, values: IntArray) -> pa.ListArray:
    """Build sorted CSR adjacency with numeric workspace, not Python row objects."""
    positions = _check_members(ids, keys)
    order = np.lexsort((values, positions))
    positions = positions[order]
    values = values[order]
    if len(values) > 1 and np.any((positions[1:] == positions[:-1]) & (values[1:] == values[:-1])):
        raise ValueError("Duplicate relationship edge")
    offsets = np.empty(len(ids) + 1, dtype=np.int64)
    offsets[0] = 0
    np.cumsum(np.bincount(positions, minlength=len(ids)), out=offsets[1:])
    if offsets[-1] > np.iinfo(np.int32).max:
        raise ValueError("Arrow list<int64> adjacency exceeds its int32 offset capacity")
    return pa.ListArray.from_arrays(pa.array(offsets, type=pa.int32()), pa.array(values, type=pa.int64()))


def _references(path: Path, column: str) -> tuple[IntArray, IntArray]:
    table = _project(path, ["id", column])
    valid = pc.is_valid(table[column])
    return _numeric(pc.filter(table["id"], valid)), _numeric(pc.filter(table[column], valid))


def _flow(path: Path, ids: IntArray) -> tuple[IntArray, IntArray]:
    table = pq.read_table(path, columns=["id", "upstream_ids"]).combine_chunks()
    row_ids = _numeric(table["id"])
    if not np.array_equal(np.sort(row_ids), ids):
        raise ValueError(f"Graph rows do not match feature IDs: {path}")
    upstream = cast(pa.ListArray, table["upstream_ids"].chunk(0))
    if upstream.null_count or upstream.values.null_count:
        raise ValueError("Flow lists and their IDs must not be null")
    values = np.asarray(upstream.values.to_numpy(), dtype=np.int64)
    _check_members(ids, values)
    lengths = np.diff(upstream.offsets.to_numpy())
    return np.repeat(row_ids, lengths), values


def _write(
    output: Path, domain: str, ids: IntArray, columns: dict[str, pa.ListArray], batch_rows: int
) -> dict[str, object]:
    data = f"{domain}-relationships.arrow"
    directory = f"{domain}-relationships-directory.json"
    schema = pa.schema(
        [pa.field("id", pa.int64(), nullable=False)]
        + [pa.field(name, pa.list_(pa.int64()), nullable=False) for name in columns]
    )
    table = pa.table({"id": pa.array(ids), **columns}, schema=schema)
    batches: list[dict[str, int]] = []
    with ipc.new_file(str(output / data), schema) as writer:
        for start in range(0, len(ids), batch_rows):
            rows = min(batch_rows, len(ids) - start)
            writer.write_table(table.slice(start, rows))
            batches.append(
                {"batch": len(batches), "min_id": int(ids[start]), "max_id": int(ids[start + rows - 1]), "rows": rows}
            )
    (output / directory).write_text(json.dumps({"version": 1, "batches": batches}) + "\n")
    return {"data": data, "directory": directory, "count": len(ids), "batch_rows": batch_rows}


def _feature_artifacts(
    domain: str, bindings: dict[str, dict[str, str]], families: Mapping[str, Mapping[str, object]]
) -> dict[str, dict[str, str]]:
    domains = {domain}
    for binding in bindings.values():
        domains.update((binding["source_domain"], binding["target_domain"]))
    artifacts: dict[str, dict[str, str]] = {}
    for name in sorted(domains):
        family = families[name]
        data, digest = family["data"], family["data_sha256"]
        if not isinstance(data, str) or not isinstance(digest, str):
            raise ValueError(f"{name} feature artifact binding must contain string paths and hashes")
        artifacts[name] = {"data": data, "data_sha256": digest}
    return artifacts


def build_relationships(
    source: Path,
    output: Path,
    families: Mapping[str, Mapping[str, object]],
    batch_rows: int = 8192,
) -> dict[str, object]:
    """Publish ID-sorted immediate neighbors and range directories in an existing directory.

    Final feature paths and fingerprints are copied from the caller's family
    declarations. Source artifacts retain their original meanings and provenance.
    The caller verifies artifact fingerprints. No source geometry is read here.
    """
    if batch_rows <= 0:
        raise ValueError("batch_rows must be positive")
    ids = {domain: _ids(source / filename) for domain, filename in _FILES.items()}
    declarations: dict[str, object] = {}
    for domain in _FILES:
        columns: dict[str, pa.ListArray] = {}
        bindings = _bindings(domain)
        if domain != "river_nodes":
            graph = "graph.parquet" if domain == "catchments" else "river-graph.parquet"
            keys, values = _flow(source / graph, ids[domain])
            for name, left, right in (
                ("upstream_ids", keys, values),
                ("downstream_ids", values, keys),
            ):
                columns[name] = _lists(ids[domain], left, right)
            del keys, values, left, right
        for origin, source_column, target, forward, reverse in _REFERENCES:
            if domain not in (origin, target):
                continue
            keys, values = _references(source / _FILES[origin], source_column)
            _check_members(ids[origin], keys)
            _check_members(ids[target], values)
            if domain == origin:
                columns[forward] = _lists(ids[domain], keys, values)
            if domain == target:
                columns[reverse] = _lists(ids[domain], values, keys)
            del keys, values
        declaration = _write(output, domain, ids[domain], columns, batch_rows)
        declaration["columns"] = bindings
        declaration["feature_artifacts"] = _feature_artifacts(domain, bindings, families)
        declaration["source_artifacts"] = _source_artifacts(domain, bindings)
        if domain == "catchments":
            manifest = json.loads((source / "manifest.json").read_text())
            declaration["connectivity"] = manifest["catchment_connectivity"]
            declaration["connectivity_source"] = "manifest.json"
        declarations[domain] = declaration
    return declarations


def _ordered_pairs(keys: IntArray, values: IntArray) -> tuple[IntArray, IntArray]:
    order = np.lexsort((values, keys))
    return keys[order], values[order]


def verify_relationships(
    source: Path,
    output: Path,
    families: Mapping[str, Mapping[str, object]],
    declarations: dict[str, object],
) -> dict[str, dict[str, object]]:
    """Expensive full source comparison, separate from ordinary selected reads.

    Expand published lists to edge pairs and compare their sorted multisets with
    independent Arrow flatten/parent-index expansion of authoritative records.
    Does not invoke CSR construction or derive flow from shared endpoints.
    Artifact fingerprint verification remains the caller's responsibility.
    """
    results: dict[str, dict[str, object]] = {}
    for domain, filename in _FILES.items():
        declaration = cast(dict[str, object], declarations[domain])
        bindings = _bindings(domain)
        if declaration["columns"] != bindings or declaration["source_artifacts"] != _source_artifacts(domain, bindings):
            raise ValueError(f"{domain} source binding mismatch")
        if declaration["feature_artifacts"] != _feature_artifacts(domain, bindings, families):
            raise ValueError(f"{domain} feature artifact binding mismatch")
        ids = _ids(source / filename)
        path = output / str(declaration["data"])
        if declaration["count"] != len(ids):
            raise ValueError(f"{domain} count mismatch")
        with ipc.open_file(str(path)) as reader:
            if reader.schema.names != ["id", *bindings]:
                raise ValueError(f"{domain} column mismatch")
            batches: list[dict[str, int]] = []
            offset = 0
            for number in range(reader.num_record_batches):
                batch = reader.get_batch(number)
                batch_ids = np.asarray(batch.column(0).to_numpy(), dtype=np.int64)
                if not len(batch_ids) or not np.array_equal(batch_ids, ids[offset : offset + len(batch_ids)]):
                    raise ValueError(f"{domain} sorted IDs mismatch")
                batches.append(
                    {"batch": number, "min_id": int(batch_ids[0]), "max_id": int(batch_ids[-1]), "rows": len(batch_ids)}
                )
                offset += len(batch_ids)
            if offset != len(ids):
                raise ValueError(f"{domain} row count mismatch")
        directory = json.loads((output / str(declaration["directory"])).read_text())
        if directory != {"version": 1, "batches": batches}:
            raise ValueError(f"{domain} directory mismatch")
        if domain == "catchments":
            manifest = json.loads((source / "manifest.json").read_text())
            if (
                declaration["connectivity"] != manifest["catchment_connectivity"]
                or declaration["connectivity_source"] != "manifest.json"
            ):
                raise ValueError("catchments connectivity source mismatch")
        counts: dict[str, int] = {}
        for name, binding in bindings.items():
            published = _project(path, ["id", name])
            lists = published[name]
            if lists.type != pa.list_(pa.int64()) or lists.null_count:
                raise ValueError(f"{domain}.{name} invalid list type or nulls")
            actual_values = _numeric(pc.list_flatten(lists))
            parents = pc.list_parent_indices(lists)
            actual_keys = _numeric(pc.take(published["id"], parents))
            artifact, column = binding["source_artifact"], binding["source_column"]
            if artifact.endswith(".parquet"):
                evidence = pq.read_table(source / artifact, columns=["id", column]).combine_chunks()
                expected_keys = _numeric(pc.take(evidence["id"], pc.list_parent_indices(evidence[column])))
                expected_values = _numeric(pc.list_flatten(evidence[column]))
            else:
                evidence = _project(source / artifact, ["id", column])
                valid = pc.is_valid(evidence[column])
                expected_keys = _numeric(pc.filter(evidence["id"], valid))
                expected_values = _numeric(pc.filter(evidence[column], valid))
            if binding["direction"] == "reverse":
                expected_keys, expected_values = expected_values, expected_keys
            actual = _ordered_pairs(actual_keys, actual_values)
            expected = _ordered_pairs(expected_keys, expected_values)
            if not all(np.array_equal(a, b) for a, b in zip(actual, expected, strict=True)):
                raise ValueError(f"{domain}.{name} differs from source")
            counts[name] = len(actual_values)
        results[domain] = {"rows": len(ids), "columns": counts}
    return results
