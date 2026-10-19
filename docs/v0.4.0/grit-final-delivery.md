# GRIT final spatial delivery

The global GRIT bundle is published at
[manifest.json](https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0/manifest.json)
under the [spatial stored contract](spatial-layout.md). Manifest SHA-256:
`04bbfb50907feaf339808730f85c39ee2cbeaed2c6217e9d546cd445b3bc897f`.
The [compact receipt](receipts/grit-final-delivery.json) records artifact identities,
verification scopes, measurements and source receipt hashes.

This implements the [production vision](../../planning/visions/2026-10-18-grit-final-hfx-0-4-0-production.md)
for [#43](https://github.com/pourpoint-tools/hfx/issues/43). Publication, final identity checks and owned temporary-resource removal are verified.
This record does not itself close the effort or claim Pourpoint reader compatibility.

## What was verified

The producer compared every reordered feature against the pinned normalized input:
22,419,857 catchments, 22,337,300 rivers and 22,278,858 source nodes. Checks preserve
native types, nulls, metadata and exact normalized WKB, verify final-bound ID
locators and conservative bounds, and compare complete immediate relationships in
both directions. Original-source fidelity is inherited from the
[prior delivery](grit-river-delivery.md), not a new normalization or hydrological repair.

The local verifier manifest hash differs from the published manifest because final
paths were relocated under `vectors/2026-10-18-final/`; artifact hashes remain the
identity of the data. Publication staged files, checked complete uploaded readback,
and replaced the root manifest last. After cutover, 15 independent source-membership
queries and 15 native exact-reference queries passed against the canonical URL,
without a candidate-manifest override. Four decoded raster windows and range reads
passed; both existing raster URLs, identities and retention declarations are unchanged.
GRIT remains CC BY-NC 4.0.

Six explicitly identified superseded vector/index files were deleted and their
absence checked: `catchments.arrow`, `graph.parquet`, `lookup.arrow`,
`lookup-directory.json`, `aux/snap_reaches.parquet`, `aux/snap_segments.parquet`.
No broad prefix deletion was used. Retained D8 rasters and the separate
`grit/hfx-v0.4.0-rivers-2026-10-12/` bundle are outside that deletion scope.
Post-cleanup public checks passed for the canonical manifest, all 22 artifact
identities through HEAD/ranges, both retained raster HEADs and the separate river
bundle (70 requests, 2,070,311 body bytes). Decoded raster windows passed after
cutover before cleanup; they were not repeated by this identity-only check.

## Access evidence and limitations

The receipt summarizes 27 completed original-probe timing cases using the staged
candidate-manifest override; these are separate from the 15+15 canonical checks
after cutover. They cover projected/full
records, known/absent IDs, spatial discovery, immediate relationship-to-record
composition, large requests and bulk, with first/reuse access across all domains.
The original full-catchment bulk path was resource-blocked by prefetch behavior;
it has no passing original timing receipt. A separately reviewed bounded native
row-group validation read every full catchment record twice, compared exact values,
and passed all 6,706 groups/22,419,857 rows. Each pass transferred about 20.65 GB;
acquisition took 2,636/2,622 seconds. That is separate full-content proof, not a claim
that the original bulk path succeeded or that small returned batches bound RSS.

Latency is a material limitation. The frozen serial HTTP probe took about
20.4 minutes first use and 19.6 minutes reuse for 4,096 scattered projected catchment
IDs. Reuse fetched about 379.7 MB in 3,368 requests, including nearly the entire
358.8 MB lookup and 3,025 feature-group reads. A parallel exact-range replay acquired
and hashed the same recorded ranges in about 124 seconds; it did **not** execute
an end-to-end reader query. Neither number is a universal format latency bound.
[Pooling PR #46](https://github.com/pourpoint-tools/hfx/pull/46) remains an unmerged
diagnostic, not a delivered consumer optimization. No duplicate feature format,
required private cache or new traversal engine was added to hide these costs.

Measurements report HTTP body bytes, not wire bytes. Fresh readers are not cold
CDN caches; two repetitions are not confidence intervals. Reference validation is
outside measured acquisition but can affect process-lifetime RSS. Spatial results
are bbox candidates, not exact intersections. Relationship membership is not clipped
to spatial discovery seeds; consumers still own traversal and query workspace.
The shared `0.4.0` string does not make old IPC readers compatible with this layout.

## Resource cleanup and handoff

The temporary server, attached volume and both primary IPs were verified absent on
2026-10-19 at 02:01:20 UTC. The estimated gross upper cost is **EUR 3.59**, within
the approved EUR 50 budget. This is an hourly-rate estimate through final absence
verification, not a provider invoice. Larger resize attempts were quota-rejected;
the original CCX33 remained in use. Compact VM evidence was preserved before teardown.

The Pourpoint #36 contract/evidence handoff and #43 completion reconciliation remain
pending. Readers must coordinate the actual stored contract, not infer compatibility
from the shared version string.
