"""Independent relation checks retain only one original basin at a time."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_tdx_bounded import inventory  # noqa: F401, F811

from hfx.candidates import fingerprint
from scripts import verify_tdx
from scripts.produce_tdx import produce


def rewrite(output: Path, name: str, rows: list[dict[str, object]]) -> None:
    path = output / name
    schema = pq.read_schema(path)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["artifacts"][name] = fingerprint(path)
    (output / "manifest.json").write_text(json.dumps(manifest))


def test_basin_workspace_and_unordered_relations(
    inventory: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "out"
    produce(inventory, output)
    for name in ("river-graph.parquet", "local-associations.parquet"):
        rewrite(output, name, list(reversed(pq.read_table(output / name).to_pylist())))
    original = verify_tdx._verify_basin
    seen: list[tuple[int, int, int]] = []

    def check(*args: Any, **kwargs: Any) -> tuple[int, int, int]:
        result = original(*args, **kwargs)
        seen.append(result)
        return result

    monkeypatch.setattr(verify_tdx, "_verify_basin", check)
    scratch_paths: list[Path] = []
    temporary = verify_tdx.TemporaryDirectory

    def scratch(*args: Any, **kwargs: Any) -> TemporaryDirectory[str]:
        directory = temporary(*args, **kwargs)
        scratch_paths.append(Path(directory.name))
        return directory

    monkeypatch.setattr(verify_tdx, "TemporaryDirectory", scratch)
    result = verify_tdx.verify_originals(inventory, output)
    assert scratch_paths and all(not path.exists() for path in scratch_paths)
    assert all(not path.is_relative_to(output) for path in scratch_paths)
    assert seen == [(1, 2, 0), (1, 1, 0)]
    assert result["flow_edges"] == 2
    assert result["local_associations"] == 3


@pytest.mark.parametrize(
    "corruption",
    [
        "foreign_edge",
        "duplicate_edge",
        "missing_edge",
        "extra_edge",
        "missing_graph",
        "extra_graph",
        "duplicate_graph",
        "duplicate_pair",
        "missing_pair",
        "extra_pair",
        "wrong_pair",
    ],
)
def test_relation_corruption(inventory: Path, tmp_path: Path, corruption: str) -> None:  # noqa: F811
    output = tmp_path / "out"
    produce(inventory, output)
    name = "local-associations.parquet" if "pair" in corruption else "river-graph.parquet"
    rows = pq.read_table(output / name).to_pylist()
    if corruption == "foreign_edge":
        rows[-1]["upstream_ids"] = [1]
    elif corruption == "duplicate_edge":
        rows[-1]["upstream_ids"] = [3, 3]
    elif corruption == "missing_edge":
        rows[-1]["upstream_ids"] = []
    elif corruption == "extra_edge":
        rows[-1]["upstream_ids"] = [3, 99]
    elif corruption.startswith("duplicate"):
        rows.append(rows[-1].copy())
    elif corruption.startswith("missing"):
        rows.pop()
    elif corruption == "extra_graph":
        rows.append({**rows[-1], "id": 99, "upstream_ids": []})
    elif corruption == "extra_pair":
        rows.append({"river_id": 99, "catchment_id": 99})
    else:
        rows[1]["catchment_id"] = 3
    rewrite(output, name, rows)
    with pytest.raises(ValueError):
        verify_tdx.verify_originals(inventory, output)


def test_manifest_count_and_failure_cleanup(inventory: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    output = tmp_path / "out"
    produce(inventory, output)
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["rivers"]["count"] = 3
    (output / "manifest.json").write_text(json.dumps(manifest))
    scratch_paths: list[Path] = []
    temporary = verify_tdx.TemporaryDirectory

    def scratch(*args: Any, **kwargs: Any) -> TemporaryDirectory[str]:
        directory = temporary(*args, **kwargs)
        scratch_paths.append(Path(directory.name))
        return directory

    monkeypatch.setattr(verify_tdx, "TemporaryDirectory", scratch)
    with pytest.raises(ValueError, match="Manifest feature counts"):
        verify_tdx.verify_originals(inventory, output)
    rows = pq.read_table(output / "river-graph.parquet").to_pylist()
    rows.append(rows[-1].copy())
    rewrite(output, "river-graph.parquet", rows)
    with pytest.raises(ValueError, match="Duplicate"):
        verify_tdx.verify_originals(inventory, output)
    assert len(scratch_paths) == 2 and all(not path.exists() for path in scratch_paths)
