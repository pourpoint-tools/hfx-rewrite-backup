# GRIT raster compression measurements

Measured on 2026-10-08 for the [published vision](../../planning/visions/2026-10-08-grit-raster-compression-experiment.md).
These are observations from five small patches, not an encoding recommendation,
a global-size prediction, or a raster contract change.

## Comparison

All accumulation files contain the same native float32 cells, 512 × 512 tiles,
and **no overviews**. DEFLATE uses level 6; ZSTD uses level 9; one encoding thread.
The fixed direction files use DEFLATE level 6/no predictor (the source codec and
predictor); their combined size is 1,177,334 bytes. The source's compression level
was not independently identified. Direction is identical across paired reads.

| Accumulation encoding | Five files, bytes | Encode total, s | Local fresh / repeated median, ms | Remote fresh / repeated median, ms |
| --- | ---: | ---: | ---: | ---: |
| DEFLATE / no predictor | 4,055,251 | 0.709 | 8.45 / 4.99 | 1,049.40 / 8.40 |
| DEFLATE / floating-point predictor | 8,957,356 | 0.866 | 10.38 / 9.46 | 1,132.36 / 16.23 |
| ZSTD / floating-point predictor | 8,688,534 | 0.232 | 5.07 / 3.93 | 1,074.43 / 8.80 |

Times above cover **paired accumulation and direction** reads, including their
separate validity arrays. Each read median pools 30 observations: five patches,
two windows, three rounds. It is a descriptive summary, not a matched-effect
estimate. Individual records are in [measurements.json](measurements.json).
Encoding was measured once per file; totals include TIFF creation/write/close,
exclude validation, and do not include an fsync. Candidate order was fixed for
encoding. Local files and OS caches were warm from writing and validation.

| Encoding | Remote fresh body bytes / requests | Remote repeated body bytes / requests |
| --- | ---: | ---: |
| DEFLATE / no predictor | 19,942,437 / 186 | 1,632,726 / 12 |
| DEFLATE / floating-point predictor | 38,139,177 / 192 | 3,131,817 / 12 |
| ZSTD / floating-point predictor | 37,092,111 / 192 | 3,048,057 / 12 |

The predictor files were larger for every sampled patch at these settings.
Timing differences vary by window and cache state; no candidate is selected.
The existing **roughly 69 GB overview-storage estimate** for the global raster
pair is separate starting evidence from [#7](https://github.com/pourpoint-tools/hfx/issues/7),
not a new measurement here. Every comparison omits overviews. None of the table's
size differences comes from removing overviews, and native readers already skip them.

## Samples and correctness

Each crop is 1024 × 1024 native cells (four tiles); coordinates are zero-based
`column,row` on the unchanged EPSG:8857 grid, at 30 m. "Dense" means valid-cell
coverage, not river density. Locations were chosen geographically, then stopped
once dense, sparse and intermediate coverage were observed; this is not random sampling.

| Patch label | Native origin column,row | Valid cells / 1,048,576 | Valid fraction |
| --- | --- | ---: | ---: |
| Amazon | 302080,296960 | 1,048,576 | 1.000000000 |
| Nile delta | 591872,148480 | 1,048,576 | 1.000000000 |
| Sahara | 542720,178688 | 1,048,576 | 1.000000000 |
| Greenland | 391168,49152 | 7,444 | 0.007099152 |
| Madagascar | 654848,345600 | 951,002 | 0.906946182 |

Both source masks have the counts above. Accumulation float32 **bit patterns**,
direction uint8 values, and each separate validity mask matched after encoding.
Grid origin, dimensions, CRS, nodata, block shape and absent overviews were checked.
All timed local/remote arrays and masks then matched the source windows outside
timings. Direction retains GRASS meaning/nodata255; accumulation retains
width-partitioned drainage area in km²/nodataNaN. No warp, resampling or hydrology
calculation occurred. These checks preserve values, not certify source hydrology.

Default windows, relative to each crop, are `128,128,128,128` (within a tile) and
`448,448,128,128` (crossing four tiles). Before timing, mask inspection fixed two
overrides: Greenland within `896,0,128,128` includes sparse valid data and nodata;
Madagascar boundary `896,448,128,128` crosses two tiles and is 1.953125% valid.
The Greenland boundary window is all nodata; the experiment does not imply that
every window exercises mixed coverage. Source selection, exact transforms, ETags,
file hashes, decoded cell/mask hashes and encode times are in
[acquisition.json](acquisition.json).

Acquisition received **11,336,132 raster body bytes** (limit 256 MiB, at most twelve
candidate patches; stopped at five). A separate connectivity probe received 16
raster bytes. Source attribution/manifest downloads received 12,342 bytes. Two
initial HEAD attempts were rejected for the default Python user-agent; no raster
GET body was read in those attempts. No full raster or global index was downloaded.

## Timing and byte boundaries

- A localhost HTTP bridge forwards GDAL HEAD/Range requests to the same public R2
  route. It counts `len(response.read(...))` on **received upstream raster response
  bodies**, including opening metadata/range read-ahead. HEAD counts as a request
  with zero body bytes. These are not requested-range lengths, tile lengths,
  Content-Length estimates, or total wire traffic: headers/TLS/TCP are excluded.
- Fresh timing begins before per-reader URL/path preparation and opening both
  readers. It ends when both value arrays and both mask arrays are usable.
  Repeated timing reads the same window with those readers still open. Correctness
  checks and closing readers are outside both timings. Bridge startup, global GDAL
  configuration and source preparation are measurement setup, outside per-read totals.
- Unique localhost paths prevent GDAL's URL cache from carrying data between fresh
  readers. Repeated reads retain GDAL HTTP read-ahead. Decoded-block cache is disabled
  (`GDAL_CACHEMAX=0`), `VSI_CACHE=False`; this does not disable OS or CDN caches.
  Every observed HTTP response reported `CF-Cache-Status: DYNAMIC`; none had Age.
  Fresh readers **do not establish cold CDN caches**.
- Three rounds rotate candidate order: baseline/floating-DEFLATE/floating-ZSTD,
  then left-rotate by one each round. Samples run in table order; local before
  remote; within before boundary. All candidates use like-sized hosted crops,
  the same direction file, and identical windows. No global-source versus crop
  timing is presented as an encoding-only comparison.
- The bridge serializes requests, buffers each response and opens urllib connections
  rather than reproducing GDAL's native TLS/connection reuse. Its overhead is in
  the timings. These timings describe this metered path, not direct engine latency
  or latency guarantees. Small TIFFs do not reproduce global tile-index costs.
  Local timing alone does not establish remote performance.

Environment: macOS 15.7.3, arm64; Python 3.13.14, Rasterio 1.5.2, GDAL 3.12.2,
NumPy 2.5.3. Exact optional dependencies are in the repository uv lock.

## Reproduce and cleanup

From the repository root, use a **new external** `$RUN` directory that does not yet
exist. Only the publication/cleanup commands require the existing `upstream-r2`
profile and its configured R2 endpoint. Do not broaden permissions on failure.
The scripts remain an isolated one-off experiment, not a production reader.

```bash
uv sync --group raster-experiment
uv run --group raster-experiment pytest -q tests experiments/raster_compression/test_measure.py
uv run --group raster-experiment ty check --config 'src.include=["experiments"]' experiments
uv run --group raster-experiment python -m experiments.raster_compression.acquire "$RUN"
uv run --group raster-experiment python -m experiments.raster_compression.remote publish "$RUN"
uv run --group raster-experiment python -m experiments.raster_compression.benchmark "$RUN"
# Inspect and preserve the small JSON receipts before removing bulk files:
uv run --group raster-experiment python -m experiments.raster_compression.remote cleanup "$RUN"
```

The run created 23 objects / 22,883,020 bytes in a new UUID prefix in
`basin-delineations-public`, using conditional `If-None-Match: *` PUTs and a
persisted exact ownership ledger. Upload size, SHA metadata and ETags were checked.
After complete measurements were saved, every object was deleted with matching
ETag, every HEAD returned 404, and the prefix listed empty. All 33 local bulk
files / 59,588,220 bytes and empty failed-attempt bulk directories were removed.
No leftovers, production changes or bucket-policy changes. See [objects.json](objects.json)
and [cleanup.json](cleanup.json). Small receipts remain; published sample URLs no
longer exist. A failed/ambiguous upload or cleanup stops for inspection rather than
silently retrying or deleting unknown keys.

## Attribution

Derived samples and retained dataset evidence: **CC BY-NC 4.0**. Credit Michel
Wortmann, Louise Slater, Laurence Hawker, Yinxue Liu and Jeffrey Neal (2025),
*Global River Topology (GRIT) raster datasets*,
[doi:10.5281/zenodo.15715535](https://doi.org/10.5281/zenodo.15715535).
See the source [NOTICE](NOTICE) and [CITATION.txt](CITATION.txt). Cropping and codec
changes are the only transformations. These attribution files and a sample README
were uploaded alongside the temporary samples. HFX's code license does not
replace the dataset license.

## Repository checks

64 tests passed (56 existing plus eight experiment tests). Ruff lint/format,
configured repository ty, explicit experiment ty (including its tests), and
`uv build` passed. The default ty configuration includes only `src`; explicitly
including all pre-existing tests also exposes nine existing PyArrow stub/type
errors outside this change. Those files were not modified. Source manifest and
README identities are retained in [source.json](source.json).
