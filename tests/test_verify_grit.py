"""Independent, hand-authored source expectations; no producer helpers."""

import sqlite3
import struct
from pathlib import Path
from typing import cast

import pyarrow as pa
import pytest

fiona = pytest.importorskip("fiona")
pytest.importorskip("rasterio")
pytest.importorskip("pyproj")
pytest.importorskip("shapely")

from scripts.verify_grit import compare_feature, source_schema  # noqa: E402


def original(path: Path) -> None:
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer="nodes",
        crs="EPSG:8857",
        schema={"geometry": "Point", "properties": {"global_id": "int64", "segment_node_id": "float", "label": "str"}},
    ) as target:
        target.write(
            {
                "geometry": {"type": "Point", "coordinates": (0.0, 0.0)},
                "properties": {"global_id": 1, "segment_node_id": None, "label": None},
            }
        )


def output() -> pa.RecordBatch:
    return pa.record_batch(
        [
            pa.array([1], type=pa.int64()),
            pa.array([1], type=pa.int64()),
            pa.array([None], type=pa.float64()),
            pa.array([None], type=pa.string()),
            pa.array([struct.pack("<BIdd", 1, 1, 0.0, 0.0)], type=pa.binary()),
        ],
        names=["source_fid", "source_global_id", "source_segment_node_id", "source_label", "geometry"],
    )


def test_original_nulls_types_and_independent_projected_origin(tmp_path: Path) -> None:
    path = tmp_path / "original.gpkg"
    original(path)
    schema = source_schema(path, "nodes")
    assert schema == {"fid": "INTEGER", "global_id": "INTEGER", "segment_node_id": "REAL", "label": "TEXT"}
    with fiona.open(path, layer="nodes") as source:
        feature = next(iter(source))
        assert compare_feature(feature, source.crs, schema, output(), 0) == 0.0
        changed = output().set_column(2, "source_segment_node_id", pa.array([0.0]))
        with pytest.raises(ValueError, match="source_segment_node_id"):
            compare_feature(feature, source.crs, schema, changed, 0)
        wrong_type = output().set_column(1, "source_global_id", pa.array([1.0]))
        with pytest.raises(ValueError, match="type.*source_global_id"):
            compare_feature(feature, source.crs, schema, wrong_type, 0)
        shifted = output().set_column(4, "geometry", pa.array([struct.pack("<BIdd", 1, 1, 0.001, 0.0)]))
        with pytest.raises(ValueError, match="coordinate"):
            compare_feature(feature, source.crs, schema, shifted, 0)


def test_lookup_covers_every_address_and_rejects_wrong_row(tmp_path: Path) -> None:
    import json
    import sqlite3

    import pyarrow.ipc as ipc

    from scripts.verify_grit import verify_lookup

    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE addresses (entity TEXT, id INTEGER, block INTEGER, row INTEGER, PRIMARY KEY(entity,id))")
    db.executemany("INSERT INTO addresses VALUES ('rivers',?,?,?)", [(7, 0, 0), (2, 0, 1)])
    schema = pa.schema(
        [pa.field("id", pa.int64(), False), pa.field("block", pa.int32(), False), pa.field("row", pa.int32(), False)],
        metadata={b"hfx:format_version": b"0.4.0", b"hfx:data_sha256": b"a" * 64},
    )
    lookup = tmp_path / "lookup.arrow"
    directory = tmp_path / "directory.json"
    directory.write_text(json.dumps({"version": 1, "batches": [{"batch": 0, "min_id": 2, "max_id": 7, "rows": 2}]}))

    def write(rows: list[int]) -> None:
        with ipc.new_file(str(lookup), schema) as writer:
            writer.write_batch(pa.record_batch([[2, 7], [0, 0], rows], schema=schema))

    write([1, 0])
    verify_lookup(db, "rivers", lookup, directory, "a" * 64, 2)
    write([0, 1])
    with pytest.raises(ValueError, match="address"):
        verify_lookup(db, "rivers", lookup, directory, "a" * 64, 2)


def test_branch_reconvergence_is_dag_but_cycle_fails(tmp_path: Path) -> None:
    from scripts.verify_grit import prepare_database, verify_dag

    with prepare_database(tmp_path / "audit.sqlite") as db:
        for identifier in (1, 2, 3, 4):
            db.execute(
                "INSERT INTO features(entity,id,namespace,source_id,level) VALUES ('rivers',?,'test',?,0)",
                (identifier, str(identifier)),
            )
        db.executemany("INSERT INTO edges VALUES ('rivers',?,?)", [(1, 2), (1, 3), (2, 4), (3, 4)])
        verify_dag(db, "rivers")
        db.execute("INSERT INTO edges VALUES ('rivers',4,1)")
        with pytest.raises(ValueError, match="cycle"):
            verify_dag(db, "rivers")


def test_reference_requires_original_target_and_strictly_coarser_level(tmp_path: Path) -> None:
    from scripts.verify_grit import check_reference, prepare_database

    with prepare_database(tmp_path / "relations.sqlite") as db:
        db.execute("INSERT INTO features(entity,id,namespace,source_id,level) VALUES ('rivers',10,'segments','1',0)")
        record: dict[str, object] = {"id": 20, "level": 1, "parent_id": 10}
        check_reference(db, record, "parent_id", "rivers", "segments", 1, coarser=True)
        record["parent_id"] = 20
        with pytest.raises(ValueError, match="relationship"):
            check_reference(db, record, "parent_id", "rivers", "segments", 1, coarser=True)
        record.update(parent_id=10, level=0)
        with pytest.raises(ValueError, match="strictly coarser"):
            check_reference(db, record, "parent_id", "rivers", "segments", 1, coarser=True)


def test_failed_verification_never_emits_success_receipt(tmp_path: Path) -> None:
    import json

    from scripts.verify_grit import verify

    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"sources": []}))
    report = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="originals"):
        verify(inventory, tmp_path / "output", report, tmp_path / "scratch.sqlite")
    assert not report.exists()
    report.write_text("retained old receipt")
    with pytest.raises(ValueError, match="new and outside"):
        verify(inventory, tmp_path / "output", report, tmp_path / "scratch.sqlite")
    assert report.read_text() == "retained old receipt"


def complete_fixture(root: Path, *, isolated_node: bool = False) -> tuple[Path, Path]:
    """Seven original layers and hand-mapped outputs, independent of producer code."""
    import json

    import pyarrow.ipc as ipc
    import pyarrow.parquet as pq
    from pyproj import Transformer
    from shapely import transform
    from shapely.geometry import shape

    from hfx.verify_candidates import _fingerprint

    output_dir = root / "output"
    output_dir.mkdir()
    sources = []
    ledger_layers = []
    rows: dict[str, list[dict[str, object]]] = {"catchments": [], "rivers": [], "river_nodes": []}
    project = Transformer.from_crs(8857, 4326, always_xy=True).transform
    polygon = {"type": "Polygon", "coordinates": [[(0, 0), (50, 0), (0, 50), (0, 0)]]}
    line = {"type": "LineString", "coordinates": [(0, 0), (1, 0)]}
    point = {"type": "Point", "coordinates": (0, 0)}
    products = [
        ("component_catchments", 0),
        ("segment_catchments", 1),
        ("reach_catchments", 2),
        ("segments", 0),
        ("reaches", 1),
    ]
    for product, level in products:
        path = root / (product + ".gpkg")
        region = "GLOBAL" if product == "component_catchments" else "SP"
        sources.append({"path": str(path), "region": region, "product": product})
        layers = ("lines", "nodes") if product in {"segments", "reaches"} else (product + "__1",)
        for layer in layers:
            entity = "river_nodes" if layer == "nodes" else "rivers" if layer == "lines" else "catchments"
            attrs: dict[str, object] = {"global_id": 1}
            if product != "component_catchments" and layer != "nodes":
                attrs["catchment_id"] = 1
            if product in {"reaches", "reach_catchments"} and layer != "nodes":
                attrs["segment_id"] = 1
            if layer == "lines":
                attrs.update(upstream_node_id=1, downstream_node_id=1, upstream_line_ids="", downstream_line_ids="")
            if layer == "nodes":
                attrs.update(upstream_line_ids="1", downstream_line_ids="1")
                if product == "reaches":
                    attrs["segment_node_id"] = 1.0
            types = {
                key: "str" if isinstance(value, str) else "float" if isinstance(value, float) else "int64"
                for key, value in attrs.items()
            }
            geometry = point if layer == "nodes" else line if layer == "lines" else polygon
            with fiona.open(
                path,
                "w",
                driver="GPKG",
                layer=layer,
                crs="EPSG:8857",
                schema={"geometry": geometry["type"], "properties": types},
            ) as target:
                target.write({"geometry": geometry, "properties": attrs})
                if isolated_node and product == "reaches" and layer == "nodes":
                    target.write(
                        {
                            "geometry": geometry,
                            "properties": {
                                **attrs,
                                "global_id": 2,
                                "upstream_line_ids": None,
                                "downstream_line_ids": None,
                            },
                        }
                    )
            geom = transform(shape(geometry), project, interleaved=False)
            # A 50 m right triangle in an equal-area CRS has 1,250 m² area.
            # At this scale the geodesic-edge correction rounds away in float32;
            # unlike the former 1 m fixture, numerical cancellation does too.
            identifier = level + 1
            row: dict[str, object] = {
                "id": identifier,
                "level": level,
                "source_namespace": f"grit:1.0:{region}:{product}:{layer}",
                "source_id": "1",
                "geometry": geom.wkb,
                "bbox": {"xmin": 0.0, "ymin": 0.0, "xmax": 0.001, "ymax": 0.001},
                "source_fid": 1,
                **{"source_" + key: value for key, value in attrs.items()},
            }
            if entity == "catchments":
                row.update(
                    parent_id=None if level == 0 else level,
                    area_km2=0.00125,
                    up_area_km2=None,
                    outlet_lon=None if level == 0 else 0.0,
                    outlet_lat=None if level == 0 else 0.0,
                )
            elif entity == "rivers":
                row.update(
                    parent_id=None if level == 0 else 1,
                    local_catchment_id=level + 2,
                    component_catchment_id=1,
                    upstream_node_id=level + 1,
                    downstream_node_id=level + 1,
                    geometry_orientation=0,
                )
            else:
                row["coarser_node_id"] = None if level == 0 else 1
            rows[entity].append(row)
            if isolated_node and product == "reaches" and layer == "nodes":
                rows[entity].append(
                    {
                        **row,
                        "id": 3,
                        "source_id": "2",
                        "source_fid": 2,
                        "source_global_id": 2,
                        "source_upstream_line_ids": None,
                        "source_downstream_line_ids": None,
                    }
                )
            ledger_layers.append(
                {
                    "namespace": row["source_namespace"],
                    "product": product,
                    "region": region,
                    "table": layer,
                    "count": 2 if isolated_node and product == "reaches" and layer == "nodes" else 1,
                    "fields": [{"name": "fid", "type": "INTEGER", "nullable": False, "output": "source_fid"}]
                    + [
                        {
                            "name": name,
                            "type": {"int64": "INTEGER", "float": "REAL", "str": "TEXT"}[kind],
                            "nullable": True,
                            "output": "source_" + name,
                        }
                        for name, kind in types.items()
                    ],
                }
            )
    inventory = root / "inventory.json"
    inventory.write_text(json.dumps({"sources": sources}))
    (output_dir / "source-provenance.json").write_text(
        json.dumps({"inventory": {"sources": sources}, "layers": ledger_layers})
    )
    declarations = {}
    for entity, records in rows.items():
        names = sorted(set().union(*(record.keys() for record in records)))
        fields = []
        for name in names:
            values = [record.get(name) for record in records]
            if name in {"level"}:
                kind = pa.int16()
            elif name == "geometry_orientation":
                kind = pa.int8()
            elif name in {"source_namespace", "source_id"} or any(
                isinstance(value, str) for value in values if value is not None
            ):
                kind = pa.string()
            elif name == "geometry":
                kind = pa.binary()
            elif name == "bbox":
                kind = pa.struct([pa.field(key, pa.float32(), False) for key in ("xmin", "ymin", "xmax", "ymax")])
            elif name in {"area_km2", "up_area_km2"}:
                kind = pa.float32()
            elif name in {"outlet_lon", "outlet_lat", "source_segment_node_id"}:
                kind = pa.float64()
            else:
                kind = pa.int64()
            fields.append(
                pa.field(
                    name,
                    kind,
                    name
                    not in {
                        "id",
                        "level",
                        "source_namespace",
                        "source_id",
                        "geometry",
                        "bbox",
                        "area_km2",
                        "geometry_orientation",
                    },
                )
            )
        schema = pa.schema(fields)
        data = entity + ".arrow"
        batch = pa.RecordBatch.from_pylist(records, schema=schema)
        with ipc.new_file(str(output_dir / data), schema, options=ipc.IpcWriteOptions(compression="zstd")) as writer:
            writer.write_batch(batch)
        lookup, directory = entity + "-lookup.arrow", entity + "-directory.json"
        binding = b"hfx:catchments_sha256" if entity == "catchments" else b"hfx:data_sha256"
        lookup_schema = pa.schema(
            [
                pa.field("id", pa.int64(), False),
                pa.field("block", pa.int32(), False),
                pa.field("row", pa.int32(), False),
            ],
            metadata={b"hfx:format_version": b"0.4.0", binding: _fingerprint(output_dir / data)["sha256"].encode()},
        )
        with ipc.new_file(str(output_dir / lookup), lookup_schema) as writer:
            writer.write_batch(
                pa.record_batch(
                    [list(range(1, len(records) + 1)), [0] * len(records), list(range(len(records)))],
                    schema=lookup_schema,
                )
            )
        (output_dir / directory).write_text(
            json.dumps(
                {"version": 1, "batches": [{"batch": 0, "min_id": 1, "max_id": len(records), "rows": len(records)}]}
            )
        )
        declarations[entity] = {
            "data": data,
            "lookup": lookup,
            "directory": directory,
            "count": len(records),
            "batch_bytes": 8388608,
            "index_batch_rows": 65536,
        }
        if entity != "river_nodes":
            graph = entity + "-graph.parquet"
            graph_rows = [
                {
                    "id": r["id"],
                    "level": r["level"],
                    "upstream_ids": [],
                    "bbox_minx": 0.0,
                    "bbox_miny": 0.0,
                    "bbox_maxx": pa.scalar(0.001, pa.float32()).as_py(),
                    "bbox_maxy": pa.scalar(0.001, pa.float32()).as_py(),
                }
                for r in records
            ]
            graph_schema = pa.schema(
                [
                    pa.field("id", pa.int64(), False),
                    pa.field("level", pa.int16(), False),
                    pa.field("upstream_ids", pa.list_(pa.field("item", pa.int64(), False)), False),
                ]
                + [pa.field(name, pa.float32(), False) for name in ("bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy")]
            )
            pq.write_table(pa.Table.from_pylist(graph_rows, schema=graph_schema), output_dir / graph)
            declarations[entity]["graph"] = graph
            declarations[entity]["topology"] = "dag"
    catch = declarations["catchments"]
    manifest = {
        "format_version": "0.4.0",
        "crs": "EPSG:4326",
        "has_up_area": False,
        "catchments": catch["data"],
        "lookup": catch["lookup"],
        "directory": catch["directory"],
        "graph": catch["graph"],
        "unit_count": 3,
        "topology": "dag",
        "catchment_batch_bytes": 8388608,
        "index_batch_rows": 65536,
        "catchment_connectivity": [
            {"level": 0, "status": "not_supplied"},
            {"level": 1, "status": "supplied"},
            {"level": 2, "status": "supplied"},
        ],
        "rivers": declarations["rivers"],
        "river_nodes": declarations["river_nodes"],
        "artifacts": {path.name: _fingerprint(path) for path in output_dir.iterdir()},
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest))
    return inventory, output_dir


def test_complete_verification_accepts_null_incidence_on_isolated_source_node(tmp_path: Path) -> None:
    from scripts.verify_grit import verify

    # Synthetic analogue of native SI reach nodes 430001282 and 580018839:
    # nullable TEXT incidence, no line endpoints, and a retained coarser node.
    inventory, output_dir = complete_fixture(tmp_path, isolated_node=True)
    result = verify(inventory, output_dir, tmp_path / "receipt.json", tmp_path / "audit.sqlite")
    assert result["status"] == "passed"
    assert cast(list[dict[str, object]], result["layers"])[-1]["count"] == 2


@pytest.mark.parametrize("value", [False, 0, [], "0", "-1", "1,1", "invalid"])
def test_source_incidence_rejects_invalid_or_duplicate_ids(value: object) -> None:
    from scripts.verify_grit import source_ids

    with pytest.raises(ValueError):
        source_ids(value)


@pytest.mark.parametrize("endpoint", ["upstream_node_id", "downstream_node_id"])
def test_null_incidence_cannot_hide_connected_line(tmp_path: Path, endpoint: str) -> None:
    from scripts.verify_grit import equal_tables, prepare_database, relationships

    record: dict[str, object] = {
        "id": 1,
        "level": 0,
        "coarser_node_id": None,
        "source_upstream_line_ids": None,
        "source_downstream_line_ids": None,
    }
    with prepare_database(tmp_path / "incidence.sqlite") as db:
        relationships(db, "river_nodes", "segments", "SI", record)
        assert db.execute("SELECT * FROM expected_incidence").fetchall() == []
        db.execute("INSERT INTO incidence VALUES (1,2,?)", (endpoint,))
        with pytest.raises(ValueError, match="incidence"):
            equal_tables(db, "incidence", "expected_incidence", "node,river,endpoint")


def test_null_incidence_source_attribute_cannot_be_replaced_with_empty_text() -> None:
    feature = {
        "id": "1",
        "properties": {"upstream_line_ids": None},
        "geometry": {"type": "Point", "coordinates": (0.0, 0.0)},
    }
    batch = pa.record_batch(
        [[1], pa.array([None], pa.string()), [struct.pack("<BIdd", 1, 1, 0.0, 0.0)]],
        names=["source_fid", "source_upstream_line_ids", "geometry"],
    )
    schema = {"fid": "INTEGER", "upstream_line_ids": "TEXT"}
    assert compare_feature(feature, "EPSG:4326", schema, batch, 0) == 0.0
    changed = batch.set_column(1, "source_upstream_line_ids", pa.array([""], pa.string()))
    with pytest.raises(ValueError, match="source_upstream_line_ids"):
        compare_feature(feature, "EPSG:4326", schema, changed, 0)


def test_complete_original_bundle_and_success_receipt(tmp_path: Path) -> None:
    import json

    from scripts.verify_grit import verify

    inventory, output_dir = complete_fixture(tmp_path)
    report = tmp_path / "receipt.json"
    result = verify(inventory, output_dir, report, tmp_path / "audit.sqlite")
    assert result["status"] == "passed"
    assert json.loads(report.read_text())["maximum_coordinate_error_degrees"] <= 1e-9
    assert [row["count"] for row in cast(list[dict[str, object]], result["layers"])] == [1] * 7


def test_complete_verification_rejects_unbound_file(tmp_path: Path) -> None:
    from scripts.verify_grit import verify

    inventory, output_dir = complete_fixture(tmp_path)
    (output_dir / "scratch.sqlite").write_bytes(b"unpublished scratch")
    report = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="coverage/fingerprints"):
        verify(inventory, output_dir, report, tmp_path / "audit.sqlite")
    assert not report.exists()


def test_complete_verification_rejects_rehashed_source_attribute_corruption(tmp_path: Path) -> None:
    import json

    import pyarrow.ipc as ipc

    from hfx.verify_candidates import _fingerprint
    from scripts.verify_grit import verify

    inventory, output_dir = complete_fixture(tmp_path)
    path = output_dir / "rivers.arrow"
    with pa.OSFile(str(path), "r") as mapped:
        reader = ipc.open_file(mapped)
        batch = reader.get_batch(0)
    index = batch.schema.get_field_index("source_catchment_id")
    changed = batch.set_column(index, batch.schema.field(index), pa.array([99, 1], pa.int64()))
    with ipc.new_file(str(path), changed.schema, options=ipc.IpcWriteOptions(compression="zstd")) as writer:
        writer.write_batch(changed)
    lookup = output_dir / "rivers-lookup.arrow"
    with pa.OSFile(str(lookup), "r") as mapped:
        reader = ipc.open_file(mapped)
        address = reader.get_batch(0)
    metadata = dict(address.schema.metadata)
    metadata[b"hfx:data_sha256"] = _fingerprint(path)["sha256"].encode()
    address = address.replace_schema_metadata(metadata)
    with ipc.new_file(str(lookup), address.schema) as writer:
        writer.write_batch(address)
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for changed_path in (path, lookup):
        manifest["artifacts"][changed_path.name] = _fingerprint(changed_path)
    manifest_path.write_text(json.dumps(manifest))
    report = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="source_catchment_id"):
        verify(inventory, output_dir, report, tmp_path / "audit.sqlite")
    assert not report.exists()


def test_equal_earth_inverse_uses_exact_authalic_latitude(tmp_path: Path) -> None:
    # PROJ 9.7 replaced the truncated series inverse. Forward projection of this
    # current inverse returns (11236125,784905) to sub-nanometre precision.
    from scripts.verify_grit import compare_feature

    feature = {"id": "1", "properties": {}, "geometry": {"type": "Point", "coordinates": (11236125.0, 784905.0)}}
    batch = pa.record_batch(
        [
            pa.array([1], pa.int64()),
            pa.array([struct.pack("<BIdd", 1, 1, 117.60450975051961, 6.114612003328459)], pa.binary()),
        ],
        names=["source_fid", "geometry"],
    )
    assert compare_feature(feature, "EPSG:8857", {"fid": "INTEGER"}, batch, 0) <= 1e-9


def test_schema_ledger_preserves_nullable_source_declaration(tmp_path: Path) -> None:
    from scripts.verify_grit import verify_ledger

    path = tmp_path / "original.gpkg"
    original(path)
    inventory = {"sources": [{"path": str(path), "product": "segments", "region": "SP"}]}
    observed = [
        {
            "namespace": "grit:1.0:SP:segments:nodes",
            "count": 1,
            "fields": {"fid": "INTEGER", "global_id": "INTEGER", "segment_node_id": "REAL", "label": "TEXT"},
        }
    ]
    ledger = {
        "inventory": inventory,
        "layers": [
            {
                "namespace": "grit:1.0:SP:segments:nodes",
                "product": "segments",
                "region": "SP",
                "table": "nodes",
                "count": 1,
                "fields": [
                    {"name": name, "type": kind, "nullable": name != "fid", "output": "source_" + name}
                    for name, kind in observed[0]["fields"].items()
                ],
            }
        ],
    }
    verify_ledger(
        cast(dict[str, object], inventory), cast(dict[str, object], ledger), cast(list[dict[str, object]], observed)
    )
    ledger["layers"][0]["fields"][2]["nullable"] = False
    with pytest.raises(ValueError, match="source schema ledger"):
        verify_ledger(
            cast(dict[str, object], inventory), cast(dict[str, object], ledger), cast(list[dict[str, object]], observed)
        )


def test_group_budget_rejects_coherently_rebatched_values(tmp_path: Path) -> None:
    from scripts.verify_grit import verify_group_batches

    schema = pa.schema([pa.field("id", pa.int64()), pa.field("payload", pa.binary())])
    incoming = pa.RecordBatch.from_pylist(
        [{"id": 1, "payload": b"a" * 20}, {"id": 2, "payload": b"b" * 20}, {"id": 3, "payload": b"c" * 20}],
        schema=schema,
    )
    budget = incoming.slice(0, 2).nbytes
    assert incoming.slice(0, 3).nbytes > budget
    verify_group_batches(incoming, [2, 1], budget)
    with pytest.raises(ValueError, match="maximal"):
        verify_group_batches(incoming, [1, 2], budget)
    with pytest.raises(ValueError, match="budget"):
        verify_group_batches(incoming, [3], budget)


def test_rebatched_bundle_with_fresh_lookup_and_hashes_is_rejected(tmp_path: Path) -> None:
    import json

    import pyarrow.ipc as ipc

    from hfx.verify_candidates import _fingerprint
    from scripts.verify_grit import verify

    inventory, output_dir = complete_fixture(tmp_path)
    path = output_dir / "rivers.arrow"
    with pa.OSFile(str(path), "r") as mapped:
        batch = ipc.open_file(mapped).get_batch(0)
    with ipc.new_file(str(path), batch.schema, options=ipc.IpcWriteOptions(compression="zstd")) as writer:
        writer.write_batch(batch.slice(0, 1))
        writer.write_batch(batch.slice(1, 1))
    lookup = output_dir / "rivers-lookup.arrow"
    with pa.OSFile(str(lookup), "r") as mapped:
        schema = ipc.open_file(mapped).schema
    metadata = dict(schema.metadata)
    metadata[b"hfx:data_sha256"] = _fingerprint(path)["sha256"].encode()
    schema = schema.with_metadata(metadata)
    with ipc.new_file(str(lookup), schema) as writer:
        writer.write_batch(pa.record_batch([[1, 2], [0, 1], [0, 0]], schema=schema))
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for changed in (path, lookup):
        manifest["artifacts"][changed.name] = _fingerprint(changed)
    manifest_path.write_text(json.dumps(manifest))
    report = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="maximal"):
        verify(inventory, output_dir, report, tmp_path / "audit.sqlite")
    assert not report.exists()


def test_graph_schema_rejects_inferred_int64_levels_and_null_edges(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    from scripts.verify_grit import prepare_database, verify_graph

    graph = tmp_path / "graph.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "id": 1,
                    "level": 0,
                    "upstream_ids": [],
                    "bbox_minx": 0.0,
                    "bbox_miny": 0.0,
                    "bbox_maxx": 1.0,
                    "bbox_maxy": 1.0,
                }
            ]
        ),
        graph,
    )
    with prepare_database(tmp_path / "audit.sqlite") as db, pytest.raises(ValueError, match="structural schema"):
        verify_graph(db, "rivers", graph)


def test_required_parent_type_and_nonnull_values_are_enforced(tmp_path: Path) -> None:
    import pyarrow.ipc as ipc

    from scripts.verify_grit import prepare_database, stage_output

    _, output_dir = complete_fixture(tmp_path)
    path = output_dir / "rivers.arrow"
    with pa.OSFile(str(path), "r") as mapped:
        batch = ipc.open_file(mapped).get_batch(0)
    index = batch.schema.get_field_index("parent_id")
    wrong = batch.set_column(index, pa.field("parent_id", pa.float64()), pa.array([None, 1.0], pa.float64()))
    with ipc.new_file(str(path), wrong.schema, options=ipc.IpcWriteOptions(compression="zstd")) as writer:
        writer.write_batch(wrong)
    with prepare_database(tmp_path / "type.sqlite") as db, pytest.raises(ValueError, match="structural schema"):
        stage_output(db, "rivers", path)
    index = batch.schema.get_field_index("geometry_orientation")
    wrong = batch.set_column(index, batch.schema.field(index), pa.array([None, 0], pa.int8()))
    with ipc.new_file(str(path), wrong.schema, options=ipc.IpcWriteOptions(compression="zstd")) as writer:
        writer.write_batch(wrong)
    with prepare_database(tmp_path / "null.sqlite") as db, pytest.raises(ValueError, match="nonnull"):
        stage_output(db, "rivers", path)


def test_manifest_storage_and_topology_declarations_are_checked(tmp_path: Path) -> None:
    import json

    from scripts.verify_grit import verify

    inventory, output_dir = complete_fixture(tmp_path)
    path = output_dir / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["rivers"].update(batch_bytes=1, index_batch_rows=1, topology="not-a-topology")
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="declaration"):
        verify(inventory, output_dir, tmp_path / "receipt.json", tmp_path / "audit.sqlite")


@pytest.mark.parametrize("mutation", ["inventory", "extra-artifact"])
def test_receipt_rejects_inputs_or_output_set_changed_during_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    from scripts import verify_grit

    inventory, output_dir = complete_fixture(tmp_path)
    original_check = verify_grit.verify_categories

    def mutate(
        db: sqlite3.Connection,
        manifest: dict[str, object],
        schemas: dict[str, pa.Schema],
        declarations: dict[str, dict[str, object]],
    ) -> None:
        original_check(db, manifest, schemas, declarations)
        if mutation == "inventory":
            inventory.write_text(inventory.read_text() + "\n")
        else:
            (output_dir / "late-file.txt").write_text("unbound")

    monkeypatch.setattr(verify_grit, "verify_categories", mutate)
    report = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="changed during"):
        verify_grit.verify(inventory, output_dir, report, tmp_path / "audit.sqlite")
    assert not report.exists()


def test_declared_tree_and_unsupplied_levels_cannot_hide_edges(tmp_path: Path) -> None:
    from scripts.verify_grit import prepare_database, verify_declared_connectivity

    with prepare_database(tmp_path / "audit.sqlite") as db:
        for identifier in (1, 2, 3):
            db.execute(
                "INSERT INTO features(entity,id,namespace,source_id,level) VALUES ('catchments',?,'synthetic',?,0)",
                (identifier, str(identifier)),
            )
        db.executemany("INSERT INTO edges VALUES ('catchments',?,?)", [(1, 2), (1, 3)])
        manifest: dict[str, object] = {
            "topology": "dag",
            "rivers": {"topology": "dag"},
            "catchment_connectivity": [{"level": 0, "status": "supplied"}],
        }
        verify_declared_connectivity(db, manifest)
        manifest["topology"] = "tree"
        with pytest.raises(ValueError, match="multiple downstream"):
            verify_declared_connectivity(db, manifest)
        manifest["topology"] = "dag"
        manifest["catchment_connectivity"] = [{"level": 0, "status": "not_supplied"}]
        with pytest.raises(ValueError, match="not_supplied"):
            verify_declared_connectivity(db, manifest)
        manifest["catchment_connectivity"] = []
        with pytest.raises(ValueError, match="coverage"):
            verify_declared_connectivity(db, manifest)


def test_graph_and_bbox_actual_nonnull_children_are_checked() -> None:
    from scripts.verify_grit import check_nonnull

    graph_schema = pa.schema(
        [
            pa.field("id", pa.int64(), False),
            pa.field("level", pa.int16(), False),
            pa.field("upstream_ids", pa.list_(pa.field("item", pa.int64(), False)), False),
        ]
        + [pa.field(name, pa.float32(), False) for name in ("bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy")]
    )
    graph = pa.RecordBatch.from_pylist(
        [{"id": 1, "level": 0, "upstream_ids": [None], "bbox_minx": 0, "bbox_miny": 0, "bbox_maxx": 1, "bbox_maxy": 1}],
        schema=graph_schema,
    )
    with pytest.raises(ValueError, match="nonnull graph edge"):
        check_nonnull(graph, "graph")


def raster_declarations() -> dict[str, object]:
    """Expected declarations from the published raster delivery, not producer helpers."""
    import json

    receipt = json.loads((Path(__file__).parents[1] / "scripts/provenance/grit-raster-delivery.json").read_text())
    return {
        "external_artifacts": {
            "grit-flow-" + kind: {
                "url": "https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0/aux/d8/flow_" + kind + ".tif",
                **{
                    key: receipt["artifacts"][f"aux/d8/flow_{kind}.tif"][key]
                    for key in ("size_bytes", "sha256", "head_sha256", "tail_sha256")
                },
                "retention": "The GRIT HFX publisher retains this exact public object unchanged for the lifetime of this dependent bundle.",
            }
            for kind in ("dir", "acc")
        },
        "auxiliary": [
            {
                "schema": "hfx.aux.d8_raster.v2",
                "artifacts": {"flow_dir": {"external": "grit-flow-dir"}, "flow_acc": {"external": "grit-flow-acc"}},
                "metadata": {"crs": "EPSG:8857", "flow_dir_encoding": "grass", "flow_acc_units": "km2"},
            }
        ],
    }


def test_external_declarations_require_opt_in_and_record_receipt(tmp_path: Path) -> None:
    import json

    from hfx.verify_candidates import _fingerprint
    from scripts.verify_grit import verify

    inventory, output_dir = complete_fixture(tmp_path)
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update(raster_declarations())
    manifest_path.write_text(json.dumps(manifest))
    report = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="local verification mode"):
        verify(inventory, output_dir, report, tmp_path / "audit.sqlite")
    assert not report.exists()
    source_receipt = Path(__file__).parents[1] / "scripts/provenance/grit-raster-delivery.json"
    result = verify(inventory, output_dir, report, tmp_path / "audit.sqlite", external_raster_receipt=source_receipt)
    external = cast(dict[str, object], result["external_rasters"])
    assert external["receipt"] == {"path": str(source_receipt.resolve()), **_fingerprint(source_receipt)}
    assert external["status"] == "declarations match supplied receipt"
    assert external["limitation"] == "No fresh full raster scan or public accessibility check."


@pytest.mark.parametrize(
    "field", ["size_bytes", "sha256", "head_sha256", "tail_sha256", "url", "retention", "auxiliary"]
)
def test_external_declaration_mutation_rejected(tmp_path: Path, field: str) -> None:
    import json

    from scripts.verify_grit import verify

    inventory, output_dir = complete_fixture(tmp_path)
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update(raster_declarations())
    if field == "auxiliary":
        manifest["auxiliary"][0]["metadata"]["flow_acc_units"] = "cells"
    else:
        manifest["external_artifacts"]["grit-flow-dir"][field] = "changed"
    manifest_path.write_text(json.dumps(manifest))
    report = tmp_path / "receipt.json"
    source_receipt = Path(__file__).parents[1] / "scripts/provenance/grit-raster-delivery.json"
    with pytest.raises(ValueError, match="raster declarations differ"):
        verify(inventory, output_dir, report, tmp_path / "audit.sqlite", external_raster_receipt=source_receipt)
    assert not report.exists()


def test_dag_verification_has_bounded_sqlite_work(tmp_path: Path) -> None:
    from scripts.verify_grit import prepare_database, verify_dag

    with prepare_database(tmp_path / "large-dag.sqlite") as db:
        db.executemany(
            "INSERT INTO features(entity,id,namespace,source_id,level) VALUES ('rivers',?,'test',?,0)",
            [(identifier, str(identifier)) for identifier in range(1, 2001)],
        )
        db.executemany("INSERT INTO edges VALUES ('rivers',?,?)", [(i, i + 1) for i in range(1, 2000)])
        calls = 0

        def work_limit() -> int:
            nonlocal calls
            calls += 1
            # One million VM steps allows ample indexed work, but not a scan
            # of every river edge for each of the 2,000 feature rows.
            return int(calls > 1000)

        db.set_progress_handler(work_limit, 1000)
        try:
            verify_dag(db, "rivers")
        finally:
            db.set_progress_handler(None, 0)


def test_grouping_streams_source_order_without_sorting_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from scripts import verify_grit

    # Source order differs from ID order at every key, including numeric FIDs.
    ordered = [
        (60, "segments", "AF", "lines", 2),
        (50, "segments", "AF", "lines", 10),
        (40, "segments", "AF", "other_lines", 1),
        (30, "segments", "SP", "lines", 1),
        (20, "reaches", "AF", "lines", 1),
    ]
    expected = [
        {"source_fid": fid, "label": None if identifier == 40 else str(identifier), "geometry": bytes([identifier])}
        for identifier, _, _, _, fid in ordered
    ]
    schema = pa.schema([("source_fid", pa.int64()), ("label", pa.string()), ("geometry", pa.binary())])
    batches: list[pa.RecordBatch] = []
    original_check = verify_grit.verify_group_batches

    def check_batch(batch: pa.RecordBatch, sizes: list[int]) -> None:
        original_check(batch, sizes)
        batches.append(batch)

    monkeypatch.setattr(verify_grit, "verify_group_batches", check_batch)
    with verify_grit.prepare_database(tmp_path / "grouping.sqlite") as db:
        for row, (identifier, product, region, layer, fid) in enumerate(ordered):
            db.execute(
                "INSERT INTO features(entity,id,namespace,source_id,level,attrs,geometry) VALUES (?,?,?,?,?,?,?)",
                (
                    "rivers",
                    identifier,
                    f"grit:1.0:{region}:{product}:{layer}",
                    str(identifier),
                    0,
                    json.dumps({"source_fid": fid, "label": expected[row]["label"]}),
                    expected[row]["geometry"],
                ),
            )
            db.execute("INSERT INTO addresses VALUES ('rivers',?,0,?)", (identifier, row))
        statements: list[str] = []
        db.set_trace_callback(statements.append)
        verify_grit.verify_grouping(db, "rivers", schema)
        db.set_trace_callback(None)
        assert pa.Table.from_batches(batches).to_pylist() == expected
        # Inspect the executed payload query, not a separately copied query.
        queries = [sql for sql in statements if sql.lstrip().startswith("SELECT") and "FROM source_order" in sql]
        assert len(queries) == 1
        plan = db.execute("EXPLAIN QUERY PLAN " + queries[0]).fetchall()
        assert not any("TEMP B-TREE" in step[3] for step in plan), plan
        opcodes = db.execute("EXPLAIN " + queries[0]).fetchall()
        assert not any(step[1].startswith("Sorter") for step in opcodes), opcodes
