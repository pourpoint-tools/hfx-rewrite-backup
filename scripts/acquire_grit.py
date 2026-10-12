"""Acquire the pinned GRIT v1.0 originals sequentially on production compute."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path
from typing import cast


def extract_verified(archive: Path, target: Path, md5: str, size: int) -> dict[str, object]:
    if target.exists():
        raise FileExistsError(target)
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "md5").hexdigest() != md5:
            raise ValueError(f"archive checksum mismatch: {archive}")
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        if len(members) != 1 or members[0].filename != target.name or members[0].file_size != size:
            raise ValueError(f"archive member name/size differs: {archive}")
        with zipped.open(members[0]) as source, target.open("xb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(target), "size_bytes": size, "sha256": digest, "archive_md5": md5}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--region",
        choices=("AF", "AS", "EU", "NA", "SA", "SI", "SP", "GLOBAL"),
        help="acquire one region; GLOBAL supplies the shared component polygons",
    )
    args = parser.parse_args()
    inventory = cast(dict[str, object], json.loads(args.inventory.read_text()))
    destination: Path = args.destination
    destination.mkdir(parents=True, exist_ok=True)
    if inventory["record_id"] != 17435232:
        raise ValueError("expected immutable GRIT v1.0 record 17435232")
    for document in cast(list[dict[str, object]], inventory["documents"]):
        path = destination / str(document["name"])
        if not path.exists():
            with urllib.request.urlopen(str(document["url"])) as response, path.open("xb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "md5").hexdigest()
        if path.stat().st_size != int(str(document["size_bytes"])) or digest != document["md5"]:
            raise ValueError(f"source document checksum/size mismatch: {path}")
    sources: list[dict[str, object]] = []
    for item in cast(list[dict[str, object]], inventory["archives"]):
        if args.region and item["region"] != args.region:
            continue
        archive = destination / str(item["name"])
        target = destination / str(item["member"])
        if archive.exists() or target.exists():
            raise FileExistsError(archive if archive.exists() else target)
        needed = int(str(item["size_bytes"])) + int(str(item["extracted_bytes"]))
        # Retain 100 GB for conversion/index scratch; final sizing is documented separately.
        if shutil.disk_usage(destination).free < needed + 100_000_000_000:
            raise ValueError(f"insufficient free disk before {archive.name}")
        with urllib.request.urlopen(str(item["url"])) as response, archive.open("xb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        if archive.stat().st_size != int(str(item["size_bytes"])):
            raise ValueError(f"archive size mismatch: {archive}")
        receipt = extract_verified(archive, target, str(item["md5"]), int(str(item["extracted_bytes"])))
        with archive.with_suffix(archive.suffix + ".receipt.json").open("x") as output:
            json.dump(receipt, output, indent=2)
        print(json.dumps(receipt), flush=True)
        sources.append(
            {
                "path": str(target.resolve()),
                "region": item["region"],
                "product": item["product"],
                "archive": {"path": str(archive.resolve()), "md5": item["md5"]},
            }
        )
    producer_inventory = {
        "release": inventory,
        "sources": sources,
        "documents": [
            {**document, "path": str((destination / str(document["name"])).resolve())}
            for document in cast(list[dict[str, object]], inventory["documents"])
        ],
    }
    with (destination / f"producer-inputs-{args.region or 'GLOBAL-ALL'}.json").open("x") as output:
        json.dump(producer_inventory, output, indent=2)


if __name__ == "__main__":
    main()
