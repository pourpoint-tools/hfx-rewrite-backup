# HFX 0.4.0 Raster Data

This optional auxiliary contract extends the [vector bundle](vector-data.md)
with a native-grid D8 direction and accumulation pair. It retains the declaration
and meaning of the pinned [D8 raster v2 contract](https://github.com/CooperBigFoot/hfx/blob/c18a8a6a115e2045080d8752279d39db2b9b29b6/spec/aux/d8_raster/v2.md).
HFX 0.4.0 explicitly supports native-only, internally tiled, cloud-friendly TIFF
layout without overviews. This is not a claim of strict overview-bearing COG
conformance. Publishing this contract does not establish that GRIT raster delivery
has completed or implement a Pourpoint reader.

## Manifest declaration

Each pair is an entry in the root manifest's `auxiliary` array, alongside any
snap declarations. Both artifact paths are required, relative to the bundle
root, and must not escape it. Each file also has an entry in the root `artifacts`
fingerprint map, with size, full SHA-256 and head/tail SHA-256 as defined by the
[vector contract](vector-data.md#artifact-identity-and-range-access).
A retained source manifest is provenance, not a raster declaration.

Example declaration for the intended GRIT delivery (not a publication receipt):

```json
{
  "schema": "hfx.aux.d8_raster.v2",
  "artifacts": {
    "flow_dir": "aux/d8/flow_dir.tif",
    "flow_acc": "aux/d8/flow_acc.tif"
  },
  "metadata": {
    "crs": "EPSG:8857",
    "flow_dir_encoding": "grass",
    "flow_acc_units": "km2"
  }
}
```

The three metadata fields are required, without defaults or additional metadata
properties. `crs` is an uppercase EPSG authority string matching
`^EPSG:[1-9][0-9]*$`. `flow_dir_encoding` is `esri`, `taudem` or `grass`.
`flow_acc_units` is `cells` or `km2`. The manifest's existing top-level `crs`
remains the vector CRS (`EPSG:4326`); it does not override a raster entry's CRS.

## Native grid and headers

GeoTIFF headers are authoritative for dtype and nodata. Each raster must carry
a nodata tag; its value is not constrained by this contract. Do not duplicate
dtype or nodata in declaration metadata. Direction dtype is `uint8` or `int8`.
Accumulation dtype is `float32` for `cells` (upstream cell count), or `int32` or
`float32` for `km2` (upstream drainage area in square kilometers).

Both header CRSs must resolve to the declared CRS. A pair must share CRS,
dimensions, affine transform, pixel dimensions and grid alignment. Keep direction
on the grid where its neighbor pointers were derived: neither producers nor
consumers may warp it to another CRS. There is no universal raster CRS, numeric
representation or compression recipe.

Both files must be readable, internally tiled GeoTIFFs arranged for bounded
HTTP range reads. Use BigTIFF when offsets exceed classic TIFF limits. Native-only
layout is supported: overviews are not required. Record expected validator
warnings about missing recommended overviews separately; do not suppress other
layout or validation failures. Verify offsets, tile ranges and actual range
reads rather than inferring suitability from a file extension.

## Direction meaning

The declared encoding selects one column:

| Direction | ESRI | TauDEM | GRASS |
| --- | ---: | ---: | ---: |
| East | 1 | 1 | 8 |
| Southeast | 2 | 8 | 7 |
| South | 4 | 7 | 6 |
| Southwest | 8 | 6 | 5 |
| West | 16 | 5 | 4 |
| Northwest | 32 | 4 | 3 |
| North | 64 | 3 | 2 |
| Northeast | 128 | 2 | 1 |

ESRI uses powers of two. TauDEM numbers counterclockwise from east; GRASS
`r.watershed` numbers counterclockwise from northeast. For GRASS with `uint8`,
valid data codes are 0 through 8; 0 denotes a terminal cell with no downstream
neighbor. For signed GRASS values, a negative value gives the direction of its
absolute value and indicates flow exiting raster coverage. Negative values and
0 (sink or depression) are terminal for upstream tracing. Nodata is determined
by the header, not by guessing from the direction codes. Engines normalize the
declared encoding on read; this contract does not implement refinement.

## Coverage and overlap

Each entry declares its own CRS; entries may use different EPSG CRSs.
Geographically overlapping entries must be windows of the same grid: same CRS,
pixel dimensions, pixel basis and alignment. Every shared cell must have identical
direction and accumulation values in all overlapping entries. Entries on different
grids must have disjoint geographic footprints. A consumer may use any entry
covering the whole requested region; it need not mosaic or arbitrate between
coherent overlaps.

For each raster, transform the extent to EPSG:4326 with densified edge sampling
and check intersection with the manifest `bbox`. Sampling density is an
implementation choice. This is a gross-mislocation smoke check, not proof of
precise coverage. The union of entries should cover the manifest bbox. Consumers
may query coverage from headers at read time.

## GRIT delivery requirements

The [accepted delivery vision](../../planning/visions/2026-10-08-hfx-0-4-0-raster-delivery.md)
authorizes an additive extension at the existing 0.4.0 prefix. It requires:

- A 1,070,000 × 500,000 native grid, EPSG:8857, affine
  `(30, 0, -15000000, 0, -30, 8400000)`.
- GRASS `uint8` direction with nodata 255; width-partitioned drainage area in
  km² as `float32` accumulation with nodata NaN.
- Exact native direction values, accumulation float32 bit patterns and separate
  validity masks, including nodata; unchanged alignment and meaningful metadata.
- 512 × 512 internal tiles, lossless DEFLATE without a predictor, BigTIFF and no
  overviews. Removing overview storage must not resample, warp or recalculate
  hydrology. Mutate only disposable local copies, never 0.3.0 cloud objects.
- Unchanged vector artifact bytes and identities. Preserve CC BY-NC 4.0,
  attribution, source caveats and provenance; explain overview removal in new
  publication notes while retaining the original publication README bytes. Preservation is not a new certification of source hydrology.

The producer performs complete bounded-memory verification of native values,
float32 bits, separate masks and grid metadata. For raw compressed copying,
verify every native compressed tile payload plus its decoding metadata; equivalent
evidence need not require redundant full passes. Record output sizes, full hashes
and bounded fingerprints. Verify upload identities and public paired windows
against independent source references, including tile boundaries, valid cells
and nodata. Recheck vector identities and selective reads. These full checks are
producer duties, not a mandatory full-data scan at consumer startup.

## Publication and Pourpoint handoff

Follow the [publication rules](vector-data.md#artifact-identity-and-range-access).
Upload verified new rasters first and amend the root manifest last, retaining
existing vector declarations and bindings. Preserve previous manifest and changed
small-document bytes and identities in receipts. Record new identities and actual
cache handling. Add separately fingerprinted raster delivery notes instead of
replacing the existing README bound by old manifests. The existing root manifest
has `public,max-age=31536000,immutable` cache policy; cached copies may persist
until expiry. Publish the amended manifest with revalidation policy and verify
its origin body and cache-busted public reads. Cached old manifests must still
describe a valid vector-only bundle; new manifests must reference only complete,
verified artifacts. Keep
publication provenance separate from unchanged source-normalization provenance.
No read of the complete new declaration may depend on the 0.3.0 publication.

After delivery, provide Pourpoint with the final root URL and manifest identity,
raster declarations and identities, grid/encoding/units, native-only layout note,
verification evidence and retained source caveats. Coordinate reader support
explicitly; this document neither changes Pourpoint's current input contract nor
claims that its reader accepts these declarations. Delivery evidence and the
handoff belong to the completed publication, not to this documentation change.
