# Spatial GeoParquet layout for GRIT 0.4.0

This is the revised stored contract for [HFX #43](https://github.com/pourpoint-tools/hfx/issues/43)
and its [production vision](../../planning/visions/2026-10-18-grit-final-hfx-0-4-0-production.md).
The [global delivery record](grit-final-delivery.md) reports production, public
verification, cutover and resource cleanup, with limitations explicitly tracked.
The old [vector contract](vector-data.md) supplies field meanings, not the physical
layout below. The shared `0.4.0` string does not imply compatibility with IPC readers.
Pourpoint must select this representation explicitly before using its addresses.

## Discovery and identity

`manifest.json` has `format_version: "0.4.0"`,
`representation: "spatial-geoparquet-adjacency"`, and `representation_version: 1`.
`families` maps `catchments`, `rivers`, and `river_nodes` to independent ID domains.
Each declaration supplies `data`, `data_sha256`, `count`, `lookup` and `directory`.
`artifacts` gives full SHA-256, size and bounded head/tail fingerprints of every
local data, index and provenance artifact. Paths are bundle-relative. Full hashes
are production identities; bounded fingerprints are selective-access checks, not
proof that all bytes were verified. A manifest is published only after its files.

One GeoParquet file per domain is authoritative. Fields retain native Arrow types,
nulls, field/schema metadata, source identities, tiers and exact normalized WKB.
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

Native Parquet statistics on `bbox.xmin`, `bbox.ymin`, `bbox.xmax`, `bbox.ymax`
conservatively select candidate row groups. Use inclusive comparisons and outward
rounding when narrowing precision; missing statistics mean retain the group.
Then project per-record bounds and tier to refine candidates before fetching full
records. Bounds are not exact geometry intersections. No duplicate feature table
or mandatory private cache is part of the bundle.

## Immediate relationships

`relationships` maps each domain to an independent IPC `data` file and ID-range
`directory`. Each row contains `id` plus independently projectable nonnull
`list<int64>` columns. All IDs in the domain have a row, including empty lists.
Rows and each neighbor list are sorted. Relationships are immediate, not closures:

- `upstream_ids` / `downstream_ids`: supplied flow graph and its reverse;
- `parent_ids` / `child_ids`: tier hierarchy;
- `upstream_node_ids` / `outgoing_river_ids`, and `downstream_node_ids` /
  `incoming_river_ids`: directed incidence;
- `coarser_node_ids` / `finer_node_ids`: cross-tier node correspondence;
- `local_catchment_ids` / `local_river_ids`, and `component_catchment_ids` /
  `component_river_ids`: distinct drainage associations.

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
remains CC BY-NC 4.0. This conversion does not repair hydrology or renormalize WKB.

`auxiliary` and `external_artifacts` are copied unchanged, including raster URLs,
identities and retention commitments. The producer never opens, copies or rewrites
rasters. Public range and decoded-window verification is a separate delivery duty.

## Production commands and evidence

Run on approved temporary compute, not the maintainer laptop, with pinned verified
normalized inputs and a new disjoint output directory:

```bash
uv sync
uv run python -m hfx.spatial_bundle build SOURCE OUTPUT \
  --source-manifest-sha256 TRUSTED_SHA256 --report verification.json
uv run python -m hfx.spatial_bundle verify SOURCE OUTPUT \
  --source-manifest-sha256 TRUSTED_SHA256 --report recheck.json
```

The trusted normalized GRIT manifest digest in the prior
[delivery receipt](receipts/grit-river-delivery.json) is
`b9a38083131dcf1a4c7c4e73ebe9a97dff2a4b7ef91a8df53f8bc38cadfa48db`.
Never replace it with a freshly calculated untrusted digest just to accept input.
The complete original-fidelity receipt is inherited evidence; each new run hashes
all required normalized inputs and independently compares every final feature,
lookup and immediate relationship. Selected public reads do not replace this.
Reports are outside both bundles; failed artifacts remain for diagnosis.
The command prints per-domain build/verify elapsed time, process-lifetime peak RSS
and free-disk snapshots. Save stdout as a run log. Feature declarations and
verification receipts include source batch reads, decoded logical bytes and
decode amplification relative to one source scan.

Global numeric keys/addresses and relationship arrays consume memory. Sorted
native-value gathers may decompress source batches repeatedly. Monitor RSS, free
disk and elapsed time externally (for example `/usr/bin/time -v`, `df`, and process
monitoring); inspect gather counters on a meaningful-scale sample before the global
run. Row/byte targets do not bound process RSS. No latency threshold is specified.
Do not publish on a failed verification or assume small fixtures prove global
performance. Upload verification, manifest-last cutover, unchanged public raster
reads, explicit superseded-vector cleanup and temporary infrastructure removal
remain separate operational work under the vision.

### Selected public measurements

Use the narrow probe against each final domain, with the fully verified local
bundle as the reference. Examples (substitute actual known IDs and windows):

```bash
uv run python -m scripts.check_spatial_access PUBLIC_BUNDLE_URL \
  --domain catchments --bounds WEST SOUTH EAST NORTH --columns id level \
  --reference OUTPUT --report catchment-spatial.json
uv run python -m scripts.check_spatial_access PUBLIC_BUNDLE_URL \
  --domain rivers --ids KNOWN_ID ABSENT_ID --reference OUTPUT --report river-records.json
uv run python -m scripts.check_spatial_access PUBLIC_BUNDLE_URL \
  --domain rivers --ids KNOWN_ID --relationship local_catchment_ids \
  --reference OUTPUT --report river-catchments.json
uv run python -m scripts.check_spatial_access PUBLIC_BUNDLE_URL \
  --domain river_nodes --bulk --columns id --reference OUTPUT --report node-bulk.json
```

Omitting `--columns` requests full records. The default two repetitions measure
first use and reuse of retained readers. Repeat with source nodes, catchment
polygons, large ID lists and bulk projections/full rows as resources allow.
Reference equality checks exact native values against the verified local bundle;
it does not independently prove query membership. Check representative spatial
and relationship membership against source-only witnesses separately. Reference
validation is outside measured public acquisition and transport counters. HTTP
counts are response body bytes, not wire bytes; fresh readers are not cold CDN
caches. Process-lifetime RSS includes verification workspace. Full local artifact
verification and uploaded full hashes remain required independently of this probe.
