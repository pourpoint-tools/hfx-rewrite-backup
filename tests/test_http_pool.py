"""HTTP/1.1 requests reuse a connection without weakening response checks."""

from collections.abc import Iterator
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from scripts.check_vector_access import HTTP


@pytest.fixture
def endpoint() -> Iterator[tuple[str, list[tuple[int, str | None]], dict[str, str]]]:
    seen: list[tuple[int, str | None]] = []
    mode: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            seen.append((self.client_address[1], self.headers.get("If-Match")))
            self.send_response(206)
            self.send_header("Content-Range", "bytes 0-2/6" if mode.get("bad") == "range" else "bytes 0-1/6")
            self.send_header("ETag", '"changed"' if mode.get("bad") == "etag" else '"fixed"')
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ab")

        def handle(self) -> None:
            with suppress(ConnectionResetError):  # Rejected responses deliberately discard the connection.
                super().handle()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/data", seen, mode
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_repeated_ranges_reuse_tcp_and_pin_identity(
    endpoint: tuple[str, list[tuple[int, str | None]], dict[str, str]],
) -> None:
    url, seen, _ = endpoint
    http = HTTP()
    try:
        assert http.get(url, (0, 1, 6)) == b"ab"
        assert http.get(url, (0, 1, 6)) == b"ab"
        assert seen[0][0] == seen[1][0]
        assert [entry[1] for entry in seen] == [None, '"fixed"']
        assert len(http.requests) == 2
    finally:
        http.close()


@pytest.mark.parametrize("bad,match", [("range", "Content-Range"), ("etag", "ETag")])
def test_bad_response_does_not_record_success(
    endpoint: tuple[str, list[tuple[int, str | None]], dict[str, str]], bad: str, match: str
) -> None:
    url, seen, mode = endpoint
    http = HTTP()
    try:
        http.get(url, (0, 1, 6))
        mode["bad"] = bad
        with pytest.raises(ValueError, match=match):
            http.get(url, (0, 1, 6))
        assert len(http.requests) == 1
        mode.clear()
        assert http.get(url, (0, 1, 6)) == b"ab"
        assert seen[0][0] == seen[1][0]
        assert seen[2][0] != seen[1][0]  # rejected response connection was discarded
        assert len(http.requests) == 2
    finally:
        http.close()


def test_bounded_error_read_discards_response(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str | int] = []

    class Response:
        headers = {"ETag": '"fixed"', "Content-Range": "bytes 0-1/6"}
        status = 206

        def read(self, size: int) -> bytes:
            events.append(size)
            return b"abc"

        def close(self) -> None:
            events.append("close")

        def release_conn(self) -> None:
            events.append("release")

    http = HTTP()
    monkeypatch.setattr(http.pool, "request", lambda *args, **kwargs: Response())
    try:
        with pytest.raises(ValueError, match="length"):
            http.get("https://example.invalid/data", (0, 1, 6))
        assert events == [3, "close", "release"]
        assert http.requests == []
    finally:
        http.close()


def test_close_clears_pool_and_vector_check_closes_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import check_vector_access as probe

    http = HTTP()
    events: list[str] = []
    monkeypatch.setattr(http.pool, "clear", lambda: events.append("clear"))
    monkeypatch.setattr(probe, "HTTP", lambda: http)
    with pytest.raises(ValueError, match="HTTP"):
        probe.check("not-a-url", [1])
    assert events == ["clear"]


def test_failed_spatial_open_closes_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import check_spatial_access as probe

    events: list[str] = []

    class FailingHTTP(HTTP):
        def get(self, url: str, span: tuple[int, int, int] | None = None) -> bytes:
            raise ValueError("failed manifest")

        def close(self) -> None:
            events.append("close")
            super().close()

    monkeypatch.setattr(probe, "HTTP", FailingHTTP)
    with pytest.raises(ValueError, match="failed manifest"):
        probe.SpatialAccess("https://example.invalid", "rivers")
    assert events == ["close"]
