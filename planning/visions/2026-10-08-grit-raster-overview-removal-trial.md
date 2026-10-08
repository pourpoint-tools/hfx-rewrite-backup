# GRIT raster overview removal trial

Run a short, bounded experiment for [HFX #10](https://github.com/pourpoint-tools/hfx/issues/10)
to find a practical way to remove raster overviews without changing native data.
Return the evidence to [#6](https://github.com/pourpoint-tools/hfx/issues/6) so the
maintainer can decide how to run the global rewrite. This vision authorizes the
small trial, not global processing or a production publication.

## Agreed direction

Remove overviews: lower-resolution display is not needed. Keep native cells,
grid, CRS, nodata and hydrologic meaning unchanged. For these GRIT files, retain
512 × 512 tiles and DEFLATE without a predictor. Do not reopen codec selection,
warp flow direction, resample native cells or rederive hydrology. These choices
are not universal HFX compression or direction-encoding requirements.

The eventual target is a self-contained HFX 0.4.0 publication. Its current
publication is under active development, not frozen, but this trial must leave
all production objects and manifests unchanged. HFX #6 remains in discovery;
Pourpoint reader and engine implementation are outside this work.

Investigate whether a mature tool can produce a base-resolution-only,
cloud-friendly TIFF by copying existing compressed tiles without decoding and
recompressing them. Verify rather than assume this capability. Ordinary lossless
rewriting is an acceptable fallback if simpler or more practical. Do not build
a general conversion framework. Tool choice and exact sample construction are
implementation decisions.

## Bounded experiment and evidence

Use small representative inputs with overviews and relevant source structure:
BigTIFF, tiled uint8 direction and float32 accumulation, including valid and
nodata regions. Reuse the sampling knowledge from the
[compression experiment](../../experiments/raster_compression/README.md).
Its temporary samples were deleted and its outputs had no overviews. If a
source-derived fixture needs overviews added, explain how it differs from the
global source. Bound source acquisition before starting it; no complete raster
download is authorized. Keep bulk files and sensitive logs outside Git.

Establish the following with small reproducible receipts and a concise report:

- Exact decoded direction values, float32 bit patterns and separate validity
  masks match the input; native grid metadata and nodata are preserved.
- Output has no overviews and passes an explicit cloud-layout validation, not
  merely a successful GDAL open. Verify selected remote reads too.
- If claiming compressed-tile preservation, compare compressed payloads.
- Record input/output sizes, wall time, peak memory, scratch disk and temporary
  file needs, commands and tool versions. Record actual transferred bytes where
  measured and state measurement boundaries and gaps.
- Explain whether the method requires a seekable local output and whether full
  local input acquisition or selected remote ranges is the practical global
  approach. Distinguish observations from estimates: small crops do not establish
  global throughput, tile-index cost or request overhead. Do not simply scale a
  tiny timing into a global runtime prediction.

This should be a short trial, not hours of benchmarking. Return an honest
limitation or a lossless-recompression recommendation rather than expanding
into an open-ended tool-development project.

## Resources and authority

Use a temporary Hetzner VM rather than staging global data on the laptop.
The trial budget is **US$5**. Check current prices, taxes and currency conversion
before provisioning. The provisional candidate in #10 is CCX23 (4 dedicated
cores, 16 GB RAM, 160 GB local disk) in Germany or Finland. Its earlier estimate
with a 500 GB volume and IPv4 was about €0.20/hour including the observed VAT;
that is not a current quote, runtime estimate or requirement to attach that
volume. Allocate only needed storage and keep spending within the budget.

Temporary R2 sample writes are authorized using the existing AWS CLI
`upstream-r2` profile. The maintainer has admin rights, but this is not permission
to broaden this trial. Check the configured endpoint and destination. Use a new,
disjoint trial-owned prefix, preserve attribution, track exactly which objects
belong to the run, and remove those temporary samples after verification.
Verify cleanup and retain small receipts. Do not change bucket policy, existing
cloud data, production replacements or live manifests. Do not expose credentials.

On success, retain the trial VM and needed storage for possible reuse after the
maintainer reviews the results. Leave no conversion jobs running. Report the
ongoing hourly cost and explicitly state that billing continues, including
while idle. Notify the maintainer before retained-resource charges reach the
budget cap; retention is not authorization for unlimited spending or global
processing. Arrange cleanup with the maintainer if the trial fails or is
abandoned. Delete only trial-owned resources when cleanup is authorized;
final cleanup must include the VM, volumes and IP, not merely power-off.

## Result and handoff

Return a short recommendation to #6: the command/tool path, what was actually
verified, remaining risks, and a proposed VM/disk configuration and cost for the
full job. Preserve reproducible evidence in the repository, without bulk data.
Include the retained server ID/name, region, access method without credentials,
volume IDs/mounts, working directories, exact code revision, environment,
commands, results and remaining files.

The maintainer reviews these findings and decides how to proceed. Do not start
the global rewrite, download complete rasters, upload production replacements
or change the raster contract under this vision.

## Source context

The [source manifest](https://basin-delineations-public.upstream.tech/grit/hfx-v0.3.0/manifest.json)
and [source README](https://basin-delineations-public.upstream.tech/grit/hfx-v0.3.0/README.md)
identify `aux/d8/flow_dir.tif` and `aux/d8/flow_acc.tif`. The pair is approximately
256 GB; roughly 69 GB of overview storage is an earlier estimate from live tile
offsets, not a new full-file measurement. Removing overviews saves storage but
does not inherently accelerate native reads.

Observed native metadata: 1,070,000 × 500,000 cells, EPSG:8857, 30 m,
affine `(30, 0, -15000000, 0, -30, 8400000)`; GRASS direction uint8/nodata255,
accumulation in km² float32/nodataNaN. Metadata observations do not certify all
source cells. Preserve GRIT's CC BY-NC 4.0 license and source attribution; use
the existing experiment's attribution records as a starting point.
