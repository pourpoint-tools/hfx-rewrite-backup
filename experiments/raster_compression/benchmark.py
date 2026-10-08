"""Paired direction/accumulation reads; three rotated candidate rounds."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.io import DatasetReader
from rasterio.windows import Window

from experiments.raster_compression.measure import ENV, Array, Meter, save

CANDIDATES = ["deflate", "deflate-fp", "zstd-fp"]
WINDOWS = {"within": [128, 128, 128, 128], "boundary": [448, 448, 128, 128]}
# Frozen after examining acquired masks, before any read timings.
OVERRIDES = {"greenland": {"within": [896, 0, 128, 128]}, "madagascar": {"boundary": [896, 448, 128, 128]}}


def arrays(acc: DatasetReader, direction: DatasetReader, window: Window) -> list[Array]:
    return [
        acc.read(1, window=window),
        acc.read_masks(1, window=window),
        direction.read(1, window=window),
        direction.read_masks(1, window=window),
    ]


def check(actual: list[Array], expected: list[Array]) -> None:
    for left, right in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(left.view("uint8"), right.view("uint8"))


def main(destination: Path) -> None:
    acquisition = json.loads((destination / "acquisition.json").read_text())
    ledger = json.loads((destination / "objects.json").read_text())
    urls = {
        entry["key"].rsplit("/", 1)[-1]: ledger["public_base"] + entry["key"].rsplit("/", 1)[-1]
        for entry in ledger["objects"]
        if entry["key"].endswith(".tif")
    }
    meter = Meter(urls, 1024**3)
    report: dict[str, Any] = {
        "complete": False,
        "rounds": 3,
        "windows": WINDOWS,
        "window_overrides": OVERRIDES,
        "environment_options": ENV,
        "reads": [],
        "http": [],
    }
    counter = 0
    try:
        with meter.bridge() as bridge, rasterio.Env(**ENV):
            for mode in ("local", "remote"):
                for sample in acquisition["samples"]:
                    name = sample["name"]
                    with (
                        np.load(destination / "bulk" / f"{name}-acc-source.npz") as a,
                        np.load(destination / "bulk" / f"{name}-dir-source.npz") as d,
                    ):
                        source = [a["cells"], a["mask"], d["cells"], d["mask"]]
                    for repetition in range(3):
                        order = CANDIDATES[repetition:] + CANDIDATES[:repetition]
                        for candidate in order:
                            for label, coords in (WINDOWS | OVERRIDES.get(name, {})).items():
                                window = Window(*coords)
                                col, row, width, height = coords
                                expected = [data[row : row + height, col : col + width].copy() for data in source]
                                files = [f"{name}-acc-{candidate}.tif", f"{name}-dir-deflate.tif"]
                                counter += 1
                                # URL preparation, reader opening and all four arrays are in fresh timing.
                                before = len(meter.records)
                                start = time.perf_counter()
                                paths = [
                                    f"{bridge}/{counter}/{f}" if mode == "remote" else str(destination / "bulk" / f)
                                    for f in files
                                ]
                                with (
                                    rasterio.open(paths[0], sharing=False) as acc,
                                    rasterio.open(paths[1], sharing=False) as direction,
                                ):
                                    actual = arrays(acc, direction, window)
                                    elapsed = time.perf_counter() - start
                                    after = len(meter.records)
                                    report["reads"].append(
                                        {
                                            "mode": mode,
                                            "sample": name,
                                            "candidate": candidate,
                                            "window": label,
                                            "round": repetition,
                                            "read": "fresh",
                                            "seconds": elapsed,
                                            "request_start": before,
                                            "request_end": after,
                                            "requests": after - before,
                                            "body_bytes": sum(r["body_bytes"] for r in meter.records[before:after]),
                                        }
                                    )
                                    check(actual, expected)
                                    before = len(meter.records)
                                    start = time.perf_counter()
                                    actual = arrays(acc, direction, window)
                                    elapsed = time.perf_counter() - start
                                    after = len(meter.records)
                                    report["reads"].append(
                                        {
                                            "mode": mode,
                                            "sample": name,
                                            "candidate": candidate,
                                            "window": label,
                                            "round": repetition,
                                            "read": "repeated",
                                            "seconds": elapsed,
                                            "request_start": before,
                                            "request_end": after,
                                            "requests": after - before,
                                            "body_bytes": sum(r["body_bytes"] for r in meter.records[before:after]),
                                        }
                                    )
                                    check(actual, expected)
                    print(mode, name, "verified", flush=True)
                    report["http"] = meter.records
                    save(destination / "measurements.json", report)
        report["complete"] = True
    finally:
        report["http"] = meter.records
        save(destination / "measurements.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    main(parser.parse_args().destination)
