"""Exercise the public HTTP probe against an independently built IPC bundle."""

import hashlib
import json
import subprocess
import sys
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[str, dict[str, str], list[str]]]:
    for name, batches, schema in [
        (
            "catchments.arrow",
            [[(90, b"c" * 500000)], [(2, b"a" * 100000), (13, b"b" * 100000)]],
            pa.schema([("id", pa.int64()), ("geometry", pa.binary())]),
        ),
    ]:
        with pa.OSFile(str(tmp_path / name), "wb") as sink, pa.ipc.new_file(sink, schema) as writer:
            for rows in batches:
                writer.write_batch(
                    pa.RecordBatch.from_pylist(
                        [dict(zip(schema.names, row, strict=True)) for row in rows], schema=schema
                    )
                )
    digest = hashlib.sha256((tmp_path / "catchments.arrow").read_bytes()).hexdigest()
    schema = pa.schema(
        [pa.field("id", pa.int64(), False), pa.field("block", pa.int32(), False), pa.field("row", pa.int32(), False)],
        metadata={b"hfx:catchments_sha256": digest.encode(), b"hfx:format_version": b"0.4.0"},
    )
    with pa.OSFile(str(tmp_path / "lookup.arrow"), "wb") as sink, pa.ipc.new_file(sink, schema) as writer:
        for rows in [[(2, 1, 0), (13, 1, 1)], [(90, 0, 0)]]:
            writer.write_batch(
                pa.RecordBatch.from_pylist([dict(zip(schema.names, row, strict=True)) for row in rows], schema=schema)
            )
    (tmp_path / "lookup-directory.json").write_text(
        json.dumps(
            {
                "version": 1,
                "batches": [
                    {"batch": 0, "min_id": 2, "max_id": 13, "rows": 2},
                    {"batch": 1, "min_id": 90, "max_id": 90, "rows": 1},
                ],
            }
        )
    )
    artifacts = {}
    for path in tmp_path.iterdir():
        data = path.read_bytes()
        artifacts[path.name] = {
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "head_sha256": hashlib.sha256(data[:65536]).hexdigest(),
            "tail_sha256": hashlib.sha256(data[-65536:]).hexdigest(),
        }
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "format_version": "0.4.0",
                "catchments": "catchments.arrow",
                "lookup": "lookup.arrow",
                "directory": "lookup-directory.json",
                "graph": "graph.parquet",
                "artifacts": artifacts,
            }
        )
    )
    mode: dict[str, str] = {}
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            data = (tmp_path / self.path.lstrip("/")).read_bytes()
            value = self.headers.get("Range")
            requests.append(self.path + " " + str(value))
            if value:
                start, end = map(int, value.removeprefix("bytes=").split("-"))
                self.send_response(206)
                self.send_header(
                    "Content-Range", f"bytes {start if mode.get('bad') != 'range' else start + 1}-{end}/{len(data)}"
                )
                data = data[start : end + 1]
            else:
                self.send_response(200)
            self.send_header(
                "ETag", '"changed"' if mode.get("bad") == "identity" and self.headers.get("If-Match") else '"fixed"'
            )
            if mode.get("bad") == "fingerprint" and self.path == "/catchments.arrow":
                data = bytes([data[0] ^ 1]) + data[1:]
            if mode.get("bad") == "encoding":
                self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", mode, requests
    finally:
        httpd.shutdown()
        thread.join()
        httpd.server_close()


def test_selective_access(server: tuple[str, dict[str, str], list[str]], tmp_path: Path) -> None:
    url, _, requests = server
    report = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_vector_access.py",
            url,
            "--ids",
            "13",
            "3",
            "1",
            "13",
            "100",
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(report.read_text())
    assert data["selected_ids"] == [13]
    assert data["absent_ids"] == [1, 3, 100]
    assert data["lookup_batches"] == [0]
    assert data["catchment_batches"] == [1]
    assert data["rows"][0]["geometry_sha256"] == hashlib.sha256(b"b" * 100000).hexdigest()
    assert data["bytes_received"] < 400000
    assert any("bytes=" in request for request in requests)


@pytest.mark.parametrize(
    "bad, expected",
    [
        ("identity", "ETag"),
        ("range", "Content-Range"),
        ("fingerprint", "fingerprint mismatch"),
        ("encoding", "Content-Encoding"),
    ],
)
def test_rejects_invalid_transport_or_artifact(
    server: tuple[str, dict[str, str], list[str]], tmp_path: Path, bad: str, expected: str
) -> None:
    url, mode, _ = server
    mode["bad"] = bad
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_vector_access.py",
            url,
            "--ids",
            "13",
            "--report",
            str(tmp_path / "report.json"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert expected in result.stderr


@pytest.mark.parametrize("wrong", [False, True])
def test_optional_source_comparison(server: tuple[str, dict[str, str], list[str]], tmp_path: Path, wrong: bool) -> None:
    url, _, _ = server
    source = tmp_path / "source.parquet"
    pq.write_table(
        pa.table(
            {
                "id": pa.array([90, 13, 2], type=pa.int64()),
                "geometry": [b"c" * 500000, b"wrong" if wrong else b"b" * 100000, b"a" * 100000],
            }
        ),
        source,
    )
    report = tmp_path / "comparison.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_vector_access.py",
            url,
            "--ids",
            "13",
            "3",
            "--source",
            str(source),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
    )
    if wrong:
        assert result.returncode != 0
        assert "Source row mismatch" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert json.loads(report.read_text())["source_verification"]["matched_ids"] == [13]
