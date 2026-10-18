"""Selective production reads compose immediate relationships with final records."""

import json
from pathlib import Path

import pytest

from hfx.spatial_bundle import build
from tests.test_spatial_bundle import normalized_source
from tests.test_vector_access import server as range_server_fixture

server = range_server_fixture


def test_selective_records_spatial_candidates_and_relationship_composition(tmp_path: Path) -> None:
    from scripts.check_spatial_access import SpatialAccess

    source, output = tmp_path / "source", tmp_path / "output"
    digest = normalized_source(source)
    build(source, output, source_manifest_sha256=digest, rows=2)
    access = SpatialAccess(str(output), "rivers")
    try:
        records, absent = access.ids([70, 11, 10, 70], ["id"])
        assert records["id"].to_pylist() == [70, 10, 70]
        assert absent == [11]
        assert access.spatial((1, 1, 2, 2), ["id"]).num_rows == 5
        assert access.spatial((2, 2, 3, 3), ["id"]).num_rows == 0
        assert access.neighbors([10], "downstream_ids") == [20, 40]
        target, missing = access.ids(access.neighbors([10], "downstream_ids"), ["id", "geometry"])
        assert target["id"].to_pylist() == [20, 40]
        assert missing == []
        rows, size, elapsed = access.bulk(["id"])
        assert elapsed >= 0
        assert rows == 5
        assert size >= 40
        reference = SpatialAccess(str(output), "rivers")
        try:
            assert access.bulk(["id"], reference)[:2] == (rows, size)
        finally:
            reference.close()
        assert access.relationship_reader is not None
        assert access.relationship_reader.schema.names == ["id", "downstream_ids"]
        assert access.neighbors([10], "upstream_node_ids") == [100]
        assert access.relationship_reader.schema.names == ["id", "upstream_node_ids"]
        assert access.stats()["local_read_bytes"] > 0
    finally:
        access.close()


def test_probe_reports_reuse_and_rejects_stale_lookup_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.check_spatial_access import SpatialAccess, main

    source, output = tmp_path / "source", tmp_path / "output"
    digest = normalized_source(source)
    build(source, output, source_manifest_sha256=digest, rows=2)
    report = tmp_path / "report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "probe",
            str(output),
            "--domain",
            "rivers",
            "--ids",
            "10",
            "--relationship",
            "local_catchment_ids",
            "--columns",
            "id",
            "--reference",
            str(output),
            "--report",
            str(report),
        ],
    )
    main()
    result = json.loads(report.read_text())
    assert [entry["rows"] for entry in result["repeats"]] == [1, 1]
    assert result["repeats"][0]["acquisition"]["local_read_bytes"] > 0
    assert result["peak_rss_bytes"] > 0
    assert all(entry["reference"] == "equal_verified_local_result" for entry in result["repeats"])
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    family = manifest["families"]["rivers"]
    family["data_sha256"] = "0" * 64
    manifest["artifacts"][family["data"]]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    access = SpatialAccess(str(output), "rivers")
    try:
        with pytest.raises(ValueError, match="lookup binding"):
            access.ids([10], ["id"])
    finally:
        access.close()


def test_http_composition_and_streaming_reference(
    server: tuple[str, dict[str, str], list[str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.check_spatial_access import SpatialAccess, main

    url, _, requests = server
    source, output = tmp_path / "source", tmp_path / "spatial"
    digest = normalized_source(source)
    build(source, output, source_manifest_sha256=digest, rows=2)
    remote = SpatialAccess(url + "/spatial", "rivers")
    local = SpatialAccess(str(output), "rivers")
    try:
        records, absent = remote.ids([70, 11, 10, 70], ["id", "geometry"])
        assert records["id"].to_pylist() == [70, 10, 70]
        assert absent == [11]
        assert remote.spatial((1, 1, 2, 2), ["id"]).num_rows == 5
        assert remote.bulk(["id", "geometry"], local)[0] == 5
    finally:
        local.close()
        remote.close()
    report = tmp_path / "http-report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "probe",
            url + "/spatial",
            "--domain",
            "rivers",
            "--ids",
            "10",
            "--relationship",
            "local_catchment_ids",
            "--reference",
            str(output),
            "--report",
            str(report),
        ],
    )
    main()
    result = json.loads(report.read_text())
    assert all(entry["reference"] == "equal_verified_local_result" for entry in result["repeats"])
    assert result["repeats"][0]["rows"] == 1
    assert result["repeats"][0]["acquisition"]["http_requests"] > 0
    assert any("/spatial/rivers.parquet bytes=" in request for request in requests)
    assert any("/spatial/rivers-relationships.arrow bytes=" in request for request in requests)
