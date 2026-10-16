"""Generated HTTP artifacts exercise actual transport, not GRIT timing evidence."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import urlparse

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from experiments.data_interface.probe import Access
from experiments.data_interface.traversal_probe import Published, main
from hfx.candidates import fingerprint


@pytest.fixture
def remote_bundle(tmp_path: Path) -> Iterator[tuple[str, Path, dict[str, str], list[dict[str, Any]]]]:
    original, candidate = tmp_path / "original", tmp_path / "candidate"
    original.mkdir()
    candidate.mkdir()
    incoming = pa.table({"id": [30, 10, 40, 20], "upstream_ids": [[10], [], [20, 30], [10]]})
    pq.write_table(incoming, original / "graph.parquet", row_group_size=2)
    source_manifest = {
        "rivers": {"graph": "graph.parquet"},
        "artifacts": {"graph.parquet": fingerprint(original / "graph.parquet")},
    }
    (original / "manifest.json").write_text(json.dumps(source_manifest))
    source_sha = hashlib.sha256((original / "manifest.json").read_bytes()).hexdigest()
    table = pa.table(
        {
            "id": [10, 20, 30, 40],
            "downstream_ids": [[20, 30], [40], [40], []],
            "upstream_ids": [[], [10], [10], [20, 30]],
        }
    )
    with pa.ipc.new_file(str(candidate / "flow.arrow"), table.schema) as writer:
        writer.write_table(table, max_chunksize=2)
    (candidate / "directory.json").write_text(
        json.dumps({"batches": [{"batch": 0, "min_id": 10, "max_id": 20}, {"batch": 1, "min_id": 30, "max_id": 40}]})
    )
    (candidate / "manifest.json").write_text(
        json.dumps(
            {
                "experimental": True,
                "input_manifest_sha256": source_sha,
                "relationships": {"rivers": {"data": "flow.arrow", "directory": "directory.json"}},
                "artifacts": {p.name: fingerprint(p) for p in candidate.iterdir()},
            }
        )
    )
    behavior: dict[str, str] = {}
    calls: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = tmp_path / urlparse(self.path).path.lstrip("/")
            data = path.read_bytes()
            span = self.headers.get("Range")
            etag = '"fixed-artifact"'
            if not span and path.name == "flow.arrow" and behavior.get("error") == "etag":
                etag = '"different-artifact"'
            self.send_response(206 if span else 200)
            self.send_header("ETag", etag)
            self.send_header(
                "Content-Encoding",
                "gzip"
                if behavior.get("error") == "encoding" and not span and path.name == "flow.arrow"
                else "identity",
            )
            body = data
            if span:
                start, end = [int(value) for value in span.removeprefix("bytes=").split("-")]
                body = data[start : end + 1]
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            calls.append(
                {
                    "path": self.path,
                    "range": span,
                    "if_match": self.headers.get("If-Match"),
                    "user_agent": self.headers.get("User-Agent"),
                    "bytes": len(body),
                }
            )

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", candidate, behavior, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("strategy", ["consumer", "bulk-file"])
def test_remote_cli_includes_preparation_and_actual_transfers(
    remote_bundle: tuple[str, Path, dict[str, str], list[dict[str, Any]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    strategy: str,
) -> None:
    root, candidate, _, calls = remote_bundle
    report = tmp_path / "receipt.json"
    bundle = root + ("/original" if strategy == "consumer" else "/candidate")
    expected_source = hashlib.sha256((candidate.parent / "original/manifest.json").read_bytes()).hexdigest()
    argv = [
        "traverse",
        "--bundle",
        bundle,
        "--strategy",
        strategy,
        "--seed",
        "10",
        "--repeats",
        "2",
        "--source-manifest-sha256",
        expected_source,
        "--report",
        str(report),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    main()
    receipt = json.loads(report.read_text())
    assert [phase["count"] for phase in receipt["phases"]] == [4, 4]
    assert (
        receipt["phases"][0]["sorted_ids_sha256_le_i64"]
        == hashlib.sha256(bytes.fromhex("0a0000000000000014000000000000001e000000000000002800000000000000")).hexdigest()
    )
    assert receipt["startup_to_first_result_s"] >= receipt["opening_s"] + receipt["preparation_s"]
    assert receipt["after_preparation"]["http_body_bytes"] > 0
    assert receipt["after_preparation"]["http_requests"] == len(receipt["requests"])
    assert receipt["after_preparation"]["http_body_bytes"] == sum(call["bytes"] for call in calls)
    if strategy == "bulk-file":
        full = [call for call in calls if call["path"] == "/candidate/flow.arrow" and not call["range"]]
        assert len(full) == 1
        assert full[0]["if_match"] == '"fixed-artifact"'
        assert full[0]["user_agent"] == "hfx-vector-verification/0.4.0"
        download = receipt["bulk_file"]
        assert download["sha256"] == fingerprint(candidate / "flow.arrow")["sha256"]
        assert download["disk_bytes"] == (candidate / "flow.arrow").stat().st_size
        assert not Path(download["temporary_directory"]).exists()
        assert receipt["phases"][0]["http_body_bytes"] == 0
    argv[argv.index("--source-manifest-sha256") + 1] = "0" * 64
    argv[-1] = str(tmp_path / "wrong-source.json")
    with pytest.raises(ValueError, match="expected source manifest"):
        main()


@pytest.mark.parametrize("error", ["digest", "etag", "encoding"])
def test_full_download_rejects_identity_change_and_cleans_own_scratch(
    remote_bundle: tuple[str, Path, dict[str, str], list[dict[str, Any]]], error: str
) -> None:
    root, candidate, behavior, _ = remote_bundle
    if error == "digest":
        path = candidate / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["artifacts"]["flow.arrow"]["sha256"] = "0" * 64
        path.write_text(json.dumps(manifest))
    behavior["error"] = error
    with Access(root + "/candidate", "rivers", ["id", "downstream_ids"], relationship=True) as access:
        provider = Published(access, "downstream_ids", "bulk-file")
        try:
            with pytest.raises(ValueError, match="digest|ETag|encoding"):
                provider.prepare()
            scratch = Path(provider.download["temporary_directory"])
        finally:
            provider.close()
        assert not scratch.exists()
