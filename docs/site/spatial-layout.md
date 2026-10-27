# Spatial storage and relationships

## Discovery and identity

`manifest.json` has `format_version: "0.4.0"`,
`representation: "spatial-geoparquet-adjacency"`, and `representation_version: 1`.
`families` maps represented `catchments`, `rivers`, and `river_nodes` to independent
ID domains. Omit unsupplied domains such as source nodes, including their feature,
lookup and relationship declarations; do not create dummy files or invent nodes.
Each declaration supplies `data`, `data_sha256`, `count`, `lookup` and `directory`.
`artifacts` gives full SHA-256, size and bounded head/tail fingerprints of every
local data, index and provenance artifact. Paths are bundle-relative. Full hashes
are production identities; bounded fingerprints are selective-access checks, not
proof that all bytes were verified. A manifest is published only after its files.

One GeoParquet file per domain is authoritative. Fields retain normalized Arrow types,
nulls, field/schema metadata, source identities, tiers and exact normalized WKB.
Native widths may change only under documented approved lossless source mappings
with original per-source declarations retained; TDX catchment `streamID` uses int64.
Only GeoParquet `geo` metadata is added. Coordinates are longitude/latitude WGS84
(GeoParquet's default CRS84). Attributes can be projected without geometry.
Current production orders by tier, 16-bit Morton key and ID. Row groups target
8192 rows and 8 MiB logical bytes, with oversized single rows allowed. These are
reversible producer settings, not reader requirements or memory/latency limits.
Readers must discover actual group boundaries from Parquet metadata.

## ID and spatial access

The uncompressed Arrow IPC lookup has nonnull `id: int64`, `block: int32`,
`row: int32`, sorted by unique positive ID. `block` is the zero-based Parquet row
group; `row` is its zero-based row position. Schema metadata `hfx:data_sha256`
binds addresses to the final Parquet bytes. The lookup directory's `batches` list
contains `batch`, `min_id`, `max_id`, and `rows`; bounds select candidate lookup
batches, not proof that an ID exists. Compare the actual ID before returning a row.
Addresses cannot be reused for another physical artifact, even with the same IDs.
The lookup fields occur in exactly that order. Schema metadata `hfx:data_sha256` contains the ASCII lowercase full feature
digest. Lookup batches contain 65536 rows except
the final remainder. The UTF-8 JSON directory has `version: 1` and exactly one
entry per batch in batch order. Inclusive `min_id` and `max_id` are its first
and last IDs; ranges are disjoint and ascending. Integer parsing must preserve
signed 64-bit precision. Every feature appears exactly once, every address is
within bounds, and each addressed row contains its stated ID. Binary-search the
ranges and then the selected lookup batch for an exact ID; no match means absent.
Group matched addresses by Parquet row group to avoid duplicate reads.

Native Parquet statistics on `bbox.xmin`, `bbox.ymin`, `bbox.xmax`, `bbox.ymax`
conservatively select candidate row groups. Use inclusive comparisons and outward
rounding when narrowing precision; missing statistics mean retain the group.
Then project per-record bounds and tier to refine candidates before fetching full
records. Bounds are not exact geometry intersections. No duplicate feature table
or mandatory private cache is part of the bundle.

## Immediate relationships

`relationships` maps each domain to an independent IPC `data` file and ID-range
`directory`. Each row contains nonnull `id: int64` plus independently projectable nonnull
`list<int64>` columns with nonnull elements. All IDs in the domain have a row, including empty lists.
Rows and each neighbor list are sorted. Relationships are immediate, not closures:

- `upstream_ids` / `downstream_ids`: supplied flow graph and its reverse;
- `parent_ids` / `child_ids`: tier hierarchy;
- `upstream_node_ids` / `outgoing_river_ids`, and `downstream_node_ids` /
  `incoming_river_ids`: directed incidence;
- `coarser_node_ids` / `finer_node_ids`: cross-tier node correspondence;
- `local_catchment_ids` / `local_river_ids`, and `component_catchment_ids` /
  `component_river_ids`: distinct drainage associations.

### Local drainage associations

For this representation, river `local_catchment_ids` and its exact reverse,
catchment `local_river_ids`, are authoritative. A river may have zero, one or
multiple represented local catchments; preserve every supplied association.
Keep feature identity separate from association keys: preserve native fields such
as TDX `streamID` independently, without merging distinct source features that
share an association key.

The river feature column `local_catchment_id` may be omitted. If present, it must
equal the sole associated catchment ID, or be null when there is no represented
association. It cannot represent multiple associations. If any river has multiple
local catchments, omit this scalar column from the domain's feature file rather
than choosing one catchment or writing a misleading null. See the [feature schemas](vector-data.md#rivers) for the other river fields.

Existing GRIT singleton associations and their consistent scalar feature columns
remain valid without changing published files or hashes. The physical relationship lists use the same schema for single and plural associations.

TDX river features additionally carry nonnull string `local_catchment_coverage`:
`supplied` means the basin's polygon source was available and associations were
exhaustively checked; `unavailable` means the polygon source was missing and local
associations are unknown. Both may have empty relationship lists; they are not the
same evidence. `processing_basin` connects each feature to the domain coverage and
original declarations in `source-metadata.json`. The manifest's `categorical_columns`
records the field meanings. This TDX extension does not require rewriting existing
GRIT publications. Pourpoint support requires explicit coordination; shared version
numbers and support for plural lists alone do not establish reader compatibility.

### Relationship provenance and access

Each `columns` entry records original source artifact/column, direction and domain
meaning. `feature_artifacts` binds involved domains to final feature paths/hashes.
Original graph files are provenance, not runtime feature addresses. Follow the
relationship's `target_domain`, then that domain's ID lookup to fetch records.
Shared node incidence does not imply a supplied flow edge. Empty lists do not
classify terminals or resolve unknown scalar relationships. Consult authoritative
feature nulls, `catchment_connectivity` and preserved source caveats. Consumers own
traversal and query workspace.

## Source and raster preservation

`source-manifest.json` retains exact verified normalized input manifest bytes;
`input_manifest_sha256` pins them. Original inventory, normalization provenance,
license and attribution remain discoverable through copied provenance and source
artifact identities. Category declarations point to final feature files. `source_domain_metadata` retains
nonphysical river/node declarations such as supplied river topology. GRIT
remains CC BY-NC 4.0. Storage conversion does not repair hydrology or renormalize WKB.

`auxiliary` and `external_artifacts` are copied unchanged, including raster URLs,
identities and retention commitments. Declared local D8 raster files are copied
byte-for-byte with unchanged artifact identities; missing files or identities and
mismatched bytes are rejected. Verification checks these references independently
of the converter's provenance inventory. External rasters are not fetched. Raster
conformance, public range and decoded-window verification remain separate duties.

