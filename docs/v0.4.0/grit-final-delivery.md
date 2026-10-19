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
[Pooling PR #46](https://github.com/pourpoint-tools/hfx/pull/46) was closed unmerged
as diagnostic evidence, not a delivered consumer optimization. No duplicate feature format,
required private cache or new traversal engine was added to hide these costs.

Measurements report HTTP body bytes, not wire bytes. Fresh readers are not cold
CDN caches; two repetitions are not confidence intervals. Reference validation is
outside measured acquisition but can affect process-lifetime RSS. Spatial results
are bbox candidates, not exact intersections. Relationship membership is not clipped
to spatial discovery seeds; consumers still own traversal and query workspace.
The shared `0.4.0` string does not make old IPC readers compatible with this layout.

## Starting point for a Pourpoint reader

The successful transport experiment used **fsspec 2026.9.0** with **aiohttp
3.14.5**, not a custom concurrent reader. These were isolated experiment
dependencies, not additions to HFX or requirements on Pourpoint.

1. Resolve requested IDs through the producer lookup, group locations by Parquet
   row group, and select only needed columns. The original probe already did this;
   it did not issue an independent feature fetch for every ID.
2. Collect exact byte ranges per immutable artifact. Our experiment replayed ranges
   recorded by that probe; it did **not** discover them inside a new end-to-end
   reader. Range planning and decoding still need integration in Pourpoint.
3. Use one asynchronous `fsspec.implementations.http.HTTPFileSystem` per artifact,
   with a fresh session, and its existing range scheduler. The tested asynchronous
   call was `await fs._cat_ranges(urls, starts=starts, ends=exclusive_ends,
   batch_size=10, max_gap=None, on_error="return")`. Input HTTP ranges had inclusive
   ends; the fsspec call used end + 1. `max_gap=None` disabled coalescing in this
   pinned implementation. `_cat_ranges` is a private, version-sensitive API: verify
   the installed API and supported integration before adopting it.
4. Pin requests with `If-Match` to the artifact ETag. Send
   `Accept-Encoding: identity`, disable redirects and automatic decompression, and
   use `aiohttp.ClientTimeout(total=30)` per request. A pre-body response callback
   required status 206, the exact ETag, Content-Range including total object size,
   and Content-Length; it rejected encoded or chunked responses. After reading,
   check length and content. Our per-range SHA256 expectations came from verified
   local files; they are **not** published per-range hashes available to consumers.
5. Preserve range/result correspondence, decode with native libraries, then restore
   requested ID order and duplicates. Validate missing IDs, nulls, types and exact
   WKB against independent cases. The replay checked bytes, not this integrated
   decode/result-assembly path. Close the HTTP session explicitly.

We first tested 128 fixed feature ranges (293,718 bytes), in separate processes:
concurrency 1 took **45.57 s**, 4 took **11.21 s**, and 10 took **4.84 s**. Each
made exactly 128 requests and passed all range hashes. Then, at concurrency 10,
we replayed all 3,374 artifact ranges from the first 4,096-ID catchment query:
389,988,733 bytes, all hashes passed, about **123.89 s** summed acquisition/hash
time. Lookup data took 9.98 s (358.8 MB); feature data took 112.88 s (20.91 MB,
3,025 requests). The manifest GET was excluded; opening/fingerprint reads and
lookup-directory reads were included. Groups ran sequentially, with a fresh
process per group and a different schedule from the original query.

**Use this as a transport starting point, not an end-to-end latency promise.**
Concurrency 10 is a tested experimental setting, not a format constant or proven
optimum. Cache/network conditions were uncontrolled. The replay knew ranges in
advance, retained each group's returned buffers, and excluded ID resolution,
decoding and result assembly. The lookup group peaked at roughly 396 MiB RSS;
concurrency alone does not bound total retained memory. Measure an integrated
reader before claiming the same speedup.

The installed aiohttp could retry a disconnected GET once; there was no manual or
HTTP-status retry. We counted headers-sent attempts and tested that behavior.
Successful public runs needed no extra attempts. With `on_error="return"`, fsspec
can finish scheduled work before errors are inspected: this is not fail-fast.
Completed-body bytes exclude unknown partial/socket traffic. Preserve these
accounting and failure distinctions when comparing readers.

Avoid assuming that merging ranges or enabling Arrow threads will solve the same
problem. For the measured feature ranges, merging gaps up to 256 KiB saved no
requests; allowing 4 MiB gaps saved 1,438 requests but added about 4.04 GB. Local
PyArrow prefetch tests through the existing Python file wrapper did not demonstrate
concurrent HTTP reads. Neither result rules out other native-library integrations.

The next Pourpoint experiment should integrate maintained asynchronous/native
transport with its reader, measure lookup, feature acquisition, decode and final
result time separately, and retain cold/first-use versus repeat-use distinctions.
Keep the same artifact identities and exact-result checks. Do not add a required
private cache or change the stored layout merely to reproduce this diagnostic.

References: [fsspec HTTP implementation](https://github.com/fsspec/filesystem_spec/blob/master/fsspec/implementations/http.py),
[fsspec Parquet range planning](https://github.com/fsspec/filesystem_spec/blob/master/fsspec/parquet.py),
and [PyArrow pre-buffer documentation](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.read_table.html).
The [compact receipt](receipts/grit-final-delivery.json) binds the public pilot and
full replay evidence; the measurements above are from this delivery, not the
libraries' general performance claims.

## Resource cleanup and handoff

The temporary server, attached volume and both primary IPs were verified absent on
2026-10-19 at 02:01:20 UTC. The estimated gross upper cost is **EUR 3.59**, within
the approved EUR 50 budget. This is an hourly-rate estimate through final absence
verification, not a provider invoice. Larger resize attempts were quota-rejected;
the original CCX33 remained in use. Compact VM evidence was preserved before teardown.

The [Pourpoint #36 handoff](https://github.com/pourpoint-tools/pourpoint/issues/36#issuecomment-6258085025)
links the delivered contract, manifest, verification evidence and limitations.
Readers must coordinate the actual stored contract, not infer compatibility from
the shared version string.
