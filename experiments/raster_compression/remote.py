"""Explicit publication and cleanup of this run's small, uniquely named samples."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_s3 import S3Client

from experiments.raster_compression.measure import save

BUCKET = "basin-delineations-public"
PUBLIC = "https://basin-delineations-public.upstream.tech/"


def client() -> S3Client:
    session = boto3.Session(profile_name="upstream-r2")
    import configparser

    config = configparser.ConfigParser()
    config.read(Path.home() / ".aws/config")
    endpoint = config["profile upstream-r2"]["endpoint_url"]
    if not endpoint.endswith(".r2.cloudflarestorage.com"):
        raise ValueError("Expected configured R2 endpoint")
    return session.client("s3", endpoint_url=endpoint)


def publish(destination: Path) -> None:
    s3 = client()
    ledger_path = destination / "objects.json"
    if ledger_path.exists():
        raise ValueError("ledger already exists; inspect before retry")
    prefix = "experiments/grit-raster-compression/" + uuid.uuid4().hex + "/"
    assert not s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix).get("Contents")
    acquisition = json.loads((destination / "acquisition.json").read_text())
    paths = [destination / "bulk" / f["name"] for s in acquisition["samples"] for f in s["files"]]
    paths += [destination / "bulk" / name for name in ("NOTICE", "CITATION.txt", "README.md")]
    ledger: dict[str, Any] = {"bucket": BUCKET, "prefix": prefix, "public_base": PUBLIC + prefix, "objects": []}
    save(ledger_path, ledger)
    for path in paths:
        body = path.read_bytes()
        entry = {
            "key": prefix + path.name,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "state": "pending",
        }
        ledger["objects"].append(entry)
        save(ledger_path, ledger)
        response = s3.put_object(
            Bucket=BUCKET,
            Key=entry["key"],
            Body=body,
            IfNoneMatch="*",
            ContentMD5=base64.b64encode(hashlib.md5(body).digest()).decode(),
            Metadata={"sha256": entry["sha256"]},
            ContentType="image/tiff" if path.suffix == ".tif" else "text/plain",
        )
        entry.update(state="created", etag=response["ETag"])
        save(ledger_path, ledger)
        head = s3.head_object(Bucket=BUCKET, Key=entry["key"])
        assert head["ContentLength"] == len(body) and head["ETag"] == entry["etag"]
        assert head["Metadata"]["sha256"] == entry["sha256"]
    print(f"Published {len(paths)} objects, {sum(o['bytes'] for o in ledger['objects'])} bytes", flush=True)


def cleanup(destination: Path) -> None:
    # Never delete merely because a key shares the prefix.
    ledger_path = destination / "objects.json"
    ledger = json.loads(ledger_path.read_text())
    assert (destination / "measurements.json").exists()
    measurements = json.loads((destination / "measurements.json").read_text())
    assert measurements["complete"]
    s3 = client()
    for entry in ledger["objects"]:
        assert entry["state"] == "created" and entry["key"].startswith(ledger["prefix"])
        head = s3.head_object(Bucket=BUCKET, Key=entry["key"])
        assert head["ETag"] == entry["etag"] and head["Metadata"]["sha256"] == entry["sha256"]
        s3.delete_object(Bucket=BUCKET, Key=entry["key"], IfMatch=entry["etag"])
        try:
            s3.head_object(Bucket=BUCKET, Key=entry["key"])
        except ClientError as error:
            assert error.response["ResponseMetadata"]["HTTPStatusCode"] == 404
        else:
            raise AssertionError("object still present")
        entry["state"] = "deleted_verified_404"
        save(ledger_path, ledger)
    assert not s3.list_objects_v2(Bucket=BUCKET, Prefix=ledger["prefix"]).get("Contents")
    ledger["prefix_empty_verified"] = True
    save(ledger_path, ledger)
    acquisition = json.loads((destination / "acquisition.json").read_text())
    names = {f["name"] for sample in acquisition["samples"] for f in sample["files"]}
    names |= {f"{sample['name']}-{kind}-source.npz" for sample in acquisition["samples"] for kind in ("acc", "dir")}
    names |= {"NOTICE", "CITATION.txt", "README.md"}
    bulk = destination / "bulk"
    assert {path.name for path in bulk.iterdir()} == names, "unexpected bulk files; preserve for inspection"
    removed = [
        {
            "name": name,
            "bytes": (bulk / name).stat().st_size,
            "sha256": hashlib.sha256((bulk / name).read_bytes()).hexdigest(),
        }
        for name in sorted(names)
    ]
    save(destination / "local-cleanup.json", {"planned": removed, "bulk_absent": False})
    for name in names:
        (bulk / name).unlink()
    bulk.rmdir()
    save(destination / "local-cleanup.json", {"removed": removed, "bulk_absent": not bulk.exists()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["publish", "cleanup"])
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    (publish if args.action == "publish" else cleanup)(args.destination)
