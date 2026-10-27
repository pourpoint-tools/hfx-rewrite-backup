# HFX 0.4.0 Raster Data

This optional auxiliary contract extends the [bundle](bundle.md)
with a native-grid D8 direction and accumulation pair.
HFX 0.4.0 explicitly supports native-only, internally tiled, cloud-friendly TIFF
layout without overviews. This is not a claim of strict overview-bearing COG
conformance. Successful packaging does not certify hydrological equivalence or source hydrology.

## Manifest declaration

Each pair is an entry in the root manifest's `auxiliary` array, alongside any
other auxiliaries. Both artifact references are required. A local path is relative
to the bundle root and must not escape it; its file has an entry in the root
`artifacts` fingerprint map. Alternatively, `{ "external": "key" }` resolves to
the root `external_artifacts` identity under the
[external raster rules](bundle.md#external-raster-artifacts). Do not place
URLs or `../` escapes in local-path strings. Both forms require size, full SHA-256
and head/tail SHA-256 as defined by the
[bundle identity rules](bundle.md#artifact-identity-and-range-access).
A retained source manifest is provenance, not a raster declaration.

A pair declaration has this structure (CRS, encoding and units describe that pair):

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

