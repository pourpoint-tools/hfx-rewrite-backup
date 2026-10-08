"""Small independent TIFF fixtures for the complete raw-copy proof."""

import hashlib
from pathlib import Path

import numpy as np
import pytest
import tifffile

from scripts.verify_raster_copy import capture_source, verify_output


def raster(path: Path, *, value: int = 7, description: str = "source history") -> None:
    data = np.full((512, 1024), value, dtype="uint8")
    data[0, 0] = 255
    tifffile.imwrite(
        path,
        data,
        bigtiff=True,
        tile=(512, 512),
        compression="deflate",
        metadata=None,
        description=description,
        extratags=[(42113, "s", 0, "255", False)],
    )


def test_capture_and_native_copy(tmp_path: Path) -> None:
    source, output = tmp_path / "source.tif", tmp_path / "output.tif"
    raster(source)
    raster(output)
    trusted = hashlib.sha256(source.read_bytes()).hexdigest()
    receipt = capture_source(source, trusted)
    result = verify_output(output, receipt)
    assert result["identity"]["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert result["tiles"] == 2
    assert result["masks_equal"] is True
    with pytest.raises(ValueError, match="trusted"):
        capture_source(source, "0" * 64)


def test_rejects_native_or_metadata_change(tmp_path: Path) -> None:
    source, output = tmp_path / "source.tif", tmp_path / "output.tif"
    raster(source)
    receipt = capture_source(source, hashlib.sha256(source.read_bytes()).hexdigest())
    raster(output, value=8)
    with pytest.raises(ValueError, match="payloads changed"):
        verify_output(output, receipt)
    raster(output, description="lost source history")
    with pytest.raises(ValueError, match="metadata changed"):
        verify_output(output, receipt)


def test_float_nan_bits_and_nodata_proof(tmp_path: Path) -> None:
    path = tmp_path / "float.tif"
    bits = np.full((512, 512), 0x3F800000, dtype="uint32")
    bits[0, :3] = [0x7FC00001, 0x7FC01234, 0x80000000]
    tifffile.imwrite(
        path,
        bits.view("float32"),
        bigtiff=True,
        tile=(512, 512),
        compression="deflate",
        metadata=None,
        extratags=[(42113, "s", 0, "nan", False)],
    )
    receipt = capture_source(path, hashlib.sha256(path.read_bytes()).hexdigest())
    assert receipt["metadata"]["mask_flags"] == [["nodata"]]
    assert verify_output(path, receipt)["native_bits_equal"] is True


def test_rejects_overviews_and_external_masks(tmp_path: Path) -> None:
    import rasterio
    from rasterio.enums import Resampling

    source = tmp_path / "source.tif"
    raster(source)
    receipt = capture_source(source, hashlib.sha256(source.read_bytes()).hexdigest())
    with rasterio.open(source, "r+") as dataset:
        dataset.build_overviews([2], Resampling.nearest)
    with pytest.raises(ValueError, match="overviews"):
        verify_output(source, receipt)
    raster(source)
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False), rasterio.open(source, "r+") as dataset:
        dataset.write_mask(np.full((512, 1024), 255, dtype="uint8"))
    with pytest.raises(ValueError, match="external"):
        capture_source(source, hashlib.sha256(source.read_bytes()).hexdigest())


def test_no_tile_payload_can_overlap_metadata(tmp_path: Path) -> None:
    from scripts.verify_raster_copy import inspect

    path = tmp_path / "overlap.tif"
    raster(path)
    with tifffile.TiffFile(path) as tif:
        offset_position = tif.pages[0].tags[324].valueoffset
    with path.open("r+b") as stream:
        stream.seek(offset_position)
        stream.write((16).to_bytes(8, "little"))
    with pytest.raises(ValueError, match="overlaps|follows"):
        inspect(path, output=True)


def test_rejects_unlinked_trailing_data(tmp_path: Path) -> None:
    path = tmp_path / "native.tif"
    raster(path)
    receipt = capture_source(path, hashlib.sha256(path.read_bytes()).hexdigest())
    with path.open("ab") as stream:
        stream.write(b"unused old overview bytes")
    with pytest.raises(ValueError, match="trailing"):
        verify_output(path, receipt)


def test_accepts_and_checks_gdal_tile_trailers(tmp_path: Path) -> None:
    from scripts.verify_raster_copy import scan

    # Independent framing fixture: size leader, tile bytes, repeated last four.
    path = tmp_path / "framed.bin"
    path.write_bytes(b"\x08\x00\x00\x00abcdefgh efgh".replace(b" ", b""))
    result = scan(path, (4,), (8,), framed=True)
    assert result["identity"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_bytes(b"\x08\x00\x00\x00abcdefghXXXX")
    with pytest.raises(ValueError, match="trailer"):
        scan(path, (4,), (8,), framed=True)
