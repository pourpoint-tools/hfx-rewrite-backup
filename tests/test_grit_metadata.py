"""GRIT metadata preserves native codes, types and independent raster identities."""

import json
from pathlib import Path
from typing import cast

import pyarrow as pa
import pytest

pytest.importorskip("numpy")
pytest.importorskip("pyproj")
pytest.importorskip("shapely")

from scripts.produce_grit import native_categories


def test_native_node_dictionary_preserves_underspecified_outlet() -> None:
    schema = pa.schema([pa.field("source_node_type", pa.string())])
    [category] = native_categories("river-nodes.arrow", schema)
    assert category["artifact"] == "river-nodes.arrow"
    assert category["physical_type"] == "string"
    codes = {entry["code"]: entry["meaning"] for entry in category["codes"]}
    assert set(codes) == {
        "bifurcation",
        "confluence",
        "inlet",
        "coastal_outlet",
        "sink_outlet",
        "grwl_change",
        "outlet",
    }
    assert "undocumented" in codes["outlet"]
    assert "not inferred" in codes["confluence"]
    assert "absent" in category["null_meaning"]
    assert "source null" in category["null_meaning"]


def test_flags_keep_integer_codes_and_omit_absent_fields() -> None:
    schema = pa.schema([pa.field("source_continuity_violated", pa.int64())])
    [category] = native_categories("river-nodes.arrow", schema)
    assert category["column"] == "source_continuity_violated"
    assert category["physical_type"] == "int64"
    assert category["codes"] == [
        {"code": 0, "meaning": "Source reports flow continuity not violated."},
        {"code": 1, "meaning": "Source reports flow continuity violated."},
    ]
    assert native_categories("river-nodes.arrow", pa.schema([])) == []
    with pytest.raises(ValueError, match="source_node_type"):
        native_categories("river-nodes.arrow", pa.schema([pa.field("source_node_type", pa.int64())]))


def test_external_rasters_bind_verified_objects_only_for_production() -> None:
    from scripts.produce_grit import external_rasters

    assert external_rasters(production=False) == {"auxiliary": []}
    fragment = external_rasters(production=True)
    assert fragment["auxiliary"] == [
        {
            "schema": "hfx.aux.d8_raster.v2",
            "artifacts": {
                "flow_dir": {"external": "grit-flow-dir"},
                "flow_acc": {"external": "grit-flow-acc"},
            },
            "metadata": {"crs": "EPSG:8857", "flow_dir_encoding": "grass", "flow_acc_units": "km2"},
        }
    ]
    expected = json.loads((Path(__file__).parents[1] / "docs/v0.4.0/receipts/grit-raster-delivery.json").read_text())
    objects = cast(dict[str, dict[str, object]], fragment["external_artifacts"])
    assert set(objects) == {"grit-flow-dir", "grit-flow-acc"}
    for kind in ("dir", "acc"):
        identity = objects[f"grit-flow-{kind}"]
        path = f"aux/d8/flow_{kind}.tif"
        assert identity["url"] == "https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0/" + path
        assert (
            identity["retention"]
            == "The GRIT HFX publisher retains this exact public object unchanged for the lifetime of this dependent bundle."
        )
        for field in ("size_bytes", "sha256", "head_sha256", "tail_sha256"):
            assert identity[field] == expected["artifacts"][path][field]
    assert "artifacts" not in fragment
