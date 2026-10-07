# HFX 0.4.0 Vector Data

## Bundle and manifest

A bundle contains one UTF-8 `manifest.json` and the artifacts it identifies.
Artifact paths are relative POSIX paths within the bundle root. Each path names
one immutable file. The manifest has these fields:

| Field | Type and meaning |
| --- | --- |
| `format_version` | String `"0.4.0"` |
| `fabric_name` | Lowercase ASCII source-fabric name |
| `fabric_version` | Optional source-fabric version string |
| `crs` | String `"EPSG:4326"` |
| `has_up_area` | Boolean; computed upstream areas are available when true, with per-row nulls permitted; all values are null when false |
| `topology` | `"tree"` or `"dag"`, describing same-level connectivity |
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
| `auxiliary` | Array of snap declarations described below; an empty array is permitted |
| `source_manifest` | `"source-manifest.json"`, original source manifest bytes |
| `artifacts` | Object mapping every delivered file except `manifest.json` to its fingerprint |

Source identity, provenance, attribution, additional source fields and applicable
metadata are preserved. `source-manifest.json` and `source-README.md` are source
provenance. Artifact discovery uses the root manifest. Its auxiliary declarations
cover the delivered vector files. `NOTICE`, `CITATION.txt` and `README.md` carry
applicable licensing, attribution, transformation notes and dataset caveats.
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
| `outlet_lon` | `float64` | No | Finite EPSG:4326 outlet longitude |
| `outlet_lat` | `float64` | No | Finite EPSG:4326 outlet latitude |
| `bbox` | `struct<xmin: float32!, ymin: float32!, xmax: float32!, ymax: float32!>` | No | Finite ordered EPSG:4326 geometry bounds; `!` denotes non-nullable leaves |
| `geometry` | `binary` | No | Exact Polygon or MultiPolygon WKB in EPSG:4326 |

Additional source columns, field order, field types, nullability, field metadata
and schema metadata are preserved. Optional `source_id: string` and
`level_label: string` retain source identity and tier labels. Source `geo` metadata,
including CRS and bbox covering paths, remains source geometry metadata in IPC.
Each coarsest unit has null `parent_id`; following parents reaches a coarsest unit.
Source hydrologic semantics include parent nesting, disjoint sibling interiors
and one outlet per unit. Their source validation status and geometric tolerances
carry forward. DAG upstream-area semantics and source anomalies are recorded
in the bundle documentation.

### Batch construction

Rows retain source order. The producer reads Parquet rows with PyArrow 25.0.1
`ParquetFile.iter_batches(batch_size=4096)`. Each incoming group is split separately.
Starting at its first remaining row, emit the largest prefix with
`RecordBatch.nbytes <= 8388608`. Repeat through the group. A first row exceeding
the budget forms a singleton batch. The final group may contain fewer than 4096
rows. A batch ends at its incoming-group boundary even when budget remains.

`nbytes` is evaluated on the source Arrow slice before serialization. It counts
logical values, offsets and validity bytes using PyArrow's accounting for sliced
arrays. IPC decoding may change validity-buffer representation. The budget applies
to source slices. A verifier checks the source slice and the next-row extension.
Allocation size, footer size and compressed size are separate quantities.
Geometry bytes remain intact. IPC buffers use Zstandard compression with the
PyArrow default codec level. Consumers accept singleton batches larger than the
budget and process all rows addressed by a valid lookup.

## Graph and snap artifacts

`graph.parquet` preserves the source Parquet bytes and same-level upstream graph.
Required non-nullable fields are `id: int64`, `level: int16`,
`upstream_ids: list<int64>`, and `bbox_minx`, `bbox_miny`, `bbox_maxx`,
`bbox_maxy`, each `float32`. Each catchment has one graph row with matching level.
Upstream IDs reference units at that level. Graphs are acyclic; a tree unit has
at most one downstream neighbor. A DAG can contain distributaries. Parent links
carry cross-level relationships. Source row order, row groups, statistics,
additional fields and metadata are preserved.

Each snap declaration contains `schema: "hfx.aux.snap.v2"`,
`artifacts: {"snap": "<relative path>"}`, and `metadata` with:

- `name`: unique kebab-case name;
- `description`: description string;
- `references_levels`: nonempty array of nonnegative referenced levels;
- `weight_semantics`: description of weight interpretation.

Snap Parquet bytes are preserved. Required fields are non-nullable `id: int64`,
`unit_id: int64`, `weight: float32`, and `geometry: binary` containing EPSG:4326
Point or LineString WKB. Snap IDs are positive and unique. Unit references resolve
to catchments at the declared levels. Weights are finite and nonnegative.
Optional nullable `stem_role: string` has values `mainstem`, `tributary`,
`distributary` or `unknown`. Optional nullable `bbox` has the catchment bbox
struct type and non-nullable leaves. Present bbox columns retain GeoParquet 1.1
covering metadata and leaf statistics. The default snap preference within a
search radius is descending weight, then mainstem, then increasing distance,
then ascending snap ID. The full unchanged graph and snap contracts are pinned
in [HFX 0.3.0](https://github.com/CooperBigFoot/hfx/blob/c18a8a6a115e2045080d8752279d39db2b9b29b6/spec/HFX_SPEC.md)
and [snap v2](https://github.com/CooperBigFoot/hfx/blob/c18a8a6a115e2045080d8752279d39db2b9b29b6/spec/aux/snap/v2.md).

## Lookup and directory

`lookup.arrow` is an uncompressed Arrow IPC file with exactly three non-nullable
fields in this order: `id: int64`, `block: int32`, `row: int32`.
IDs are strictly ascending across the complete file. Each catchment appears once.
`block` is its zero-based catchment record-batch number; `row` is its zero-based
row within that batch. Every address is within bounds and resolves to the stated
ID. Every batch contains 65536 rows except the final batch, which contains the remaining rows. Schema metadata contains exactly
`hfx:format_version` with UTF-8 value `0.4.0` and `hfx:catchments_sha256` with the
ASCII lowercase full catchment SHA-256 digest.

The UTF-8 JSON directory has this shape:

```json
{"version": 1, "batches": [
  {"batch": 0, "min_id": 2, "max_id": 90, "rows": 2},
  {"batch": 1, "min_id": 700, "max_id": 700, "rows": 1}
]}
```

There is exactly one entry per lookup batch, in batch order. Inclusive endpoints
are the batch's first and last ID. Ranges are disjoint and ascending. `rows` is
the batch row count. JSON integer parsing must retain signed 64-bit precision.
For each requested ID, binary-search these ranges, then binary-search the selected
lookup batch for an exact match. Return absent if either search finds no match.
Group matched addresses by block and read each requested catchment batch once.
Check that the selected row contains the requested ID. Caller ordering and duplicate
requests can be restored after selection.

## Artifact identity and range access

Each fingerprint has integer `size_bytes` and lowercase hexadecimal SHA-256
strings `sha256`, `head_sha256`, `tail_sha256`. The first is the whole-file digest.
The latter two hash the first and last `min(65536, size_bytes)` bytes. Consumers
check sizes and bounded hashes before using the lookup and catchments, verify
the lookup's catchment digest binding, and verify the directory's full digest.
Bounded hashes detect mismatches within their checked regions. Complete integrity
uses full producer and upload verification, a trusted manifest and immutable
publication. Consumers needing independent integrity assurance verify full digests.

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

Publish verified artifacts at an unused versioned prefix, verify uploaded
identities, then publish the manifest. Keep published objects immutable.
Corrections use a new prefix and manifest with fresh artifact bindings.
