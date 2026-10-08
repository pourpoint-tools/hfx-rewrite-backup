"""One-off, bounded GRIT compression measurements; no production reader changes."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import threading
import time
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt
import rasterio

Array = npt.NDArray[Any]
BASE = "https://basin-delineations-public.upstream.tech/grit/hfx-v0.3.0/"
ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_CACHEMAX": 0,
    "VSI_CACHE": False,
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_MAX_RETRY": 0,
}


class Readable(Protocol):
    def read(self, size: int) -> bytes: ...


class BodyLimitError(ValueError):
    def __init__(self, received: int) -> None:
        self.received = received
        super().__init__("HTTP body budget exceeded")


def receive(response: Readable, budget: int) -> bytes:
    body = response.read(budget + 1)
    if len(body) > budget:
        raise BodyLimitError(len(body))
    return body


def validate_range(requested: str, returned: str, size: int) -> None:
    request = re.fullmatch(r"bytes=(\d+)-(\d+)", requested)
    response = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", returned)
    if not request or not response:
        raise ValueError("invalid range syntax")
    start, end = map(int, request.groups())
    actual_start, actual_end, total = map(int, response.groups())
    if actual_start != start or actual_end != min(end, total - 1) or size != actual_end - start + 1:
        raise ValueError("response range differs from request/body")


@dataclass
class Meter:
    urls: dict[str, str]
    limit: int
    records: list[dict[str, Any]] = field(default_factory=list)
    identities: dict[str, str] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(row["body_bytes"] for row in self.records)

    @contextlib.contextmanager
    def bridge(self) -> Iterator[str]:
        meter = self

        class Bridge(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_HEAD(self) -> None:
                self.forward("HEAD")

            def do_GET(self) -> None:
                self.forward("GET")

            def forward(self, method: str) -> None:
                name = self.path.rsplit("/", 1)[-1]
                if name not in meter.urls:
                    self.send_error(404)
                    return
                if meter.total >= meter.limit:
                    self.send_error(502, "body budget exhausted")
                    return
                headers = {"Accept-Encoding": "identity", "User-Agent": "hfx-raster-experiment/1.0"}
                if self.headers.get("Range"):
                    headers["Range"] = self.headers["Range"]
                if name in meter.identities:
                    headers["If-Match"] = meter.identities[name]
                request = urllib.request.Request(meter.urls[name], headers=headers, method=method)
                recorded = False
                try:
                    with urllib.request.urlopen(request, timeout=60) as response:
                        body = receive(response, min(8 * 1024**2, meter.limit - meter.total))
                        etag = response.headers.get("ETag", "")
                        meter.records.append(
                            {
                                "name": name,
                                "method": method,
                                "status": response.status,
                                "range": headers.get("Range"),
                                "body_bytes": len(body),
                                "etag": etag,
                                "content_range": response.headers.get("Content-Range"),
                                "cache_status": response.headers.get("CF-Cache-Status"),
                                "age": response.headers.get("Age"),
                            }
                        )
                        recorded = True
                        if not etag or (name in meter.identities and meter.identities[name] != etag):
                            raise ValueError("missing or changed ETag")
                        meter.identities[name] = etag
                        if method == "GET" and response.status != 206:
                            raise ValueError("range response required")
                        if method == "GET":
                            validate_range(
                                headers.get("Range", ""), response.headers.get("Content-Range", ""), len(body)
                            )
                        self.send_response(response.status)
                        for key in ("Content-Length", "Content-Range", "Content-Type", "ETag", "Accept-Ranges"):
                            if key in response.headers:
                                self.send_header(key, response.headers[key])
                        self.end_headers()
                        if method != "HEAD":
                            self.wfile.write(body)
                except Exception as error:
                    if not recorded:
                        meter.records.append(
                            {
                                "name": name,
                                "method": method,
                                "body_bytes": error.received if isinstance(error, BodyLimitError) else 0,
                                "error": type(error).__name__,
                            }
                        )
                    print(f"bridge {method} {name}: {type(error).__name__}: {error}", flush=True)
                    self.send_error(502)

        server = HTTPServer(("127.0.0.1", 0), Bridge)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


def digest(array: Array) -> str:
    return hashlib.sha256(array.tobytes()).hexdigest()


def verify(path: Path, data: Array, mask: Array, profile: dict[str, Any]) -> dict[str, str]:
    with rasterio.open(path) as src:
        actual = src.read(1)
        np.testing.assert_array_equal(actual.view("uint8"), data.view("uint8"))
        np.testing.assert_array_equal(src.read_masks(1), mask)
        assert src.transform == profile["transform"] and src.crs == profile["crs"]
        assert src.width == data.shape[1] and src.height == data.shape[0]
        assert src.dtypes[0] == str(data.dtype)
        assert (
            (np.isnan(src.nodata) and np.isnan(profile["nodata"]))
            if data.dtype.kind == "f"
            else src.nodata == profile["nodata"]
        )
        assert src.overviews(1) == [] and src.block_shapes == [(512, 512)]
    return {"cells_sha256": digest(data), "mask_sha256": digest(mask)}


def encode(path: Path, data: Array, mask: Array, profile: dict[str, Any], codec: str, predictor: int) -> float:
    settings = dict(
        profile,
        driver="GTiff",
        compress=codec,
        predictor=predictor,
        tiled=True,
        blockxsize=512,
        blockysize=512,
        num_threads=1,
    )
    settings.update(zlevel=6) if codec == "DEFLATE" else settings.update(zstd_level=9)
    start = time.perf_counter()
    with rasterio.open(path, "w", **settings) as dst:
        dst.write(data, 1)
        # Nodata-derived masks must match; no replacement mask or hydrology is inferred.
    elapsed = time.perf_counter() - start
    verify(path, data, mask, profile)
    return elapsed


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n")
