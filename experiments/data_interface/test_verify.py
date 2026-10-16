from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from experiments.data_interface.features import build_features
from experiments.data_interface.test_features import source_file
from experiments.data_interface.verify import verify
from hfx.candidates import fingerprint


@pytest.mark.parametrize("changed_claim", ["categorical_columns", "source_schemas"])
def test_full_verification_rejects_changed_source_meaning_or_schema_binding(tmp_path: Path, changed_claim: str) -> None:
    source, candidate = tmp_path / "source", tmp_path / "candidate"
    source.mkdir()
    candidate.mkdir()
    original = source_file(source / "rivers.arrow")
    category = {
        "artifact": "rivers.arrow",
        "column": "level",
        "physical_type": "int16",
        "codes": [{"code": 0, "meaning": "segment"}, {"code": 1, "meaning": "reach"}],
        "null_meaning": "not permitted",
    }
    upstream = {"artifacts": {"rivers.arrow": fingerprint(source / "rivers.arrow")}, "categorical_columns": [category]}
    source_bytes = json.dumps(upstream).encode()
    (source / "manifest.json").write_bytes(source_bytes)
    declaration = build_features(source / "rivers.arrow", candidate, "rivers", rows=2)
    manifest = {
        "experimental": True,
        "input_manifest_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "input_artifacts": upstream["artifacts"],
        "families": {"rivers": declaration},
        "relationships": {},
        "categorical_columns": [{**category, "artifact": declaration["data"]}],
        "source_schemas": {
            "rivers": {
                "artifact": "rivers.arrow",
                "arrow_schema_sha256": hashlib.sha256(original.schema.serialize().to_pybytes()).hexdigest(),
            }
        },
        "artifacts": {p.name: fingerprint(p) for p in candidate.iterdir()},
    }
    manifest_path = candidate / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    assert verify(source, candidate)["status"] == "passed"
    if changed_claim == "categorical_columns":
        manifest["categorical_columns"][0]["codes"] = [
            {"code": 0, "meaning": "reach"},
            {"code": 1, "meaning": "segment"},
        ]
    else:
        manifest["source_schemas"]["rivers"]["arrow_schema_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="categorical|source schema"):
        verify(source, candidate)
