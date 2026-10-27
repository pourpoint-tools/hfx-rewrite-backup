# Bundle organization and discovery

A bundle contains one UTF-8 `manifest.json` and the artifacts it identifies.
Read the root manifest rather than guessing filenames or consulting a source
manifest for runtime addresses. Select the current representation using all three
values:

```json
{
  "format_version": "0.4.0",
  "representation": "spatial-geoparquet-adjacency",
  "representation_version": 1
}
```

The format string alone does not establish compatibility with earlier IPC feature
publications. Current features use GeoParquet; lookup and immediate relationship
files use Arrow IPC. The manifest discovers each independently.

Local paths are relative POSIX paths within the bundle root and must not escape
it. Only explicit external raster references may name remote objects. Each local
path names one immutable data or provenance file. Readers accept additional
manifest fields and validate fields they use.

## Manifest fields

| Field | Meaning |
| --- | --- |
| `format_version`, `representation`, `representation_version` | Exact selector above |
| `fabric_name` | Lowercase ASCII source-fabric name |
| `fabric_version` | Optional source-fabric version string |
| `crs` | `"EPSG:4326"` for vectors; raster CRS is declared separately |
| `has_up_area` | Boolean; computed upstream areas available when true, with per-row nulls permitted; all null when false |
| `topology` | `"tree"` or `"dag"` for supplied same-level catchment connectivity |
| `bbox` | Four finite numbers `[west, south, east, north]` covering the units |
| `unit_count` | Positive catchment count |
| `created_at`, `adapter_version` | Source normalization RFC 3339 timestamp and adapter version |
| `region` | Optional source subset string |
| `families` | Feature domain declarations, below |
| `relationships` | Immediate relationship declarations, below |
| `catchment_connectivity` | One `{ "level": integer, "status": "supplied" or "not_supplied" }` per catchment level |
| `categorical_columns` | Optional [typed column dictionaries](vector-data.md#typed-meanings-and-source-fidelity) |
| `auxiliary` | Array of optional [D8 pairs](raster-data.md); may be empty |
| `external_artifacts` | Optional external raster identities |
| `artifacts` | Fingerprints of every local delivered artifact except the root manifest |
| `source_manifest` | Path `source-manifest.json` to preserved normalized input bytes |
| `addressing` | `block`: `zero-based Parquet row group`; `row`: `zero-based row within group` |
| `input_manifest_sha256` | Full SHA-256 binding the preserved `source-manifest.json` bytes |
| `source_domain_metadata` | Preserved nonphysical river/node declarations, including supplied river topology |

`families` maps represented `catchments`, `rivers`, and `river_nodes` to separate
ID domains. Each declaration supplies `data`, `data_sha256`, `count`, `lookup`,
and `directory`. Counts are exact positive feature and lookup row counts. Omit
unsupplied optional domains, including associated feature, lookup and relationship
declarations; empty feature files are not an alternative. Nodes require rivers.

`relationships` maps represented domains to IPC `data`, ID-range `directory`,
`columns` provenance and `feature_artifacts` bindings. Optional relationship columns
are discovered from these declarations; absent evidence is not an empty supplied
relationship. See [storage and access](spatial-layout.md).

## Provenance and attribution

Preserve source identities, typed attributes, metadata, normalization provenance,
original inventory, licensing and attribution. `source-manifest.json` retains
exact verified normalized input bytes; it is provenance, not current feature
addressing. `NOTICE`, `CITATION.txt` and dataset publication notes carry applicable
licenses, transformations and caveats. GRIT data remains CC BY-NC 4.0, separate
from this repository's MIT code license. A new physical layout does not certify
source hydrology. Source and derived quantities retain their distinct meanings.

## Artifact identity and range access

Each fingerprint has nonnegative integer `size_bytes` and lowercase hexadecimal SHA-256
strings `sha256`, `head_sha256`, `tail_sha256`. The first is the whole-file digest.
The latter two hash the first and last `min(65536, size_bytes)` bytes. Consumers
check sizes and bounded hashes before using lookup and feature artifacts, verify
the lookup's `hfx:data_sha256` binding, and verify the directory's full digest.
Bounded hashes detect mismatches within their checked regions. Complete integrity
uses full producer and upload verification, a trusted manifest and immutable
data artifacts. Consumers needing independent integrity assurance verify full digests.

Locate IPC batches through the file trailer: a little-endian 32-bit footer length
followed by the six bytes `ARROW1`. The footer supplies record-batch offsets and
lengths. Fetch schema and dictionary dependencies required by Arrow. The lookup
uses plain numeric arrays. Read the directory and IPC footer metadata at startup;
fetch numeric lookup batches only for requested IDs. Feature addresses refer to
Parquet row groups, whose boundaries come from Parquet metadata, not the IPC footer.

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
Preserve existing publications and their valid manifest snapshots. 