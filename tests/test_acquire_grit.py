"""Acquisition preserves verified originals and never replaces partial evidence."""

import hashlib
import zipfile
from pathlib import Path

import pytest

from scripts.acquire_grit import extract_verified


def test_verified_member_and_existing_evidence(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("source.gpkg", b"original bytes")
    checksum = hashlib.md5(archive.read_bytes()).hexdigest()
    target = tmp_path / "source.gpkg"
    receipt = extract_verified(archive, target, checksum, len(b"original bytes"))
    assert target.read_bytes() == b"original bytes"
    assert receipt["sha256"] == hashlib.sha256(b"original bytes").hexdigest()
    with pytest.raises(FileExistsError):
        extract_verified(archive, target, checksum, len(b"original bytes"))
    with pytest.raises(ValueError, match="checksum"):
        extract_verified(archive, tmp_path / "other.gpkg", "0" * 32, 14)
    assert not (tmp_path / "other.gpkg").exists()


def test_member_size_and_archive_member_name(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("../source.gpkg", b"unexpected member")
    checksum = hashlib.md5(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="member"):
        extract_verified(archive, tmp_path / "source.gpkg", checksum, 17)


def test_acquisition_binds_documents_and_producer_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import sys
    from types import SimpleNamespace

    from scripts.acquire_grit import main

    originals = tmp_path / "originals"
    originals.mkdir()
    archive = originals / "source.gpkg.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("source.gpkg", b"original bytes")
    document = originals / "LICENSE.md"
    document.write_text("source license")
    inventory = {
        "record_id": 17435232,
        "documents": [
            {
                "name": document.name,
                "url": document.as_uri(),
                "size_bytes": document.stat().st_size,
                "md5": hashlib.md5(document.read_bytes()).hexdigest(),
            }
        ],
        "archives": [
            {
                "name": archive.name,
                "url": archive.as_uri(),
                "md5": hashlib.md5(archive.read_bytes()).hexdigest(),
                "size_bytes": archive.stat().st_size,
                "member": "source.gpkg",
                "extracted_bytes": 14,
                "region": "SP",
                "product": "segments",
            }
        ],
    }
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps(inventory))
    target = tmp_path / "acquired"
    monkeypatch.setattr(sys, "argv", ["acquire_grit", str(inventory_path), str(target), "--region", "SP"])
    monkeypatch.setattr("scripts.acquire_grit.shutil.disk_usage", lambda _: SimpleNamespace(free=200_000_000_000))
    main()
    produced = json.loads((target / "producer-inputs-SP.json").read_text())
    assert produced["sources"][0]["archive"]["md5"] == inventory["archives"][0]["md5"]
    assert Path(produced["sources"][0]["path"]).read_bytes() == b"original bytes"
    assert Path(produced["documents"][0]["path"]).read_text() == "source license"
    with pytest.raises(FileExistsError):
        main()
    assert (target / archive.name).read_bytes() == archive.read_bytes()
