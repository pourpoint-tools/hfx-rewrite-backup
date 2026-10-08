"""Bounded one-off overview-removal trial; all bulk paths are external to Git."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import resource
import time
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import tifffile
from rasterio.enums import Resampling
from rasterio.shutil import copy  # ty: ignore[unresolved-import] # Compiled Rasterio extension.
from rasterio.windows import Window
from rio_cogeo.cogeo import cog_validate

from experiments.raster_compression.measure import BASE, ENV, Meter, save, verify

WINDOWS = {"greenland": [391168, 49152, 1024, 1024], "madagascar": [654848, 345600, 1024, 1024]}


def verify_output(source: Path, output: Path) -> dict[str, Any]:
    with rasterio.open(source) as src:
        result: dict[str, Any] = verify(output, src.read(1), src.read_masks(1), dict(src.profile))
    with output.open("rb") as stream:
        bigtiff = stream.read(4) in (b"II+\x00", b"MM\x00+")
    with rasterio.open(output) as dst:
        assert dst.compression.name == "deflate"
        assert dst.tags(ns="IMAGE_STRUCTURE").get("PREDICTOR", "1") == "1"
        assert dst.count == 1
        assert dst.files == [str(output)], "output must be self-contained"
    valid, errors, warnings = cog_validate(str(output), strict=False)
    assert valid, (errors, warnings)
    # Missing display pyramids are intentional; no other warning is accepted.
    assert all(
        w == "The file is greater than 512xH or 512xW, it is recommended to include internal overviews"
        for w in warnings
    )
    return result | {"cog_valid": valid, "cog_errors": errors, "cog_warnings": warnings, "bigtiff": bigtiff}


def verify_payloads(source: Path, output: Path) -> dict[str, Any]:
    hashes: list[str] = []
    with tifffile.TiffFile(source) as left, tifffile.TiffFile(output) as right:
        a, b = left.pages[0], right.pages[0]
        assert isinstance(a, tifffile.TiffPage) and isinstance(b, tifffile.TiffPage)
        assert a.is_tiled and b.is_tiled
        assert a.shape == b.shape and a.dtype == b.dtype
        assert a.tilewidth == b.tilewidth and a.tilelength == b.tilelength
        assert a.compression == b.compression and a.predictor == b.predictor
        assert left.byteorder == right.byteorder, "raw copy cannot silently change byte order"
        assert a.databytecounts == b.databytecounts
        with source.open("rb") as src, output.open("rb") as dst:
            for offset_a, offset_b, length in zip(a.dataoffsets, b.dataoffsets, a.databytecounts, strict=True):
                src.seek(offset_a)
                dst.seek(offset_b)
                payload = src.read(length)
                assert len(payload) == length and payload == dst.read(length)
                hashes.append(hashlib.sha256(payload).hexdigest())
    return {"tiles": len(hashes), "compressed_payloads_equal": True, "tile_sha256": hashes}


def acquire(destination: Path) -> None:
    destination.mkdir(exist_ok=False)
    bulk = destination / "bulk"
    bulk.mkdir()
    for name in ("NOTICE", "CITATION.txt", "source.json"):
        (bulk / name).write_bytes(Path(__file__).parents[1].joinpath("raster_compression", name).read_bytes())
    (bulk / "README.md").write_text(
        "GRIT overview-removal samples. CC BY-NC 4.0; see NOTICE and CITATION.txt. "
        "Native 1024-square crops; 512 tiles, BigTIFF DEFLATE/no predictor. "
        "Inputs add nearest-neighbour levels 2 and 4, unlike the source overview pyramid. "
        "Outputs remove overviews only; no native resampling or hydrology changes.\n"
    )
    meter = Meter({f"{kind}.tif": BASE + f"aux/d8/flow_{kind}.tif" for kind in ("acc", "dir")}, 256 * 1024**2)
    report: dict[str, Any] = {
        "complete": False,
        "windows": WINDOWS,
        "files": [],
        "byte_limit": meter.limit,
        "versions": {
            "python": platform.python_version(),
            "rasterio": rasterio.__version__,
            "gdal": rasterio.__gdal_version__,
            "numpy": np.__version__,
            "rio-cogeo": importlib.metadata.version("rio-cogeo"),
        },
        "platform": platform.platform(),
        "environment_options": ENV,
    }
    start = time.perf_counter()
    try:
        with meter.bridge() as bridge, rasterio.Env(**ENV):
            for label, coords in WINDOWS.items():
                window = Window(*coords)
                for kind in ("acc", "dir"):
                    path = bulk / f"{label}-{kind}-input.tif"
                    with rasterio.open(f"{bridge}/{label}/{kind}.tif", sharing=False) as src:
                        assert (src.width, src.height) == (1070000, 500000)
                        assert src.crs.to_epsg() == 8857
                        assert tuple(src.transform)[:6] == (30, 0, -15000000, 0, -30, 8400000)
                        assert src.dtypes == (("float32",) if kind == "acc" else ("uint8",))
                        data, mask = src.read(1, window=window), src.read_masks(1, window=window)
                        profile = dict(src.profile, width=1024, height=1024, transform=src.window_transform(window))
                        source_overviews = src.overviews(1)
                    profile.update(
                        driver="GTiff",
                        tiled=True,
                        blockxsize=512,
                        blockysize=512,
                        compress="DEFLATE",
                        predictor=1,
                        zlevel=6,
                        BIGTIFF="YES",
                    )
                    with rasterio.open(path, "w", **profile) as dst:
                        dst.write(data, 1)
                    # Verify native fixture before adding its deliberately synthetic pyramid.
                    correctness = verify(path, data, mask, profile)
                    with rasterio.open(path, "r+") as dst:
                        dst.build_overviews([2, 4], Resampling.nearest)
                    with rasterio.open(path) as src:
                        np.testing.assert_array_equal(src.read(1).view("uint8"), data.view("uint8"))
                        np.testing.assert_array_equal(src.read_masks(1), mask)
                        assert src.overviews(1) == [2, 4]
                    report["files"].append(
                        {
                            "name": path.name,
                            "bytes": path.stat().st_size,
                            "source_overviews": source_overviews,
                            "fixture_overviews": [2, 4],
                            "valid_cells": int(np.count_nonzero(mask)),
                            "correctness": correctness,
                        }
                    )
                    print(path.name, "verified", flush=True)
        report["complete"] = True
    finally:
        report.update(
            http=meter.records,
            source_etags=meter.identities,
            body_bytes=meter.total,
            wall_seconds=time.perf_counter() - start,
            peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        )
        save(destination / "acquisition.json", report)


def rewrite(destination: Path) -> None:
    rows: list[dict[str, Any]] = []
    with rasterio.Env(**ENV):
        for source in sorted((destination / "bulk").glob("*-input.tif")):
            output = source.with_name(source.name.replace("-input.tif", "-output.tif"))
            assert not output.exists(), "refusing overwrite"
            start = time.perf_counter()
            copy(
                source,
                output,
                driver="COG",
                OVERVIEWS="NONE",
                BIGTIFF="YES",
                BLOCKSIZE=512,
                COMPRESS="DEFLATE",
                PREDICTOR="NO",
                LEVEL=6,
                NUM_THREADS=1,
            )
            seconds = time.perf_counter() - start
            correctness = verify_output(source, output)
            rows.append(
                {
                    "input": source.name,
                    "output": output.name,
                    "input_bytes": source.stat().st_size,
                    "output_bytes": output.stat().st_size,
                    "rewrite_seconds": seconds,
                    "correctness": correctness,
                    "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                }
            )
            save(destination / "rewrite.json", {"files": rows, "complete": False})
    assert len(rows) == 4
    save(destination / "rewrite.json", {"files": rows, "complete": True})


def verify_remote(destination: Path, public_base: str) -> None:
    paths = sorted((destination / "bulk").glob("*-output.tif"))
    assert len(paths) == 4
    meter = Meter({p.name: public_base.rstrip("/") + "/" + p.name for p in paths}, 32 * 1024**2)
    rows: list[dict[str, Any]] = []
    report: dict[str, Any] = {"complete": False, "reads": rows}
    try:
        with meter.bridge() as bridge, rasterio.Env(**ENV):
            for path in paths:
                sample = path.name.split("-")[0]
                coords = [896, 0, 128, 128] if sample == "greenland" else [896, 448, 128, 128]
                for label, box in (("mixed", coords), ("four_tiles", [448, 448, 128, 128])):
                    before = meter.total
                    window = Window(*box)
                    with rasterio.open(path.with_name(path.name.replace("-output", "-input"))) as src:
                        data, mask = src.read(1, window=window), src.read_masks(1, window=window)
                    start = time.perf_counter()
                    with rasterio.open(f"{bridge}/{label}/{path.name}", sharing=False) as src:
                        actual, actual_mask = src.read(1, window=window), src.read_masks(1, window=window)
                        seconds = time.perf_counter() - start
                        assert src.overviews(1) == []
                    np.testing.assert_array_equal(actual.view("uint8"), data.view("uint8"))
                    np.testing.assert_array_equal(actual_mask, mask)
                    rows.append(
                        {
                            "file": path.name,
                            "window": box,
                            "seconds": seconds,
                            "body_bytes": meter.total - before,
                            "valid_cells": int(np.count_nonzero(mask)),
                        }
                    )
        report["complete"] = True
    finally:
        report.update(http=meter.records, body_bytes=meter.total)
        save(destination / "remote.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["acquire", "rewrite", "verify", "verify-raw", "verify-remote"])
    parser.add_argument("destination", type=Path)
    parser.add_argument("extra", nargs="?")
    args = parser.parse_args()
    if args.action == "acquire":
        acquire(args.destination)
    elif args.action == "rewrite":
        rewrite(args.destination)
    elif args.action in ("verify", "verify-raw"):
        result = verify_output(args.destination, Path(args.extra))
        if args.action == "verify-raw":
            result.update(verify_payloads(args.destination, Path(args.extra)))
        print(json.dumps(result))
    else:
        verify_remote(args.destination, args.extra)
