# TDX private vector delivery

Published on 2026-10-26 at
`s3://pourpoint-hfx/tdx/hfx-0.4.0/NGA-TDX-Hydro-20230126-20261026/manifest.json`
using the authenticated endpoint `https://fsn1.your-objectstorage.com`.
Manifest SHA-256: `c8923c52c66f6aa285a31621a8a4eda80bd41817d8f462d0adce52359d7d81f2`.
The [compact receipt](receipts/tdx-delivery.json) records identities and verification.
Access remains private; no anonymous access or permission change was introduced.

This is the [spatial GeoParquet contract](spatial-layout.md), with
`format_version: "0.4.0"`, `representation: "spatial-geoparquet-adjacency"`, and
`representation_version: 1`: one authoritative feature file per domain, artifact-bound
ID lookups, conservative bounds and immediate relationships in both directions.
There are no rasters or inferred catchment graph; catchment connectivity is `not_supplied`.
See the [delivery vision](../../planning/visions/2026-10-22-tdx-hfx-0-4-0-private-vector-delivery.md)
and [HFX #33](https://github.com/pourpoint-tools/hfx/issues/33).

## Coverage and source fidelity

Release `NGA-TDX-Hydro-20230126` contributes all 62 river originals and 59 polygon
originals: **15,940,505 rivers and 13,890,015 catchments**. Polygon sources are
unavailable for **`1020027430`, `5020049720`, and `6020006540`**. Their rivers and
supplied flow connectivity remain represented; this is not complete worldwide
catchment coverage.

River `local_catchment_coverage` is `supplied` or `unavailable`. For unavailable
coverage, empty `local_catchment_ids` means unknown associations, not naturally
polygonless rivers. Unmatched rivers in supplied polygon sources remain distinct.
Plural associations preserve separate polygons sharing a `streamID`.

Catchment `streamID` is consistently **int64**, widening basin `1020018110`'s
int32 declaration exactly. `source-metadata.json` retains original declarations
and supplied/unavailable coverage; `original-inventory.json` pins acquired hashes.
[Normalization](tdx-normalization.md) documents this approved mapping. Native values,
nulls, exact embedded WKB, geometry order and basin-qualified source identities
remain intact, including 5,477 finite zero-length rivers. No geometry repair,
dissolve, coordinate clamp or connectivity inference was applied. Original area
attributes remain separate from derived normalized areas.

Source boundary truncation, missing upstream area, coastal extensions and dateline
cuts remain source caveats. Orientation is unspecified; missing downstream links
do not establish natural terminals. CC BY-SA 4.0 attribution and transformation
notices accompany the bundle. Private access is a maintainer requirement, not a
claim that the license prohibits redistribution.

## Verification and limits

The independent original-to-staging verifier checked every supplied feature,
native value/null, identity, exact WKB, supplied flow edge and available local
association. The full staging-to-spatial verifier then checked every final record,
ID address, conservative bound and complete immediate relationship in both directions:
15,769,946 flow edges and 13,890,015 local associations. The receipt binds both
verification steps to the published manifest.

All 16 uploaded artifacts passed full authenticated GET size/SHA-256 readback.
The manifest was uploaded last and its exact bytes GET-verified. Ten selected
authenticated consumer probes matched the verified local bundle: full/projected
records and known/absent IDs in both domains, spatial discovery, and flow/local
relationship-to-record reads in both directions. These selected probes are not
full content verification; the separate full readback supplies that proof.
Spatial discovery returns bbox candidates, not exact intersections. No latency
or fixed-memory guarantee is claimed.

Full WKB fidelity is not worldwide topology certification. Earlier complete
within-basin overlap screens covered only `7020000010` and `1020018110`; global
or cross-basin polygon overlap was not checked. The old 0.3.0 publication was not
a normalization input. It and the permanent raw archive remain retained.

## Consumer coordination and cleanup

[Pourpoint #44](https://github.com/pourpoint-tools/pourpoint/issues/44) tracks reader
support for plural local associations and unavailable-coverage semantics. Shared
version numbers and the HFX access probes do **not** establish Pourpoint reader
compatibility.

The temporary server, attached volume and owned IPs were verified absent on
2026-10-26 at 11:18:12 UTC. The estimated cumulative temporary cost is **EUR 21.00**,
including the prior run and rounding reserve. A conservative **CHF 28.10** reservation
uses 1.10 CHF/EUR plus CHF 5 contingency, within the current CHF 50 ceiling. These
are planning estimates, not a provider invoice or live exchange quote; ongoing object storage is
excluded and retained. Compact verification and cleanup evidence is preserved.
This handoff does not itself close HFX #33.
