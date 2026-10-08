"""Acquire at most twelve 1024-square native-grid patches, then stop."""

from __future__ import annotations

import argparse
import hashlib
import platform
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.warp import transform
from rasterio.windows import Window

from experiments.raster_compression.measure import BASE, ENV, Meter, encode, save, verify

# Inland rainforest, delta/coast, arid drainage, island and ice-margin candidates.
LOCATIONS = [
    ("amazon", -62.0, -4.0),
    ("nile_delta", 31.0, 31.4),
    ("sahara", 14.0, 24.0),
    ("greenland", -45.0, 60.0),
    ("madagascar", 49.5, -15.5),
    ("australia", 133.0, -25.0),
    ("new_zealand", 172.7, -43.6),
    ("florida", -81.0, 25.2),
    ("namibia", 14.5, -23.0),
    ("chile", -73.0, -45.0),
    ("iceland", -16.0, 66.0),
    ("indonesia", 119.5, -5.5),
]


def main(destination: Path) -> None:
    destination.mkdir(exist_ok=False)
    bulk = destination / "bulk"
    bulk.mkdir()
    for name in ("NOTICE", "CITATION.txt", "sample-README.md"):
        target = "README.md" if name == "sample-README.md" else name
        (bulk / target).write_bytes(Path(__file__).with_name(name).read_bytes())
    meter = Meter({f"{kind}.tif": BASE + f"aux/d8/flow_{kind}.tif" for kind in ("acc", "dir")}, 256 * 1024**2)
    report: dict[str, Any] = {
        "samples": [],
        "acquisition": [],
        "byte_limit": meter.limit,
        "source_base": BASE,
        "versions": {
            "python": platform.python_version(),
            "rasterio": rasterio.__version__,
            "gdal": rasterio.__gdal_version__,
            "numpy": np.__version__,
        },
        "environment": platform.platform(),
    }
    try:
        with meter.bridge() as bridge, rasterio.Env(**ENV):
            for label, lon, lat in LOCATIONS:
                x, y = transform("EPSG:4326", "EPSG:8857", [lon], [lat])
                col = int((x[0] + 15000000) / 30) // 512 * 512
                row = int((8400000 - y[0]) / 30) // 512 * 512
                window = Window.from_slices((row, row + 1024), (col, col + 1024))
                sample: dict[str, Any] = {
                    "name": label,
                    "selection_lon_lat": [lon, lat],
                    "window": [col, row, 1024, 1024],
                    "files": [],
                }
                for kind in ("acc", "dir"):
                    with rasterio.open(f"{bridge}/{label}/{kind}.tif", sharing=False) as src:
                        assert src.width == 1070000 and src.height == 500000
                        assert src.crs.to_epsg() == 8857
                        assert tuple(src.transform)[:6] == (30, 0, -15000000, 0, -30, 8400000)
                        assert src.block_shapes == [(512, 512)]
                        assert src.compression.name == "deflate"
                        assert src.tags(ns="IMAGE_STRUCTURE").get("PREDICTOR", "1") == "1"
                        data, mask = src.read(1, window=window), src.read_masks(1, window=window)
                        profile: dict[str, Any] = dict(
                            src.profile, width=1024, height=1024, transform=src.window_transform(window)
                        )
                        sample[f"{kind}_valid_fraction"] = float(np.count_nonzero(mask) / mask.size)
                        sample[f"{kind}_valid_cells"] = int(np.count_nonzero(mask))
                        sample[f"{kind}_transform"] = list(profile["transform"])[:6]
                        sample[f"{kind}_source_tags"] = src.tags()
                        sample[f"{kind}_nodata"] = "NaN" if kind == "acc" else src.nodata
                    # The exact source arrays remain outside Git until all comparisons are verified.
                    np.savez(bulk / f"{label}-{kind}-source.npz", cells=data, mask=mask)
                    settings = (
                        [("deflate", "DEFLATE", 1)]
                        if kind == "dir"
                        else [("deflate", "DEFLATE", 1), ("deflate-fp", "DEFLATE", 3), ("zstd-fp", "ZSTD", 3)]
                    )
                    for candidate, codec, predictor in settings:
                        path = bulk / f"{label}-{kind}-{candidate}.tif"
                        seconds = encode(path, data, mask, profile, codec, predictor)
                        sample["files"].append(
                            {
                                "name": path.name,
                                "kind": kind,
                                "candidate": candidate,
                                "bytes": path.stat().st_size,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                "encoding_seconds": seconds,
                                "codec": codec,
                                "predictor": predictor,
                                "level": 6 if codec == "DEFLATE" else 9,
                                "correctness": verify(path, data, mask, profile),
                            }
                        )
                report["samples"].append(sample)
                print(label, sample["acc_valid_fraction"], sample["dir_valid_fraction"], meter.total, flush=True)
                fractions = [s["acc_valid_fraction"] for s in report["samples"]]
                if (
                    len(fractions) >= 3
                    and any(f > 0.95 for f in fractions)
                    and any(0 < f < 0.25 for f in fractions)
                    and any(0.25 <= f < 0.95 for f in fractions)
                ):
                    break
    finally:
        report["acquisition"] = meter.records
        report["source_etags"] = meter.identities
        report["download_body_bytes"] = meter.total
        save(destination / "acquisition.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    main(parser.parse_args().destination)
