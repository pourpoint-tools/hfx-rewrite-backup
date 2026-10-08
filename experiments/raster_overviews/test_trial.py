from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.enums import Resampling
from rasterio.shutil import copy  # ty: ignore[unresolved-import] # Compiled Rasterio extension.
from rasterio.transform import from_origin

from experiments.raster_overviews.trial import verify_output


def test_rewrite_and_reject_changed_bits_or_overviews(tmp_path: Path) -> None:
    source, output = tmp_path / "input.tif", tmp_path / "output.tif"
    data = np.zeros((1024, 1024), dtype="float32")
    data[0, :4] = [np.nan, -0.0, 1.25, 65536.5]
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=1024,
        height=1024,
        count=1,
        dtype="float32",
        nodata=np.nan,
        crs="EPSG:8857",
        transform=from_origin(0, 0, 30, 30),
        tiled=True,
        blockxsize=512,
        blockysize=512,
        compress="DEFLATE",
        BIGTIFF="YES",
    ) as dst:
        dst.write(data, 1)
        dst.build_overviews([2, 4], Resampling.nearest)
    with pytest.raises(AssertionError):
        verify_output(source, source)
    copy(
        source, output, driver="COG", OVERVIEWS="NONE", BIGTIFF="YES", BLOCKSIZE=512, COMPRESS="DEFLATE", PREDICTOR="NO"
    )
    result = verify_output(source, output)
    assert result["cog_valid"] is True
    # IEEE negative zero compares equal numerically, but must not pass bit verification.
    with rasterio.open(source, "r+") as dst:
        data[0, 1] = 0.0
        dst.write(data, 1)
    with pytest.raises(AssertionError):
        verify_output(source, output)


def test_payload_comparison_rejects_one_changed_tile(tmp_path: Path) -> None:
    import tifffile

    from experiments.raster_overviews.trial import verify_payloads

    source, output = tmp_path / "source.tif", tmp_path / "output.tif"
    tifffile.imwrite(source, np.arange(1024**2, dtype="uint8").reshape(1024, 1024), tile=(512, 512))
    output.write_bytes(source.read_bytes())
    assert verify_payloads(source, output)["tiles"] == 4
    with tifffile.TiffFile(output) as tif:
        offset = tif.pages[0].dataoffsets[-1]
    with output.open("r+b") as stream:
        stream.seek(offset)
        stream.write(b"\xff")
    with pytest.raises(AssertionError):
        verify_payloads(source, output)
