# HFX 0.4.0 Vector Data

The finalized GRIT production layout is specified in [Spatial GeoParquet layout](spatial-layout.md).
This page retains the earlier IPC physical layout and source field meanings.
The same version string does not imply reader compatibility; revised global delivery
is not claimed here.

## Bundle and manifest

A bundle contains one UTF-8 `manifest.json` and the artifacts it identifies.
Local artifact paths are relative POSIX paths within the bundle root and must not
escape it. Only explicit external raster references may name remote objects
([below](#external-raster-artifacts)). Each local path names
one immutable data or provenance file, except for the explicitly permitted
publication-document amendment described below. The manifest has these fields:

| Field | Type and meaning |
| --- | --- |
| `format_version` | String `"0.4.0"` |
| `fabric_name` | Lowercase ASCII source-fabric name |
| `fabric_version` | Optional source-fabric version string |
| `crs` | String `"EPSG:4326"` |
| `has_up_area` | Boolean; computed upstream areas are available when true, with per-row nulls permitted; all values are null when false |
| `topology` | `"tree"` or `"dag"`, describing supplied same-level catchment connectivity |
| `bbox` | Four finite numbers `[west, south, east, north]` covering the units |
| `unit_count` | Positive integer; catchment and lookup row count |
| `created_at` | RFC 3339 timestamp of source normalization |
| `adapter_version` | Source normalization adapter version string |
| `region` | Optional source subset string |
| `catchments` | `"catchments.arrow"` |
| `graph` | `"graph.parquet"` |
| `lookup` | `"lookup.arrow"` |
| `directory` | `"lookup-directory.json"` |
| `index_batch_rows` | Integer `65536` |
| `catchment_batch_bytes` | Integer `8388608` |
| `auxiliary` | Array of optional [D8 raster declarations](raster-data.md); an empty array is permitted |
| `rivers` | Optional river artifact declaration below |
| `river_nodes` | Optional node artifact declaration below; requires `rivers` |
| `catchment_connectivity` | One `{ "level": integer, "status": "supplied" or "not_supplied" }` entry per catchment level |
| `categorical_columns` | Optional array of typed column dictionaries below |
| `external_artifacts` | Optional map of external raster identities below |
| `source_manifest` | Optional relative path to original source manifest bytes, when supplied |
| `artifacts` | Object mapping every delivered file except `manifest.json` to its fingerprint |

Source identity, provenance, attribution, additional source fields and applicable
metadata are preserved. `source-manifest.json` and `source-README.md` are source
provenance. Artifact discovery uses the root manifest. River and node declarations
identify their artifacts; auxiliary declarations
identify raster pairs explicitly. New river bundles do not emit redundant snap
artifacts. Earlier snap declarations retain their historical meaning and files;
this revision does not rewrite those publications.
`NOTICE`, `CITATION.txt` and `README.md` carry applicable licensing, attribution,
transformation notes and dataset caveats.
Readers accept additional manifest fields and validate fields they use.

## Catchments

`catchments.arrow` is an Arrow IPC file containing one row per drainage unit.
Attributes and WKB occupy the same record batch. The required fields are:

| Field | Arrow type | Nullable | Meaning |
| --- | --- | --- | --- |
| `id` | `int64` | No | Positive dataset-local unique unit ID |
| `level` | `int16` | No | Nonnegative dataset-local resolution tier |
| `parent_id` | `int64` | Yes | Containing unit at a strictly coarser available level |
| `area_km2` | `float32` | No | Local geodesic area in km² |
| `up_area_km2` | `float32` | Yes | Inclusive same-level upstream area in km², under documented dataset semantics |
| `outlet_lon` | `float64` | Yes | Finite EPSG:4326 longitude of a single source-described outlet |
| `outlet_lat` | `float64` | Yes | Finite EPSG:4326 latitude of that outlet |
| `bbox` | `struct<xmin: float32!, ymin: float32!, xmax: float32!, ymax: float32!>` | No | Finite ordered, outward-covering EPSG:4326 bounds; `!` denotes non-nullable leaves |
| `geometry` | `binary` | No | Exact Polygon or MultiPolygon WKB in EPSG:4326 |

Source identity is retained as `source_namespace: string` and `source_id: string`
(non-nullable). A namespace identifies the source product and layer, including
region/basin where needed for unique source identity. The pair identifies a source
feature; preserve native ID columns and types independently of the string rendering.
Only unchanged catchment artifacts from the earlier normalized 0.4.0 publication
may retain their existing optional source identity fields when documented provenance
establishes the mapping. Newly produced catchments require both nonnullable fields.

Smaller levels are coarser. Each coarsest unit has null `parent_id`; other nonnull
parents resolve at a strictly coarser available catchment level. A child polygon
must lie within its declared parent, and sibling polygon interiors must not overlap,
within explicitly documented numerical geometry tolerances. A producer declares
the tolerance values, units and comparison method and reports actual validation
coverage. This contract does not require exhaustive worldwide polygon topology
certification; full reference and source-fidelity verification is a separate duty.
Tolerances account for numerical representation, not arbitrary source discrepancies. A violation beyond
them is nonconforming; recording an anomaly does not waive the invariant. Investigate
such originals and obtain an explicit contract decision before production rather
than silently repairing geometry or relaxing containment. Record validation
coverage separately: sampled checks do not establish worldwide conformance.
Components may have multiple or no represented outlets, including coastal and
inland sink polygon-only units. Outlet coordinates are either both null or both
present. Supply them only for a single source-described outlet; never choose an
arbitrary representative from multiple outlets or invent a point. Source river
nodes and associations retain multiple outlet facts independently.

`catchment_connectivity` distinguishes supplied edges from absent information.
For a `not_supplied` level, every graph row has an empty upstream list; that is not
an assertion of natural termination. The topology declaration applies only to
supplied levels. Even there, missing links alone do not classify a terminal.
Preserve source explanations and distinguish subset cuts. Additional typed source
attributes and nulls remain intact. Preserve native local polygon area separately
from geodesic `area_km2`; partitioned drainage area, mainstem-following area and
upstream polygon-union area are different quantities. Do not relabel one as another.
Document upstream-area semantics, derivations and anomalies; use null rather than
an unsupported value.

### Batch construction

Rows retain documented source order. For existing normalized Parquet conversion,
the producer reads with PyArrow 25.0.1
`ParquetFile.iter_batches(batch_size=4096)`. Original-source producers instead
document their typed incoming Arrow grouping; Parquet staging is not required.
Each incoming group is split separately.
Starting at its first remaining row, emit the largest prefix with
`RecordBatch.nbytes <= 8388608`. Repeat through the group. A first row exceeding
the budget forms a singleton batch. A batch ends at its incoming-group boundary even
when budget remains.

`nbytes` is evaluated on the source Arrow slice before serialization. It counts
logical values, offsets and validity bytes using PyArrow's accounting for sliced
arrays. IPC decoding may change validity-buffer representation. The budget applies
to source slices. A verifier checks the source slice and the next-row extension.
Allocation size, footer size and compressed size are separate quantities.
Geometry bytes remain intact. IPC buffers use Zstandard compression with the
PyArrow default codec level. Consumers accept singleton batches larger than the
budget and process all rows addressed by a valid lookup.

## Graphs

Catchment `graph.parquet` has required non-nullable fields `id: int64`,
`level: int16`, `upstream_ids: list<int64>` (nonnull elements), and `bbox_minx`,
`bbox_miny`, `bbox_maxx`, `bbox_maxy`, each `float32`. Each catchment has exactly
one row with matching level and outward-covering geometry bounds. When float32
rounding would shrink bounds, round the affected bound outward. Reused source
Parquet artifacts keep their bytes, row groups, extra fields and metadata.

The river graph has the same fields, one row per river. An upstream ID denotes
an edge from that river to the row's river, at the same level. IDs resolve within
the corresponding feature table; lists contain no nulls, duplicates or self-links.
Graphs are acyclic. `tree` allows at most one downstream neighbor; `dag` allows
splits and reconvergence without duplicating features. Parent membership is not
flow. Validate complete source edges before declaring conformance; a cycle cannot
be excused by an anomaly note or removed silently. Acyclicity does not certify
hydrological continuity. Bounds make spatial selection possible without geometry
or source attributes; the ID lookup itself is not a spatial index.

## Rivers and source nodes

The optional root `rivers` declaration is:

```json
{
  "data": "rivers.arrow", "graph": "river-graph.parquet",
  "lookup": "river-lookup.arrow", "directory": "river-lookup-directory.json",
  "count": 25, "batch_bytes": 8388608, "index_batch_rows": 65536,
  "topology": "dag"
}
```

Paths are local artifacts with fingerprints. `count` is the positive exact row
count of data, graph and lookup. Omit an optional river/node declaration when no
rows exist; an empty file is not an alternative declaration. `topology` is `tree` or `dag`. Required river fields:

| Field | Arrow type | Nullable | Meaning |
| --- | --- | --- | --- |
| `id` | `int64` | No | Positive dataset-local river ID, unique across river levels |
| `level` | `int16` | No | Nonnegative river tier; smaller is coarser |
| `parent_id` | `int64` | Yes | Constituent membership in a river at a strictly coarser available tier |
| `source_namespace`, `source_id` | `string` | No | Source layer identity and ID rendering; retain native ID separately |
| `local_catchment_id` | `int64` | Yes | Associated local drainage unit, not the accumulated upstream basin |
| `component_catchment_id` | `int64` | Yes | Associated drainage unit representing the connected network component |
| `upstream_node_id`, `downstream_node_id` | `int64` | Yes | Source-directed endpoint references to node rows |
| `geometry_orientation` | `int8` | No | 0 unspecified, 1 upstream-first, 2 downstream-first |
| `bbox` | Catchment bbox struct | No | Outward-covering EPSG:4326 bounds |
| `geometry` | `binary` | No | LineString or MultiLineString WKB in EPSG:4326 |

Within each feature table, `(source_namespace, source_id)` is unique across all
levels; river, node and catchment tables have separate HFX ID domains. Namespaces
retain source layer identity, not a label inferred from coincident geometry.
River IDs are not row numbers or globally stable IDs across datasets/versions.
River and catchment tiers are independent. One-tier rivers need no invented
parents. Stream order is an attribute, not a tier or universal snapping weight.
Parent membership does not require equality with the union of child geometries.
Each nonnull catchment association resolves to a catchment ID; multiple rivers may
share either target. Sources need not supply components or polygons. Null means no
represented association, with absence versus unavailable evidence documented.
Never infer hydrological association solely from spatial intersection.

Geometry retains coordinate and part order. Do not silently reverse, simplify,
clip or repair it. Record necessary transformations, including source geometry
export and reprojection. Orientation 1/2 asserts first-to-last order relative to
flow; for MultiLineString it also asserts parts are in connected flow order with
each part consistently oriented. Otherwise use 0. Connectivity and directed node
references remain authoritative regardless of orientation; 0 is not a failure.

Optional `river_nodes` uses the river declaration's `data`, `lookup`, `directory`,
`count`, `batch_bytes`, `index_batch_rows` fields, with paths `river-nodes.arrow`,
`river-node-lookup.arrow`, `river-node-lookup-directory.json`. It has no graph or
topology field. Required node fields are nonnull `id: int64`, `level: int16`,
`source_namespace: string`, `source_id: string`, `bbox` of the catchment struct
type, and `geometry: binary` (Point WKB in EPSG:4326), plus nullable
`coarser_node_id: int64`. Node IDs are positive and unique across node tiers;
`level` is the nonnegative river tier. A coarser-node reference resolves at a strictly smaller
level and means source-declared correspondence, not constituent membership.
Keep source layers distinct even if coordinates and numeric source IDs match.

Nonnull river endpoint IDs resolve to nodes at that river's level. These references
are the canonical incidence relation: incoming rivers have that downstream node;
outgoing rivers have that upstream node. Preserve original incidence strings,
ordering-dependent width shares, cross-tier reference columns, diagnostics and
other typed attributes alongside it. Do not invent nodes for sources without them.
No node reference may be nonnull when the node artifact is absent. Verify that
source-supplied flow edges and endpoint incidence agree; sharing a node alone does
not imply every possible incoming/outgoing river pair is a source flow edge.

River/node attributes and WKB share compressed IPC batches. Apply the 8388608-byte
logical slice budget, oversized-singleton rule and Zstandard compression above to
typed incoming Arrow batches; their source need not be Parquet. Producers document
incoming grouping and deterministic row order separately. Lookup rows use the
same 65536-row layout and directory rules below, with `hfx:data_sha256` replacing
`hfx:catchments_sha256` and binding exactly the declared `data` artifact. All other
lookup/HTTP integrity rules apply unchanged.

## Typed meanings and source fidelity

HFX fixes structural fields, not a complete source attribute schema. Preserve
useful source attributes, physical types, nulls and meanings. Document retained,
renamed, transformed and omitted fields; a collision with an HFX structural name
requires an explicit source-column rename map in provenance, not value replacement.
Retain source field/schema metadata where applicable; update geometry metadata for
actual delivered CRS and bounds rather than carrying stale projected metadata.

The optional `categorical_columns` array binds a dictionary to one scalar column:

```json
{
  "artifact": "rivers.arrow", "column": "level", "physical_type": "int16",
  "codes": [{"code": 0, "meaning": "segment"}, {"code": 1, "meaning": "reach"}],
  "null_meaning": "not permitted"
}
```

`artifact` is an exact local artifact path, `column` a top-level field name.
`physical_type` is one of `string`, `bool`, `int8`, `int16`, `int32`, `int64`,
`uint8`, `uint16`, `uint32`, `uint64`, matching the Arrow field's logical scalar
type (dictionary encoding, if present, does not change this type). Codes are unique,
nonnull JSON values of that type; integer parsing must preserve full precision.
Every observed nonnull value has one nonempty string meaning. `null_meaning` is a
required nonempty description of null interpretation, even for nonnullable fields.
At most one dictionary binds each artifact/column pair. Dictionaries define dataset
semantics, not cross-dataset equivalence or Arrow compression. Level descriptions
supplement HFX ordering, never replace parents/edges. A source `termination_kind`
may use this mechanism; no universal outlet vocabulary is required. Preserve
underspecified source codes with an explicit uncertainty description.

Subsets retain external source edge identities in source columns and document
which edges were cut, in each direction; structural graph references still resolve
within the delivered subset. Never turn a known cut into a source terminal.

## Lookup and directory

`lookup.arrow` is an uncompressed Arrow IPC file with exactly three non-nullable
fields in this order: `id: int64`, `block: int32`, `row: int32`.
IDs are strictly ascending across the complete file. Each addressed feature appears once.
`block` is its zero-based addressed-data record-batch number; `row` is its zero-based
row within that batch. Every address is within bounds and resolves to the stated
ID. Every batch contains 65536 rows except the final batch, which contains the remaining rows. Schema metadata contains exactly
`hfx:format_version` with UTF-8 value `0.4.0` and `hfx:catchments_sha256` with the
ASCII lowercase full catchment SHA-256 digest.

The UTF-8 JSON directory has this shape:

```json
{"version": 1, "batches": [
  {"batch": 0, "min_id": 2, "max_id": 700, "rows": 3}
]}
```

There is exactly one entry per lookup batch, in batch order. Inclusive endpoints
are the batch's first and last ID. Ranges are disjoint and ascending. `rows` is
the batch row count. JSON integer parsing must retain signed 64-bit precision.
For each requested ID, binary-search these ranges, then binary-search the selected
lookup batch for an exact match. Return absent if either search finds no match.
Group matched addresses by block and read each requested data batch once.
Check that the selected row contains the requested ID. Caller ordering and duplicate
requests can be restored after selection.

## Artifact identity and range access

Each fingerprint has nonnegative integer `size_bytes` and lowercase hexadecimal SHA-256
strings `sha256`, `head_sha256`, `tail_sha256`. The first is the whole-file digest.
The latter two hash the first and last `min(65536, size_bytes)` bytes. Consumers
check sizes and bounded hashes before using the lookup and catchments, verify
the lookup's catchment digest binding, and verify the directory's full digest.
Bounded hashes detect mismatches within their checked regions. Complete integrity
uses full producer and upload verification, a trusted manifest and immutable
data artifacts. Consumers needing independent integrity assurance verify full digests.

Locate IPC batches through the file trailer: a little-endian 32-bit footer length
followed by the six bytes `ARROW1`. The footer supplies record-batch offsets and
lengths. Fetch schema and dictionary dependencies required by Arrow. The lookup
uses plain numeric arrays. Read the directory and IPC footer metadata at startup;
fetch numeric lookup batches and catchment batches only for requested IDs.

HTTP servers return `206 Partial Content` for requested byte ranges over the
stored bytes. Clients send `Accept-Encoding: identity`, verify `Content-Range`
and response length, and pin a strong ETag or immutable object version across
requests. ETags identify transport versions; the manifest supplies full SHA-256
identity. Reject changed identities, malformed ranges, out-of-bounds addresses
and mismatched fingerprints. Reading one bundle requires a consistent manifest
and artifact object set for the duration of access.

For a new bundle, publish verified artifacts at an unused versioned prefix,
verify uploaded identities, then publish the manifest. Keep data artifacts
immutable. Corrections to data artifacts use a new prefix and manifest with
fresh bindings.

The approved [GRIT raster extension](raster-data.md) may add new raster artifacts
and amend the existing in-development 0.4.0 root manifest and publication
documentation. It must not replace vector data or alter existing vector bindings,
declaration meanings or source provenance. Verify new artifacts before publishing
the amended manifest last. Preserve previous small-object bytes and identities
in receipts, and record replacement identities and cache handling. Prefer new,
separately bound publication notes over replacing a document bound by an old
manifest. Any document amendment must preserve valid reads of retained manifest
snapshots. Cached old manifests remain valid vector-only snapshots; new manifests declare a verified
complete bundle. Readers retain one consistent manifest snapshot and pin artifact
transport versions for each selected read. This exception does not authorize
changes to any 0.3.0 cloud object.

## External raster artifacts

Only raster auxiliaries may refer outside the bundle. In a raster declaration,
replace a local artifact path with `{"external": "raster-flow-dir"}` (or another
unique key). That key resolves in root `external_artifacts` to an object with
`url`, `size_bytes`, `sha256`, `head_sha256`, `tail_sha256`, and `retention`.
`url` is a direct absolute HTTPS data-object URL, not another manifest or a mutable
alias. Fingerprints have exactly the local artifact meanings. `retention` is a
nonempty concrete publisher commitment identifying who keeps that exact object
immutable and publicly available for the lifetime of this dependent bundle; it is
not an automatic runtime guarantee. External keys are not local artifact paths
and do not appear in `artifacts`.

Publishers verify the referenced full identity and provenance, retain the original
verification receipt, and check current public range reads before publishing a
new manifest. References may reuse unchanged verified objects without copying or
reprocessing them. All size, range, encoding, fingerprint and pinned strong
ETag/object-version checks still apply. Access retains one consistent root
manifest snapshot, including its external identities; it must not refresh another
bundle's manifest to resolve a reference. A missing or changed object is an error,
not permission to substitute data. Document this cross-prefix lifetime dependency.
Preserve existing publications and their valid manifest snapshots. A new river
bundle requires a new approved immutable prefix; the historical raster-amendment
exception above does not authorize replacing the earlier river/snap bundle.
