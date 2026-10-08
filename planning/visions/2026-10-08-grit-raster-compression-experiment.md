# GRIT raster compression experiment

Measure how lossless compression affects GRIT raster size and selected-window
reads, using small samples locally and on R2. The maintainer wants measurements
to inform their own later decisions, not a recommended encoding or a judgment
about whether a global rewrite is worthwhile.

This vision settles the experiment in [HFX #7](https://github.com/pourpoint-tools/hfx/issues/7).
It supersedes that issue's local-first restriction and request for a rewrite
recommendation. Return the results to [HFX #6](https://github.com/pourpoint-tools/hfx/issues/6),
which remains in discovery. Do not implement a raster contract or change production.

## Experiment

The implementing agent owns sample selection, compression settings, repetitions,
and measurement design. Keep the harness small and proportional. Do not ask the
maintainer to choose routine experiment details.

- Fetch a bounded set of native-resolution, tile-aligned patches from varied
  regions, including dense data, sparse coverage, and nodata boundaries. Record
  the selection and download volume. No full-raster download or global conversion.
- Compare accumulation encoded with DEFLATE/no predictor,
  DEFLATE/floating-point predictor, and ZSTD/floating-point predictor. Use the
  same sample cells and 512 × 512 tiles across candidates. Record all settings
  and tool versions. Keep direction compression unchanged and use the same
  direction samples for paired-window measurements.
- Omit overviews from every comparison file. Report the existing overview storage
  estimate separately; do not attribute overview removal to codec savings or
  native-read speed improvements.
- Verify decoded float32 bit patterns, direction values, and separate validity
  masks against the source samples. Preserve native cells, grid placement, CRS,
  nodata, direction meaning, and accumulation units. Crops must retain the correct
  native-grid origin. Do not warp, resample, or re-derive hydrology.
- Measure compressed bytes, encoding cost, and repeated local decoding cost.
- Upload the small baseline and alternatives to the same R2 bucket under a new,
  unique experiment prefix. Measure actual raster HTTP response-body bytes,
  request counts, and elapsed time through usable arrays. Include fresh-reader
  and repeated-window reads under comparable conditions. Include opening and
  preparation in the fresh-reader total; identify timed boundaries explicitly.
  Keep correctness and sample acquisition outside read timings.

Compare like-sized hosted samples rather than treating a cropped candidate
versus the global source as an encoding-only comparison. Include useful
within-tile and tile-boundary windows. Existing Pourpoint workloads and evidence
can be reused where appropriate; they do not supply nodata coverage on their own.

## Evidence, not a decision

Deliver a short comparison, small machine-readable results, correctness evidence,
and reproducible commands/settings. Describe observations and measurement limits;
do not rank candidates, recommend further work, or set a required winner or
savings/performance threshold. A slower or larger candidate is a valid result.

Report sample coverage and limitations. Sample compression ratios are not global
predictions. Small TIFFs do not reproduce the global tile-index cost. A fresh
reader does not establish a cold CDN cache. Record cache conditions, run ordering,
and relevant environment details; do not claim controlled remote caches or
latency guarantees. Local timings alone do not establish remote performance.
Requested ranges, TIFF tile lengths, and Content-Length headers alone are not
measurements of actual received response-body bytes. State the byte metric
precisely rather than claiming total wire traffic.

Keep bulk data and sensitive diagnostics outside Git. Retain enough small source
identifiers, window coordinates, settings, hashes, and measurement records to
reproduce the experiment after cleanup. Return a concise results link to #6 and
#7 without selecting the later format/publication approach.

## Authorization and cleanup

The maintainer authorizes bounded downloads and experiment uploads to R2.
The local AWS CLI has an `upstream-r2` profile with an R2 endpoint configured;
credentials, bucket permissions, and the public-read route were not tested during
discovery. Inspect the actual configuration before use. Keep credentials and
sensitive logs out of Git and reports.

Use a new experiment prefix and track exactly which objects this run creates.
Never overwrite existing objects, change production manifests, or change bucket
access policy as part of this experiment. If access requires broader changes,
report the blocker rather than expanding authorization.

After measurements and correctness records are verified and saved, delete this
experiment's remote objects and local bulk artifacts. Verify cleanup and report
any leftovers or failures. Do not remove unrelated files or objects. Preserve
GRIT's CC BY-NC 4.0 attribution in retained evidence and sample distribution.

No production integration, global conversion, engine implementation, or
format/publication decision is in scope. Publishing this vision does not itself
start the experiment.

## Starting evidence

- [GRIT 0.3.0 manifest](https://basin-delineations-public.upstream.tech/grit/hfx-v0.3.0/manifest.json)
  and [source README](https://basin-delineations-public.upstream.tech/grit/hfx-v0.3.0/README.md).
  Raster paths are `aux/d8/flow_dir.tif` and `aux/d8/flow_acc.tif`.
- #7 records bounded inspection: 512 × 512 tiles, DEFLATE with no predictor,
  metadata before pixel data, smaller overviews before full-resolution tiles,
  and working HTTP 206 responses. Historical records report COG validation;
  this is not a fresh full-file validation.
- Source sizes reported in #6 are 50,686,516,478 bytes for direction and
  205,069,870,081 bytes for accumulation. #7 estimates roughly 69 GB of the pair
  is overviews from live tile offsets. Native readers already skip those levels.
- Shared grid: 1,070,000 columns × 500,000 rows, EPSG:8857, affine
  `(30, 0, -15000000, 0, -30, 8400000)`. Direction is GRASS uint8/nodata255;
  accumulation is km² float32/nodataNaN.
- [Pourpoint's merged access report](https://github.com/pourpoint-tools/pourpoint/blob/8849ba565bd855375f460a0996c93b08e5608661/experiments/terminal_raster_access/README.md)
  supplies frozen native windows, tile-boundary cases, and independent decoding
  evidence. Its five selected windows contain no nodata. It did not measure
  actual raster response bytes. Its timings are diagnostic, not guarantees.

HFX remains standards-first. Keep supporting research code isolated and minimal;
use the repository's uv, typed Python, Ruff, ty, and test-first conventions where
code is needed. Leave reversible implementation mechanisms to the implementing
agent rather than building a reusable benchmark framework.
