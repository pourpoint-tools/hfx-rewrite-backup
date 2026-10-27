# TDX full-coverage private vector delivery

Published on 2026-10-27 at
`s3://pourpoint-hfx/tdx/hfx-0.4.0/NGA-TDX-Hydro-20230126-full62-20261027/manifest.json`
through authenticated endpoint `https://fsn1.your-objectstorage.com`.
Manifest SHA-256: `af831fec8d1469e304d21ff9271faead0035bb6f0ce8bf1e007c03c022a13991`.
The [compact receipt](receipts/tdx-full-delivery.json) binds artifact identities and
verification. Access remains private, with no permission changes.

This implements the [full-coverage vision](../../planning/visions/2026-10-22-tdx-hfx-0-4-0-private-vector-delivery.md).
The [historical 59-polygon delivery](tdx-handoff.md), its receipt and its private
prefix remain unchanged. That delivery completed [HFX #33](https://github.com/pourpoint-tools/hfx/issues/33);
this is a standalone follow-on.

## Stored contract and coverage

All **62 river and 62 polygon originals** from `NGA-TDX-Hydro-20230126` contribute
**15,940,505 rivers and 16,864,998 catchments**, with 15,769,946 supplied flow edges
and 16,864,998 local associations. The recovered polygon sources for `1020027430`,
`5020049720` and `6020006540` are included. Every basin has
`local_catchment_coverage: supplied`; no source is marked unavailable. Unmatched
rivers remain represented, and separate polygons sharing `streamID` retain plural
`local_catchment_ids` associations rather than being dissolved.

The [spatial GeoParquet contract](spatial-layout.md) is unchanged:
`format_version: "0.4.0"`, `representation: "spatial-geoparquet-adjacency"`,
`representation_version: 1`. It stores one authoritative feature file per domain,
artifact-bound ID lookups, conservative bounds and complete immediate relationships
in both directions. There are no rasters; catchment connectivity is `not_supplied`.
Use this bundle's IDs and artifact-bound lookups together, not addresses from a
previous publication.

Catchment `streamID` is int64, with exact widening of the int32 source declarations
in basins `1020018110` and `5020049720`. [Normalization guidance](tdx-normalization.md) describes this
approved mapping. Native values/nulls, exact embedded WKB, geometry order and
basin-qualified source identities remain intact, including 5,477 finite zero-length
rivers. Original areas remain separate from derived areas. No geometry repair,
coordinate clamp, inferred graph, outlet, node or upstream area was added.

Published `source-metadata.json` retains original declarations and domain coverage;
`original-inventory.json` pins production inputs. The `provenance/` artifacts retain
acquisition records, the cumulative 124-original archive inventory, archive verification,
and source license/attribution. CC BY-SA 4.0 and transformation notices accompany
the bundle. The permanent raw archive and prior publications are retained.

## Verification and limitations

Independent original-to-staging verification covered every supplied feature,
value/null, identity, exact geometry, flow edge and association. Full staging-to-spatial
verification then checked every final record, ID address, conservative bound and
immediate relationship in both directions. The receipt binds both checks to the
published manifest.

All **19 artifacts** passed full authenticated GET size/SHA-256 readback. The
manifest was published last and its exact bytes GET-verified. **14 selected consumer
probes** matched the verified local bundle: both-domain full/projected records,
known/absent IDs, spatial discovery, and flow/local relationship-to-record reads
in both directions. They explicitly cover all three recovered basins, including
supplied coverage and nonempty local associations. Selected probes are distinct
from the full uploaded-content checks; they establish neither a latency guarantee
nor Pourpoint reader compatibility.

Complete source coverage and exact WKB do not establish worldwide polygon-topology
validity. No global or cross-basin overlap screen was performed; earlier within-basin
screens covered only `7020000010` and `1020018110`. Spatial discovery returns bbox
candidates, not exact intersections. Source boundary truncation, missing upstream
area, coastal extensions and dateline cuts remain caveats. Orientation is unspecified;
missing downstream links do not establish natural terminals.

[Pourpoint #44](https://github.com/pourpoint-tools/pourpoint/issues/44) remains the
reader follow-up for plural associations and coverage semantics. Shared version
numbers do not establish compatibility. No map was produced, as requested.

## Resource cleanup

Final temporary-resource cleanup and cumulative cost reconciliation are pending.
