# GRIT original component production

`scripts/produce_grit.py` converts the original GRIT v1.0 GeoPackage layers into
a local vector bundle. It preserves native attributes and nulls under `source_`
column names and records the exact source schema and renames in
`source-provenance.json`. HFX identities distinguish source products, regions,
layers and tiers even when native numeric IDs coincide.

This is a **local sample producer**, not a completed global delivery. Independent
verification is required before upload. The sample omits rasters honestly; the
final GRIT publication must reference the approved existing unchanged rasters.
No raster or snap copies are produced. No download, upload or provisioning occurs.

## Reproduce

Run with:

```sh
uv run --group vector-production python scripts/produce_grit.py inventory.json NEW_OUTPUT
```

 The output and adjacent
`NEW_OUTPUT-production.sqlite` must not already exist. The latter stores selected
row identities and graph references, not geometry; retain it on failure. Original
GeoPackages are reread by indexed `fid`. Do not publish this scratch database.

The JSON inventory contains `sources`, each with `path`, `region`, `product`, and
`archive: {path, md5}`. Paths identify local originals; `md5` is the published
Zenodo archive checksum. Allowed products are `segments`, `reaches`,
`segment_catchments`, `reach_catchments`, and `component_catchments`. Regional
products use their release region such as `SP`; components use `GLOBAL`.
The producer checks the archive MD5 and streaming SHA-256 equality between its
GeoPackage member and the loose input. Input fingerprints must agree before and
after conversion. The fixture-only `synthetic_fixture: true` skips ZIP checks and
must not be used for an original-source delivery.

For the complete small original example, set
`components: [70000129, 70115212, 370650032]` and supply the five SP/global
GeoPackages identified in [the source evidence](grit-river-evidence.md).
Select nodes through river endpoints, not an invented node catchment field.
This yields 1,197 catchments, 1,194 rivers and 1,176 nodes. The sample includes
the four-segment/21-reach diamond, six real component terminals, and two real
polygon-only components. Source flow edges and node incidence remain internal;
the producer rejects unresolved references rather than rewriting cuts as outlets.

## Transformations and limits

Geometry is exported from EPSG:8857 GeoPackage and reprojected with pyproj,
longitude/latitude axis order, without reversing, simplifying, clipping or repair.
The source geometries remain available in the originals for independent native-WKB
and CRS checks. `geometry_orientation=0` makes no vertex-order claim; source
endpoint references and directed edges remain authoritative.

Local normalized area uses WGS84 geodesic exterior-minus-hole area per polygon,
then sums MultiPolygon parts without signed cancellation. Native `source_area`
remains the original equal-area value. Upstream polygon-union area is not computed;
`up_area_km2` stays null. Native partitioned and mainstem-following drainage areas
retain their separate columns. Component outlets remain null; local polygon
outlets use the corresponding source river's downstream node.

Typed incoming groups contain 256 rows per feature family, concatenated across
layers in the documented product order (components, segment catchments, reach
catchments, segments, reaches), then region/table and ascending source `fid`.
A group may cross a layer boundary; only the final family group is short. The shared writer retains the 8 MiB logical batch budget
and oversized-singleton rule. Float32 geometry and graph bounds round outward.
Selected IDs, references, reciprocal edges, endpoint continuity, node incidence
and graph acyclicity are checked without repairing source hydrology. Cycle flags
and node labels remain source attributes, not hydrological certification.

The current checks do not certify worldwide polygon geometry. Independent source
fidelity checks and sampled containment/disjointness checks must report actual
coverage and justified numerical tolerances. Source-schema variations and
cross-region references outside the acquired original sample remain unverified;
unknown references stop processing. Full production resource sizing, native
categorical descriptions, public selective reads, external raster declarations
and publication receipts are separate delivery work, not promises of this sample.

## Measured local run

The fresh original component run produced 3,567 vector rows in 31.65 seconds,
including archive/member identity checks, original scans and before/after source
hashes. Peak RSS was 262,914,048 bytes. The vectors and provenance occupied about
1.89 MB; the retained external identity/reference scratch database occupied
1,134,592 bytes. These are local sample-production measurements, not remote-read,
consumer startup or global throughput measurements.

Independent Fiona original reads and modern GDAL reprojection checked every
source row and coordinate in the sample: 1,197 catchments, 1,194 rivers and 1,176
nodes. The maximum coordinate difference was 0.0 degrees. This initial verification
also checked source attributes/types/nulls, references, graphs, lookup coverage
and artifact identities. Source-schema ledger checks and four original diamond
polygon-group checks also passed. Actual output byte-budget/maximal-slice proof
is a separate remaining verifier check; this is not full format-verifier completion.

The exact fresh manifest SHA-256 is
`ea15082eaddc7bd043fba4e84581a48875ab78a2f6c2ed91b6d37c42b34215fd`.
The initial failed sample retained a scratch database inside its bundle; this was
moved outside without deleting its bytes, and a new untouched output established
the corrected producer result. Tests now require exact bound-artifact coverage.
