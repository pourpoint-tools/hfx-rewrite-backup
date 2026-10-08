# HFX 0.4.0 raster delivery

Make the existing GRIT HFX 0.4.0 publication self-contained: its root manifest
must identify both the delivered vectors and a native-resolution direction and
accumulation raster pair. Remove unused raster overviews while preserving the
original full-resolution data. This is the agreed delivery handoff for
[HFX #6](https://github.com/pourpoint-tools/hfx/issues/6), following the compression
and overview-removal experiments. Publication of this vision is not execution;
begin delivery only through a separately requested implementation workflow.

**Do not delete, overwrite, move, or otherwise modify any HFX 0.3.0 cloud data.**
This includes its rasters, vectors, manifests, attribution and other objects.
Overview removal acts only on disposable VM-local copies. Existing 0.4.0 vector
artifact bytes and identities also remain unchanged.

## Outcome and format

Publish the new raster files within
`https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0/` and declare them
explicitly in its root `manifest.json`. No dependency on the 0.3.0 publication
is needed to discover or read the complete 0.4.0 dataset. Retained source
provenance is not an implicit raster declaration.

The maintainer has no external users of this in-development release. Earlier
immutable-publication wording is not a binding freeze: updating this existing
0.4.0 manifest is intended, and a new prefix or format version is not required.
Reconcile the current vector documentation's blanket publication rules with
this approved extension, without weakening artifact identity or consistent
selected reads. Preserve the existing vector contract and manifest bindings.

Document a lean 0.4.0 raster contract using the pinned
[D8 raster v2 contract](https://github.com/CooperBigFoot/hfx/blob/c18a8a6a115e2045080d8752279d39db2b9b29b6/spec/aux/d8_raster/v2.md)
as the baseline. Preserve its explicit ESRI, TauDEM and GRASS direction
conventions, supported accumulation units (cells or km²), native-grid pairing,
header-authoritative dtype/nodata and coverage/overlap semantics. Do not force
all fabrics into GRASS, one CRS, one numeric representation, or one compression
recipe. The manifest declares meaning; TIFF headers declare storage details.
Leave exact additive documentation/schema mechanics to implementation, without
silently changing the meaning of existing declarations. Coordinate the resulting
contract handoff with Pourpoint; this delivery does not implement its reader.

For these GRIT artifacts specifically:

- Preserve every native direction value, accumulation float32 bit pattern and
  each validity mask, including nodata. Preserve the dimensions, alignment,
  transform, CRS, direction meaning and accumulation units.
- Retain 512 × 512 internal tiles and lossless DEFLATE without a predictor.
  Remove all overviews; no resampling, flow-direction warp or hydrologic
  recalculation is permitted.
- Produce a cloud-friendly tiled BigTIFF layout suitable for bounded range
  reads. Explicitly document native-only layout support: overview recommendations
  may produce expected validator warnings. Do not claim strict overview-bearing
  conformance or suppress unrelated validation failures.
- Preserve GRIT's CC BY-NC 4.0 license, source attribution, source caveats and
  provenance. Explain the overview removal in the publication documentation.

Observed source grid: 1,070,000 × 500,000 cells, EPSG:8857, affine
`(30, 0, -15000000, 0, -30, 8400000)`. Direction is GRASS uint8/nodata255;
accumulation is width-partitioned drainage area in km², float32/nodataNaN.
Preserving these data is not a new certification of source hydrology.

## Production approach and remaining engineering checks

Reuse the retained Hetzner VM, with suitable scratch storage, rather than
staging hundreds of gigabytes on the laptop. Start from the proposal of a
500 GB attached volume and process one raster at a time. Confirm disk headroom
for the actual tool path before acquiring inputs. The root disk alone is too
small. One-time processing time is acceptable within the agreed spending cap.

Prefer compressed-tile copying if global checks establish that it is safe.
The trial used `gdaladdo -clean` on a disposable local input, then cogger v0.1.1
to write a new file. Cleaning only unlinks overview directories; it does not
reclaim their bytes. Stock cogger needs a random-access local input. Download
and verify the source on the VM, not the laptop, before any local mutation.
Retain trustworthy source fingerprints and verification evidence through that
mutation; keep the production source remote and untouched.

Do not infer global readiness from the tiny trial. Investigate cogger's >4 GB
BigTIFF output, global tile-index memory and metadata preservation before
committing to it. Its metadata whitelist can omit unknown tags and
ImageDescription. The user supplied a local checkout at
`/Users/nicolaslazaro/Desktop/thirdparty/cogger`; confirm its revision before use.
Pinned upstream evidence and the tested binary are identified in the trial
report. Do not silently drop meaningful source metadata.

If compressed copying is unsuitable, use the demonstrated GDAL COG lossless
rewrite path with overviews disabled. Exact commands, compression level for a
rewrite, bounded preflight tests and resource monitoring are engineering choices.
No custom storage engine or general conversion framework is wanted. Report
material blockers rather than extending the task into tool development.

The source pair is approximately 256 GB, with approximately 69 GB in overviews.
These are planning figures, not guaranteed output sizes or runtime estimates.
The small experiments do not establish global throughput or memory bounds.

## Verification and publication

Full conformance and publication verification belongs with the producer, not
in each consumer's startup. Use bounded-memory, complete verification of native
cells/float32 bit patterns and separate masks against source data, plus matching
grid metadata. For a raw-copy path, verify every native compressed tile payload
and the decoding metadata needed to interpret it; organize checks to avoid
redundant passes where evidence is equivalent. Confirm no overviews, correct
BigTIFF offsets/layout, and usable native range reads. Whole-file identities
and source/output comparisons are separate from hydrologic validation.

Record output size, full SHA-256 and the existing 0.4.0 head/tail fingerprints.
Keep small reproducible verification and operational receipts outside bulk data.
Inspect the actual R2 configuration and existing destination objects before
writing. Use the configured `upstream-r2` profile without publishing credentials
or changing bucket policy. Track exact objects owned by this run; never use a
broad deletion against either production prefix.

Upload only verified new raster outputs. Verify uploaded identities and focused
public paired-window reads, including tile boundaries, valid cells and nodata.
Check exact values and masks against independent source references. Confirm
that vector artifact identities remain unchanged and existing selective vector
access still works. No new benchmark suite or latency guarantee is required.

Publish the amended root manifest last, with raster declarations and artifact
bindings. Account for cached old manifests and any changed documentation objects:
readers must see either the old vector-only declaration or the verified complete
one, not a manifest pointing at incomplete artifacts. Preserve the previous
manifest/changed small-object bytes and identities in the run receipts for
recovery; record the new identities and applicable cache handling. Keep
publication provenance distinct from unchanged source provenance.

Success is a documented 0.4.0 contract, verified self-contained public GRIT bundle,
unchanged 0.3.0 objects and vector data, and a concise handoff for Pourpoint.
Update #6 with delivery evidence; do not resume Pourpoint implementation here.

## Budget, retained VM and cleanup

The maintainer approved **US$20 total infrastructure spending for this job**,
including retained-VM time, compute and attached storage. Account for already
accrued retention charges; this is not an additional unlimited retention period.
Recheck current pricing, VAT, FX and any relevant transfer charges. The proposal
was about €0.19/hour including the observed VAT with a 500 GB volume; it is not
a runtime or total-job-cost promise. Track cumulative spend, an estimated cap
time and an earlier check-in. Seek approval before exceeding the cap; stop
starting new work and arrange a resumable stop/cleanup early enough to stay
within it. Idle resources keep billing. Do not rely on an old reminder as a
provider-enforced budget limit.

The trial handoff recorded:

- Server `169381744`, `hfx-overview-trial-20261008-1246`, CCX23, `hel1`:
  4 dedicated cores, 16 GB RAM, 160 GB root disk, no attached volumes.
- Access `root@89.167.2.16`, existing `nicolas-workstation` SSH key.
  Primary IP IDs: IPv4 `154299103`, IPv6 `154299104`.
- Checkout `/root/hfx` at trial execution revision `5078ad5`; tools
  `/root/overview-tools`; retained fixtures/results `/root/grit-overview-run`.
- Created 2026-10-08 12:46:32 UTC; last authoring check found it running.
  Verify current ownership, state, revision and active jobs before reuse.

The previous US$5 trial cap/reminder must be reconciled with this job's budget
and actual accrued charges. Preserve useful trial evidence before reusing paths.
Do not expose credentials in the repository or handoff.

After successful publication and verification, remove this job's temporary bulk
files and infrastructure, including VM, attached volumes and owned IPs; verify
cleanup and retain small receipts. This cleanup authority **never includes any
0.3.0 cloud data, delivered 0.4.0 artifacts, or unrelated resources**. On failure,
retain a clear recovery handoff and arrange cleanup within budget rather than
leaving indefinite charges. No raster rewrite begins merely because this vision
is merged.

## Durable evidence and boundaries

- [Compression results, PR #9](https://github.com/pourpoint-tools/hfx/blob/a418789b3bc4e1e4d2ed0b1e07a19df4797a1110/experiments/raster_compression/README.md):
  predictors increased all sampled accumulation sizes; no demonstrated reason
  to change compression. ZSTD without a predictor was not tested; no claim of
  globally optimal encoding is made.
- [Overview-removal results and VM handoff, PR #12](https://github.com/pourpoint-tools/hfx/blob/5616e6f6082897fcdf6afaed74a96eb08d48c601/experiments/raster_overviews/README.md):
  both methods preserved exact sample data; raw copying preserved all 16 sample
  compressed tiles. BigTIFF inputs produced small classic-TIFF cogger outputs,
  so >4 GB output remains a production preflight concern.
- [0.3.0 source manifest](https://basin-delineations-public.upstream.tech/grit/hfx-v0.3.0/manifest.json)
  and [source README](https://basin-delineations-public.upstream.tech/grit/hfx-v0.3.0/README.md)
  identify both `aux/d8/flow_dir.tif` and `aux/d8/flow_acc.tif` and source hashes.
- [Existing vector contract](../../docs/v0.4.0/vector-data.md) and
  [publication verification](../../docs/v0.4.0/grit-verification.md).

Keep supporting code small, typed, tested and specific to delivery. Use the
repository's uv, Ruff, ty and test-first conventions. Bulk data stays outside
Git. Pourpoint readers, delineation algorithms, batching/caches, vector redesign,
new source fabrics and further codec research are out of scope.
