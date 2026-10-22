"""Authenticated object reads retain the public probe's byte and identity checks."""

import io
from pathlib import Path
from typing import Any

import pytest

from scripts.check_vector_access import S3

boto3 = pytest.importorskip("boto3")
StreamingBody = pytest.importorskip("botocore.response").StreamingBody
Stubber = pytest.importorskip("botocore.stub").Stubber


@pytest.fixture
def client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url="https://objects.example",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )


def response(data: bytes = b"abc", **changes: Any) -> dict[str, Any]:
    return {
        "Body": StreamingBody(io.BytesIO(data), len(data)),
        "ETag": '"v1"',
        "ContentRange": "bytes 0-2/10",
        "ResponseMetadata": {"HTTPStatusCode": 206},
        **changes,
    }


def test_s3_range_pins_etag_and_keeps_unsigned_receipts(client: Any) -> None:
    transport = S3(client, "https://objects.example")
    url = "https://objects.example/bucket/prefix/a%20b"
    params = {"Bucket": "bucket", "Key": "prefix/a b", "Range": "bytes=0-2"}
    with Stubber(client) as stub:
        stub.add_response("get_object", response(), params)
        stub.add_response("get_object", response(), {**params, "IfMatch": '"v1"'})
        assert transport.get(url, (0, 2, 10)) == b"abc"
        assert transport.get(url, (0, 2, 10)) == b"abc"
        stub.assert_no_pending_responses()
    assert transport.requests == [{"url": url, "start": 0, "end": 2, "bytes": 3, "etag": '"v1"'}] * 2


@pytest.mark.parametrize(
    ("changes", "data", "message"),
    [
        ({"ContentRange": "bytes 0-2/11"}, b"abc", "Content-Range"),
        ({"ETag": 'W/"v1"'}, b"abc", "strong ETag"),
        ({"ETag": '"v2"'}, b"abc", "ETag changed"),
        ({"ContentEncoding": "gzip"}, b"abc", "Content-Encoding"),
        ({}, b"ab", "response length"),
        ({}, b"abcd", "response length"),
    ],
)
def test_s3_rejects_invalid_range(client: Any, changes: dict[str, Any], data: bytes, message: str) -> None:
    transport = S3(client, "https://objects.example")
    url = "https://objects.example/bucket/key"
    transport.etags[url] = '"v1"'
    with Stubber(client) as stub:
        stub.add_response(
            "get_object",
            response(data, **changes),
            {"Bucket": "bucket", "Key": "key", "Range": "bytes=0-2", "IfMatch": '"v1"'},
        )
        with pytest.raises(ValueError, match=message):
            transport.get(url, (0, 2, 10))
    assert transport.requests == []


def test_s3_rejects_other_endpoint_and_signed_urls(client: Any) -> None:
    transport = S3(client, "https://objects.example")
    for url in ["https://other.example/bucket/key", "https://objects.example/bucket/key?secret=value"]:
        with pytest.raises(ValueError, match="endpoint"):
            transport.get(url)


def test_authenticated_relationship_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import Mock

    import boto3

    from hfx.spatial_bundle import build
    from scripts.check_spatial_access import main
    from tests.test_spatial_bundle import normalized_source

    source, output = tmp_path / "source", tmp_path / "output"
    digest = normalized_source(source)
    build(source, output, source_manifest_sha256=digest, rows=2)
    calls: list[dict[str, Any]] = []

    def get_object(**params: Any) -> dict[str, Any]:
        assert params["Bucket"] == "bucket"
        data = (output / params["Key"].removeprefix("prefix/")).read_bytes()
        calls.append(params)
        if "IfMatch" in params:
            assert params["IfMatch"] == '"v1"'
        if "Range" in params:
            start, end = map(int, params["Range"].removeprefix("bytes=").split("-"))
            return response(data[start : end + 1], ContentRange=f"bytes {start}-{end}/{len(data)}")
        return response(data, ResponseMetadata={"HTTPStatusCode": 200})

    client = Mock(get_object=get_object)
    session = Mock()
    session.client.return_value = client
    factory = Mock(return_value=session)
    monkeypatch.setattr(boto3, "Session", factory)
    report = tmp_path / "receipt.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "probe",
            "https://objects.example/bucket/prefix",
            "--aws-profile",
            "private",
            "--s3-endpoint",
            "https://objects.example",
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
    import json

    result = json.loads(report.read_text())
    factory.assert_called_once_with(profile_name="private")
    assert all(item["reference"] == "equal_verified_local_result" for item in result["repeats"])
    assert result["final"]["http_requests"] == len(calls) == len(result["requests"])
    assert result["final"]["http_body_bytes"] == sum(item["bytes"] for item in result["requests"])
    assert all(item["url"].startswith("https://objects.example/bucket/prefix/") for item in result["requests"])


def test_s3_precondition_failure_is_not_retried_without_identity(client: Any) -> None:
    from botocore.exceptions import ClientError

    transport = S3(client, "https://objects.example")
    url = "https://objects.example/bucket/key"
    transport.etags[url] = '"v1"'
    with Stubber(client) as stub:
        stub.add_client_error(
            "get_object",
            service_error_code="PreconditionFailed",
            http_status_code=412,
            expected_params={"Bucket": "bucket", "Key": "key", "Range": "bytes=0-2", "IfMatch": '"v1"'},
        )
        with pytest.raises(ClientError, match="PreconditionFailed"):
            transport.get(url, (0, 2, 10))
        stub.assert_no_pending_responses()
    assert transport.requests == []
