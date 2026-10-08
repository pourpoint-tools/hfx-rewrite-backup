from email.message import Message
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from experiments.raster_compression.measure import BodyLimitError, encode, receive, verify


class Response:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.headers = Message()
        self.headers["Content-Length"] = "999999"

    def read(self, size: int) -> bytes:
        return self.body[:size]


def test_received_bytes_are_body_not_header() -> None:
    assert receive(Response(b"abc"), 4) == b"abc"


def test_body_limit_is_enforced() -> None:
    with pytest.raises(BodyLimitError, match="budget") as failure:
        receive(Response(b"abcde"), 4)
    assert failure.value.received == 5


@pytest.mark.parametrize("codec,predictor", [("DEFLATE", 1), ("DEFLATE", 3), ("ZSTD", 3)])
def test_float_bits_grid_and_masks(tmp_path: Path, codec: str, predictor: int) -> None:
    data = np.zeros((1024, 1024), dtype="float32")
    data[0, :4] = [np.nan, -0.0, 1.25, 65536.5]
    mask = np.where(np.isnan(data), 0, 255).astype("uint8")
    profile = {
        "width": 1024,
        "height": 1024,
        "count": 1,
        "dtype": "float32",
        "nodata": np.nan,
        "crs": rasterio.CRS.from_epsg(8857),
        "transform": from_origin(-15000000 + 512 * 30, 8400000 - 1024 * 30, 30, 30),
    }
    path = tmp_path / "sample.tif"
    assert encode(path, data, mask, profile, codec, predictor) > 0
    assert verify(path, data, mask, profile)["cells_sha256"]
    data[1, 1] = 1
    with pytest.raises(AssertionError):
        verify(path, data, mask, profile)


def test_range_rejects_shifted_cells() -> None:
    from experiments.raster_compression.measure import validate_range

    validate_range("bytes=10-19", "bytes 10-14/15", 5)
    with pytest.raises(ValueError, match="range"):
        validate_range("bytes=10-19", "bytes 11-19/20", 9)
    with pytest.raises(ValueError, match="range"):
        validate_range("bytes=10-19", "bytes 10-19/20", 5)


def test_publication_is_conditional_and_has_exact_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib
    import json
    from types import SimpleNamespace

    import boto3
    from botocore.stub import ANY, Stubber

    from experiments.raster_compression import remote

    s3 = boto3.client("s3", region_name="auto", aws_access_key_id="test", aws_secret_access_key="test")
    monkeypatch.setattr(remote, "client", lambda: s3)
    monkeypatch.setattr(remote.uuid, "uuid4", lambda: SimpleNamespace(hex="test-run"))
    prefix = "experiments/grit-raster-compression/test-run/"
    bulk = tmp_path / "bulk"
    bulk.mkdir()
    (tmp_path / "acquisition.json").write_text(
        json.dumps({"samples": [{"name": "sample", "files": [{"name": "sample.tif"}]}]})
    )
    with Stubber(s3) as stub:
        stub.add_response("list_objects_v2", {}, {"Bucket": remote.BUCKET, "Prefix": prefix})
        for name in ("sample.tif", "NOTICE", "CITATION.txt", "README.md"):
            body = name.encode()
            (bulk / name).write_bytes(body)
            sha = hashlib.sha256(body).hexdigest()
            stub.add_response(
                "put_object",
                {"ETag": '"new"'},
                {
                    "Bucket": remote.BUCKET,
                    "Key": prefix + name,
                    "Body": body,
                    "IfNoneMatch": "*",
                    "ContentMD5": ANY,
                    "Metadata": {"sha256": sha},
                    "ContentType": "image/tiff" if name.endswith(".tif") else "text/plain",
                },
            )
            stub.add_response(
                "head_object",
                {"ContentLength": len(body), "ETag": '"new"', "Metadata": {"sha256": sha}},
                {"Bucket": remote.BUCKET, "Key": prefix + name},
            )
        remote.publish(tmp_path)
        stub.assert_no_pending_responses()
    ledger = json.loads((tmp_path / "objects.json").read_text())
    assert [entry["key"] for entry in ledger["objects"]] == [
        prefix + name for name in ("sample.tif", "NOTICE", "CITATION.txt", "README.md")
    ]
    assert all(entry["state"] == "created" for entry in ledger["objects"])
    with pytest.raises(ValueError, match="ledger already exists"):
        remote.publish(tmp_path)
    (tmp_path / "measurements.json").write_text('{"complete": true}')
    for kind in ("acc", "dir"):
        (bulk / f"sample-{kind}-source.npz").write_bytes(b"source")
    with Stubber(s3) as stub:
        for entry in ledger["objects"]:
            identity = {"Bucket": remote.BUCKET, "Key": entry["key"]}
            stub.add_response("head_object", {"ETag": entry["etag"], "Metadata": {"sha256": entry["sha256"]}}, identity)
            stub.add_response("delete_object", {}, identity | {"IfMatch": entry["etag"]})
            stub.add_client_error(
                "head_object", service_error_code="404", http_status_code=404, expected_params=identity
            )
        stub.add_response("list_objects_v2", {}, {"Bucket": remote.BUCKET, "Prefix": prefix})
        remote.cleanup(tmp_path)
        stub.assert_no_pending_responses()
    assert not bulk.exists()
    assert json.loads((tmp_path / "objects.json").read_text())["prefix_empty_verified"]
    assert len(json.loads((tmp_path / "local-cleanup.json").read_text())["removed"]) == 6


def test_bridge_counts_received_eof_body_and_head() -> None:
    import threading
    import urllib.request
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from experiments.raster_compression.measure import Meter

    received: list[str | None] = []

    class Source(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_HEAD(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", "3")
            self.send_header("ETag", '"source"')
            self.end_headers()

        def do_GET(self) -> None:
            received.append(self.headers.get("If-Match"))
            self.send_response(206)
            self.send_header("Content-Length", "3")
            self.send_header("Content-Range", "bytes 0-2/3")
            self.send_header("ETag", '"source"')
            self.end_headers()
            self.wfile.write(b"abc")

    server = HTTPServer(("127.0.0.1", 0), Source)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        meter = Meter({"tiny.tif": f"http://127.0.0.1:{server.server_port}/tiny.tif"}, 100)
        with meter.bridge() as bridge:
            url = bridge + "/fresh/tiny.tif"
            with urllib.request.urlopen(urllib.request.Request(url, method="HEAD")) as response:
                assert response.read() == b""
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-99"})) as response:
                assert response.read() == b"abc"
        assert meter.total == 3
        assert [row["body_bytes"] for row in meter.records] == [0, 3]
        assert received == ['"source"']
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
