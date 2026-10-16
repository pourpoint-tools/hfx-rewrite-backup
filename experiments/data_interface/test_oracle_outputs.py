from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("module", ["establish_workloads", "catchment_flow_oracle", "source_node_spatial"])
def test_source_oracle_rejects_report_inside_source_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: str
) -> None:
    oracle = importlib.import_module(f"experiments.data_interface.oracles.{module}")
    source = tmp_path / "source"
    source.mkdir()
    report = source / "new-oracle.json"
    monkeypatch.setattr(sys, "argv", [module, str(source), "--report", str(report)])
    with pytest.raises(ValueError, match="outside input bundle"):
        oracle.main()
    assert not list(source.iterdir())
