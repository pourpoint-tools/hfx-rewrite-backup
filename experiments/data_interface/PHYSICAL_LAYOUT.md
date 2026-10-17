# GRIT physical-layout investigation

**Recommendation for maintainer discussion:** favor spatially organized GeoParquet
as the feature-container direction, with one authoritative representation per domain,
projected attributes and exact WKB, compact ID/spatial access, and separately
addressable immediate relationships. River evidence supports this direction; an
all-domain production choice remains blocked by unmeasured GeoParquet catchment/node
behavior. The measured IPC catchment/node bundle is the evidence baseline, not an
adopted fallback. A permanent mixed-container contract has unquantified reader and
maintenance costs and is not selected by default.

The authorized switch to Hetzner after R2 transport failures enabled the completed
same-host HTTP comparison below. This is not production adoption or a claim about
R2-versus-Hetzner causes. Temporary-publication cleanup remains pending.
Related: [HFX #35](https://github.com/pourpoint-tools/hfx/issues/35).
The [previous findings](REPORT.md) remain historical evidence, not revised results.

## Method and reader changes

The first comparison keeps the original, 8,192-row and 256-row artifacts unchanged.
The corrected experimental reader discovers schema from the leading IPC message,
retains projected readers and one Arrow wrapper per file, and reuses spatial and
original Parquet graph readers. Original graph discovery groups selected row groups
for Parquet pre-buffering while streaming projected batches. Arrow's default lazy
cache policy does not establish concurrent HTTP reads.

Projection already skipped unrequested IPC buffers; this is not a new storage
capability. The 8,192-row candidate changes feature order and publishes batch bounds.
The 256-row variation tests smaller feature batches but has no relationships or
source-node domain. Their earlier build and global verification evidence remains
in the [historical report](REPORT.md); neither row cap is a production requirement.

[Local evidence](results/physical-layout-local.json) contains 48 trials and 96
first/reuse operations, with source identities, code hashes and raw receipt hashes.
All selected records match the original source semantically and as exact Arrow
streams. All 16 matched workload/buffer groups agree across layouts on selected IDs
and source streams. Transport phase sums match final counters; time sums match
reported totals. Selected equality does not replace full producer verification.

First results include opening, discovery, requested-value retrieval and geometry
decoding when WKB is returned. Imports and independent source validation are outside
timers. Reuse is a second operation on the same reader. Filesystem/OS cache is
uncontrolled; validation can warm source files before reuse. Trials are not
randomized or repeated enough for confidence intervals. Local bytes/calls count
serialized reads, not physical disk traffic or HTTP responses.

## Verified local trade-offs

Seconds below are **first / reuse**, including opening only on first use. These
trials use 65,536-byte IPC read-ahead per open buffered file. The medium square has
radius 0.1° around the existing source witness. Many-ID requests select 4,096 actual
source row ordinals, not assumed contiguous IDs. These are investigation settings.
Medium requests include source attributes and WKB; other rows here are attributes.

| Family / request | Selected rows | Original s | 8,192 s | 256 s |
| --- | ---: | ---: | ---: | ---: |
| Rivers / medium | 164 | 0.5897 / 0.3841 | 0.0208 / 0.0115 | 0.0969 / 0.0090 |
| Catchments / medium | 115 | 0.6252 / 0.4060 | 0.0460 / 0.0326 | 0.1073 / 0.0238 |
| Rivers / Amazon | 75,495 | 1.0948 / 0.7150 | 0.1652 / 0.1616 | 0.3767 / 0.2362 |
| Catchments / Amazon | 75,929 | 1.1837 / 0.7291 | 0.1809 / 0.1645 | 0.3929 / 0.2408 |
| Rivers / many clustered | 4,096 | 0.0169 / 0.0091 | 0.0169 / 0.0100 | 0.1472 / 0.0182 |
| Catchments / many clustered | 4,096 | 0.0204 / 0.0096 | 0.0248 / 0.0103 | 0.1148 / 0.0110 |
| Rivers / many scattered | 4,096 | 1.5461 / 0.3086 | 0.3915 / 0.2963 | 1.6163 / 0.3030 |
| Catchments / many scattered | 4,096 | 1.6297 / 0.2964 | 0.3543 / 0.3029 | 1.6965 / 0.2894 |

Both large original requests completed with exact source equality, unlike the
previous request-capped remote diagnostics. First serialized bytes for rivers /
catchments were 201.386 / 207.743 MB original, 30.151 / 38.382 MB for 8,192, and
108.639 / 115.189 MB for 256 (decimal MB). These are local observations, not remote
completion or throughput evidence.

Smaller batches trade first-use metadata for less materialization. Medium catchment
output is 3.625 MB logical, including 3.620 MB exact WKB. Fetch materialization is
24.618 MB original, 37.607 MB for 8,192 and 12.069 MB for 256. These totals include
projected attributes and offsets, not isolated WKB-overread bytes. The 256 variant
has slower first use here but faster reuse than 8,192.

Scattered requests expose the opposite cost: 8,192 materializes 17.58 million river
rows or 12.03 million catchment rows, versus about one million in original/256.
Its local first time is still lower in these trials. Materialized bytes and elapsed
time are not interchangeable goals; clustered requests already favor tight
original selection. No tested layout wins every path.

The source-boundary witness crosses selected feature blocks in every layout:
102 river IDs address 11 original / 2 candidate-8,192 / 4 candidate-256 blocks;
85 catchment IDs address 16 / 6 / 8. These are equality-checked lookup addresses,
not merely discovery envelopes touching multiple blocks.

Source nodes are a separate point domain, not river/catchment tiers. A
[source-node window](results/physical-layout-source-nodes.json) returns five
source-equal points / 105 exact WKB bytes with `id, level, bbox, coarser_node_id,
geometry`, including decode. Recorded original / candidate first results are
6.266 / 0.0196 s; these upload-concurrent local values are not speedup evidence.
Original discovery scans all 22,278,858 nodes; the candidate examines 81,920 bounds
rows. Original has no node graph-spatial index to use. Both first/reuse operations
match the independent node witness and exact original Arrow stream. This exposes
an access-path difference, not new point geometry, snapping or flow semantics.

## Buffering, exclusions and decode correction

Controlled small-river read-ahead from zero to 65,536 bytes reduces first serialized
calls from 94 to 66 original, 105 to 60 for 8,192 and 113 to 43 for 256. Bytes rise
from 70.537 to 70.968 MB, 13.159 to 14.291 MB and 22.806 to 23.836 MB respectively.
Read-ahead can fetch WKB gaps and retain serialized data between operations. This
is a local mechanism check, not proof of faster HTTP round trips.

Four trials are excluded from elapsed comparisons: all three catchment elongated
variants and original catchment source-boundary. An accidental duplicate command
had overlapping process lifetimes; exact timed-phase overlap is unknown. Its
exclusive-create failure did not overwrite a successful receipt. The compact data
retains raw timings with `elapsed_claim_eligible=false`; the table omits them.
Their correctness and serialized-byte evidence remains, but their elapsed values
must not support a layout claim.

`record_probe` decodes geometry whenever it returns WKB, records decode separately,
and includes it in result time. Earlier external summary prose saying decode was
disabled was wrong; raw receipts and numeric decode fields were correct. Medium
catchment first decode is about 1.844 / 1.746 / 1.640 ms for original / 8,192 / 256.
The evidence binds the separate erratum rather than rewriting prior receipts.

Read-ahead capacity is not total retained memory. Parquet pre-buffer spans, Arrow
outputs, query arrays and validation allocations are separate. Observed lifetime
RSS spans roughly 110–792 MB and includes validation; it is not query-only memory
or a read-ahead bound. No exact compressed-WKB overread ratio is inferred.

## Existing formats and verified GeoParquet control

[FlatGeobuf's HTTP reader](https://github.com/flatgeobuf/flatgeobuf/blob/d8b6d6afcfe25b7898ddd721be0cb85c3be276ea/src/ts/http-reader.ts)
already merges nearby index/feature ranges, deliberately reading gaps to avoid
round trips. Its native geometry/property representation does not itself preserve
exact delivered WKB or the full Arrow schema. A derived bbox/ID index would add
storage, verification and a join to authoritative records; that duplication has
not earned a global build here. This is not a format tournament.

[GeoParquet 1.1.0](https://geoparquet.org/releases/v1.1.0/) offers unchanged WKB
columns and bbox-child statistics. The focused river control copies all fields,
WKB and actual spatial candidate batch boundaries into one row group per batch.
It reuses existing IDs/relationships rather than changing graph semantics.
[PyArrow 25.0.1](https://github.com/apache/arrow/blob/apache-arrow-25.0.1/cpp/src/parquet/arrow/reader.cc)
already pre-buffers selected column chunks; default lazy coalescing is not proof
of concurrent HTTP reads. Page-index acceleration is not claimed.

The [GeoParquet evidence](results/physical-layout-geoparquet.json) binds source
manifest → verified candidate manifest/IPC artifact → separate derivative declaration
→ new Parquet artifact. Old lookup SHA bindings still name IPC, never Parquet;
the derivative separately binds its unchanged group/row mapping. Full verification
passed for **22,337,300 rows / 3,207 groups**, all original values, nulls, Arrow
schema and exact WKB. The added `geo` metadata is checked separately. This is more
than selected-query equality. The artifact is **8,988,705,207 bytes**, with a
**10,645,592-byte footer** and 47 leaf columns. It is a river control, not evidence
for catchment geometry behavior.

Producer / verifier elapsed time including complete fingerprints is **53.275 /
39.889 s**; lifetime peak RSS is **10.124 / 10.334 GB**. An unrelated upload ran
concurrently. These are nonisolated production/verification costs, not consumer
throughput comparisons or bounded-memory claims. Declaration, artifact, code and
immutable global receipt hashes are in the JSON; historical receipts stay unchanged.
The derivative declaration binds producer commit `c48736b498b815a0d05e460e038ba3c4d7541d82`;
useful-result/bulk readers bind `44f1346ce298ee241841c890a557750346c3f122`.

## GeoParquet local useful-result and bulk comparison

First result includes opening and requested geometry decode. Decimal MB and calls
below count local serialized reads, not HTTP or physical disk I/O. GP uses native
Parquet `pre_buffer=True`, `use_threads=False`; IPC uses 65,536-byte read-ahead.
No application selected-batch cache is added.

| River request | Rows | GP ms / MB / calls | IPC 8,192 ms / MB / calls |
| --- | ---: | ---: | ---: |
| Small, attributes + WKB | 7 | 71.2 / 18.626 / 30 | 20.3 / 14.291 / 60 |
| Medium, attributes + WKB | 164 | 64.2 / 18.626 / 30 | 20.8 / 15.405 / 62 |
| Elongated, attributes | 159 | 52.3 / 11.801 / 30 | 10.9 / 8.589 / 58 |
| Source boundary, attributes | 102 | 56.6 / 12.016 / 34 | 12.8 / 9.048 / 65 |
| Amazon, attributes | 75,495 | 85.9 / 16.772 / 119 | 165.2 / 30.151 / 203 |
| Clustered IDs, attributes | 4,096 | 59.0 / 12.592 / 62 | 16.9 / 5.495 / 68 |
| Scattered IDs, attributes | 4,096 | 1,212.5 / 523.758 / 5,018 | 391.5 / 664.382 / 5,364 |
| Absent IDs, attributes | 0 | 38.7 / 11.053 / 11 | — |

The 10.646 MB GP footer imposes first-use startup: fewer calls do not make small
local results faster. Large attribute selection benefits locally, while dispersed
known IDs do not show a universal win. All 16 GP operations passed independent
exact source equality; five windows also match source-only ID witnesses. GP returns
physical order and IPC sorted IDs, so cross-layout stream hashes can differ while
each matches its source. GP spatial acquisition retains group/row addresses;
IPC record fetch includes locator lookup. This is an as-used comparison, not pure
encoding attribution. Fresh processes and same-instance second reads do not prove
cold filesystem cache. Validation can warm source; unrelated upload was concurrent.

The complete projected river census returns ID, tier, bbox and source length,
without WKB or decode. Both repetitions count 22,337,300 rows, tier counts
1,767,065 / 20,570,235 and zero projected nulls, matching the independent source
census. The ID sum is diagnostic, not a multiset identity proof; full preservation
is verified separately.

| Layout | First / repeat s | First serialized MB | Lifetime RSS MB |
| --- | ---: | ---: | ---: |
| Original | 12.981 / 9.082 | 5,717.082 | 109.9 |
| IPC 8,192 | 2.460 / 0.560 | 780.982 | 133.4 |
| IPC 256 | 14.498 / 9.123 | 5,727.762 | 171.5 |
| GeoParquet | 1.731 / 0.936 | 488.783 | 882.0 |

These IPC census trials use 65,536-byte read-ahead; the control below separates
reader-policy overread. GP first totals include 0.037224 s opening plus 1.693892 s scan and
9,561 serialized reads. Two ordinary manifest reads add 99,094 bytes, included in
time but recorded separately from serialized counters. Compare cumulative first
transport: IPC's first scan counters already include opening. Native GP emits 341
batches at a 65,536-row cap, with maximum emitted Arrow buffer 2,236,416 bytes.
That buffer is **not** total live memory or native serialized prebuffer retention,
which is unmeasured. Streaming avoids application whole-table materialization;
it does not prove bounded process memory. Lifetime RSS includes imports and
validation. Lower local bytes/calls and elapsed time do not establish remote benefit.

The [complete catchment census](results/physical-layout-catchment-bulk.json)
projects ID, tier, bbox and `source_area`, not geometry. All three layouts return
22,419,857 rows, tier counts 82,557 / 1,767,065 / 20,570,235 and zero projected
nulls; logical projection is 762.275 MB. With 65,536-byte read-ahead, recorded
first / reuse seconds are 23.365 / 23.554 original, 1.380 / 0.941 for 8,192 and
23.445 / 23.608 for 256; first serialized transfer is 5,744.222 / 832.057 /
5,755.932 MB respectively. These are nonisolated upload-concurrent local scans,
not HTTP speedups. The river control below demonstrates why this buffer policy's
gap overread must not be attributed only to storage layout. Catchment zero-buffer
and GeoParquet bulk behavior were not measured here.

## Reader policy versus layout: projected river scan

The [zero-buffer control](results/physical-layout-river-buffering.json) repeats the
same projected census with no IPC read-ahead. All rows, tiers, projected nulls and
logical byte counts match the buffered scans; no geometry is requested or decoded.

| Layout | No read-ahead: first MB / calls | 65,536 bytes: first MB / calls |
| --- | ---: | ---: |
| Original | 711.097 / 665,531 | 5,717.082 / 87,210 |
| IPC 8,192 | 486.068 / 24,073 | 780.982 / 11,916 |
| IPC 256 | 730.542 / 654,487 | 5,727.762 / 87,173 |

Read-ahead removes calls but returns gaps, including possible skipped WKB bytes,
without decoding geometry. These totals do not isolate exact WKB overread. Do not
credit storage layout alone for the roughly 5.7 GB buffered original/256 transfer.
Batch count, compression and per-batch overhead remain layout differences. Upload
was concurrent and filesystem cache uncontrolled; local elapsed values in the JSON
are nonisolated, not cold-cache or HTTP-speed evidence. This control selects neither
an on-disk row cap nor an optimal network policy.

## Composed local access: flow and node incidence

[Six completed trials](results/physical-layout-sequences.json) cover conservative
bbox discovery → supplied-flow membership → every reached record plus WKB decode,
and directed node incidence → exact river records. All 12 first/reuse record
checks pass semantic and exact Arrow-stream equality against original source.
Flow seeds and complete membership match independent witnesses. River downstream
level-0 discovery finds 2 seeds and reaches 1,290 members; catchment upstream level-1
finds 3 and reaches 10. Respectively 1,288 / 7 reached IDs are not discovery seeds.
The 1,290 / 10 bounds-extending-outside counts mean bounds extend outside the
window, not geometries wholly outside it. Fetch is not clipped to discovery bounds.

Source node 2 has incoming rivers **[2, 3]** (`downstream_node_id == 2`) and outgoing
**[1]** (`upstream_node_id == 2`). Both layouts fetch all three exact records with
attributes and WKB. Node incidence does not infer a supplied-flow edge merely from
sharing a node. These are access compositions, not delineation or terminal rules.

| Sequence / layout | Recorded decoded first / reuse s | First / reuse local calls | First / reuse MB |
| --- | ---: | ---: | ---: |
| River flow / original | 2.842 / 0.193 | 173 / 136 | 677.669 / 15.657 |
| River flow / IPC 8,192 selective | 0.171 / 0.160 | 3,720 / 3,692 | 282.852 / 281.084 |
| River flow / IPC 8,192 batch-cache | 0.121 / 0.104 | 96 / 68 | 45.349 / 43.581 |
| Catchment flow / original | 1.427 / 0.139 | 69 / 32 | 661.019 / 8.207 |
| Catchment flow / IPC 8,192 selective | 0.032 / 0.014 | 56 / 28 | 13.669 / 11.207 |
| Node-2 incidence / original | 6.905 / 0.0006 | 87,173 / 5 | 5,717.328 / 1.311 |
| Node-2 incidence / IPC 8,192 | 0.020 / 0.0075 | 35 / 5 | 7.978 / 5.964 |

**Elapsed values are nonisolated observations, not speedup evidence:** approved
upload ran concurrently; filesystem cache is uncontrolled. The fixed 65,536-byte
policy can transfer skipped gaps. First includes opening/acquisition/preparation,
fetch and separately timed decode; reuse transport is a delta. Original supplied
adjacency preparation is charged inside first use. Original spatial discovery also
opens a separate graph reader: its duplicate footer work is counted, not a format
requirement.

The [existing query-owned `batch-cache` control](results/physical-layout-sequence-cache.json)
adds a seventh trial, with the same 2 seeds, 1,290 supplied-flow members and exact
source records in both phases. Within each traversal it retains three adjacency
batches / **504,492 Arrow buffer bytes**. It clears them before every query,
including reuse: adjacency is reread, not retained across queries. Traversal drops
from 3,636 reads / 238.289 MB to 12 / 0.786 MB per query. Record fetch is unchanged:
45 reads / 42.074 MB. This separates avoidable reader rereads from storage layout.
Use the existing query-owned reuse for this follow-flow path; no new cache framework
or producer closure is warranted by that overhead. Lifetime RSS is 318.964 MB,
including validation. Local observations do not establish a causal timing or
remote speedup, and Arrow cache bytes are not total process memory.

Original node incidence streams authoritative node-reference scalars of all
22,337,300 rivers once; candidate uses published immediate node adjacency. Both
retain only tiny incidence lists for reuse and fetch the three records again.
Their 24-byte numeric ID equivalent excludes Python list/int overhead. Reuse does
not erase original first acquisition cost or candidate's larger repeat transfer.

River flow outputs 1,290 records / 1,191,278 Arrow buffer bytes; catchment flow
10 / 121,085 bytes. Original / candidate fetch materialization is 18.704 / 63.182 MB
for rivers and 10.227 / 16.420 MB for catchments, not pure WKB overread. Isolated
requested-WKB and logical-output bytes were not recorded; JSON leaves them null.
Original prepared adjacency retains 536.564 / 451.008 MB; selective candidate
retains no application adjacency after the query, not zero I/O/process buffers.
Flow lifetime RSS is 4.232 / 3.124 GB original versus 279 / 175 MB candidate,
including preparation, validation and allocator lifetime. These distinct memory
measures must not be summed or treated as query-only peaks. Local counters expose
read-policy concerns but establish neither HTTP request counts nor remote benefit.

## Original publication: corrected remote baseline

**Historical original-public baseline; not paired with the Hetzner trials below.**
[Remote evidence](results/physical-layout-remote-original.json) preserves eight
spatial workloads / 16 operations and five known-ID cases / 10 operations on the
unchanged public GRIT publication. Trials ran serially with uploads stopped.
Each starts a fresh process, then reuses the same reader. CDN/network cache state
is unknown; this is not a cold-cache or provider-general result.

First includes opening, discovery, requested-record retrieval and WKB decode when
requested; reuse excludes opening. Independent source validation, imports, hashing
and JSON are outside timers. Readers retain metadata/head-tail ranges, use
65,536-byte IPC read-ahead and grouped native Parquet pre-buffering, without an
application selected-batch cache. Lazy graph opening can occur in discovery;
constructor time is not all startup. Concurrent HTTP fetching is not established.

Small/medium spatial windows request ID, tier, bbox, source length/area and exact
WKB with decode; other rows request those attributes without geometry. Seconds,
requests and decimal MB are **first / reuse**; requests/body bytes include opening
once, not headers, TLS or provider costs.

| Family / window | Rows | First / reuse s | HTTP requests | HTTP MB |
| --- | ---: | ---: | ---: | ---: |
| rivers / small | 7 | 18.652 / 13.001 | 58 / 48 | 70.763 / 5.795 |
| rivers / medium | 164 | 30.827 / 25.041 | 88 / 78 | 75.586 / 10.618 |
| rivers / elongated | 159 | 31.027 / 24.953 | 91 / 81 | 73.987 / 9.019 |
| rivers / Amazon | 75,495 | 702.391 / 715.583 | 1,723 / 1,713 | 201.188 / 136.220 |
| catchments / small | 8 | 23.328 / 19.966 | 80 / 70 | 79.578 / 14.395 |
| catchments / medium | 115 | 39.851 / 34.176 | 119 / 109 | 89.265 / 24.082 |
| catchments / source boundary | 85 | 29.994 / 24.460 | 91 / 81 | 73.413 / 8.230 |
| catchments / Amazon | 75,929 | 749.974 / 743.634 | 1,787 / 1,777 | 207.520 / 142.337 |

All spatial operations match independent original-source records exactly and
local original witnesses on selected ID, count and projected Arrow-stream hash.
Local timings are not compared. Both large attribute selections now complete;
first record fetch alone takes 685.939 s for rivers and 726.991 s for catchments.
Reuse is not uniformly faster. Medium catchment reuse discovery still needs 50
requests / 1.210 MB, followed by 59 / 22.872 MB for records: retaining metadata
reduces transfer but does not remove every round trip. Its 115 output records
contain 3.620 MB WKB; fetch materializes 4,269 rows / 24.618 MB. This is projected
Arrow materialization, not isolated compressed-WKB overread. Conservative bbox
selection is not exact geometry intersection.

Known-ID requests below use `id, level, source_length` (rivers) or `source_area`
(catchments), with no spatial discovery, WKB or decode. Dispersed **128** is a
source-row subset, not the local 4,096 dispersed workload; no linear extrapolation.

| Family / known IDs | Rows | First / reuse s | HTTP requests | HTTP MB |
| --- | ---: | ---: | ---: | ---: |
| rivers / clustered 4,096 | 4,096 | 10.640 / 7.028 | 26 / 19 | 4.635 / 2.228 |
| rivers / dispersed 128, retry | 128 | 205.265 / 189.611 | 513 / 506 | 161.201 / 158.794 |
| rivers / absent max + 1 | 0 | 2.503 / 0.000045 | 7 / 0 | 2.407 / 0.000 |
| catchments / clustered 4,096 | 4,096 | 14.691 / 9.472 | 31 / 24 | 4.963 / 2.556 |
| catchments / absent max + 1 | 0 | 2.621 / 0.000064 | 7 / 0 | 2.407 / 0.000 |

Absent means one above each source maximum, not absence inside an indexed range.
The river dispersed retry materializes 32,532 rows / 0.586 MB for 128 outputs /
2,304 logical bytes, while fetch transfers 158.794 MB. Useful Arrow output and
lookup/read-ahead transfer are different measures. The initial river attempt
failed HTTP 500; only its explicit fresh-process retry supplies completed timing.
**Catchment dispersed 128 remains missing after HTTP 503.** Neither failed attempt
has a result receipt, equality check or useful-result elapsed claim; both failures
remain hash-bound outside Git. No retry is included for catchments.

Read-only audits report 331 original spatial/river checks and 33 added catchment
checks, with zero failures. Every successful operation asserts semantic and exact
projected-source stream equality; selected checks do not authenticate full global
artifacts. Measured scripts/workloads, raw receipts and execution hashes are bound
in the JSON at code `8b2fac6d928c493187a97928c06b4749b6f50f1f`. Imported reader/build
hashes observed at aggregation are not retroactive per-trial measurements.
Spatial lifetime RSS is 659–805 MB and known-ID RSS 101–146 MB, including validation;
native serialized cache retention is unmeasured, not a query-memory bound.
Single first/reuse pairs provide no confidence interval or layout recommendation.

## Reproduction and remaining decisions

Use the [current reproduction commands](REPRODUCE.md#current-workload-and-workflow-probes)
with the same columns, source witnesses and reader options across layouts. The
initial spatial reader commit is `528a58865f6992cf57af1771fbea13afff976519`; per-trial code,
wrapper, workload and receipt hashes are in the local JSON. Its audit binding
identifies the full immutable external aggregation; duplicated cumulative snapshots
and comparison tables are omitted from the committed projection. The current source-only
generator reproduces all old and added witness entries exactly, excluding intentional
extension timing/provenance fields. New generated-file hashes do not replace the
original workload hashes bound to measured receipts. Full request logs, datasets
and machine paths stay outside Git. Exact measured census/incidence drivers and
their tiny tests are [historical source archives](REPRODUCE.md#historical-census-and-incidence-drivers),
not maintained APIs. The archive binding records hashes and native checks;
GeoParquet producer/probe source remains pinned to its measured commit.

The same-host selective and composed HTTP trials below complete the bounded remote
comparison. They do not add complete remote projected censuses. Historical whole-file
relationship preparation and repeated-work results in [REPORT.md](REPORT.md) remain
valid for their original conditions, not a universal bulk crossover. Publication
cleanup remains pending. Keep #35 open and return these findings to maintainers and
Pourpoint #36; adoption requires a subsequent agreed production vision.

## Same-host signed HTTP comparison

[Compact evidence](results/physical-layout-hetzner.json) binds all **43 fresh-process
trials / 86 first-and-reuse operations** to their exact sources and raw receipts.
All selected results passed exact original-source checks. The experiment published
and fully read back **46 objects / about 83.5 GB** on private Hetzner object storage.
Original, candidate and river GeoParquet targets used the same host. Signed URL
preparation is outside useful-result timers for every layout; opening and required
metadata, discovery, record retrieval and requested WKB decode are inside. Reuse
is the second operation on the same reader. These are single pairs, not latency
distributions; fresh processes do not establish cold CDN or network caches.
Queue source hashes and current-file checks bind the measured code. Root execution
checked source hashes before/after each serial task, but the minimal execution JSON
does not retain those snapshots, stdout/stderr hashes or independent quiet-process
attestations. Do not infer those missing receipts from successful selected checks.
GP validates expected witness IDs in its pinned probe without emitting a selected-ID
hash; the evidence preserves that distinction.

Seconds below are first useful results. Small/medium windows include WKB and decode;
other spatial rows return projected attributes. IPC means the verified 8,192-row
configuration, not an adopted cap. GP means the river-only GeoParquet control.

| Family / request | Original s | IPC s | GP s |
| --- | ---: | ---: | ---: |
| Rivers / small | 11.808 | 9.568 | 5.553 |
| Rivers / medium | 16.007 | 9.210 | 4.944 |
| Rivers / elongated | 16.010 | 8.085 | 4.625 |
| Rivers / Amazon | 277.392 | 35.616 | 18.948 |
| Catchments / small | 14.144 | 9.599 | — |
| Catchments / medium | 22.499 | 11.502 | — |
| Catchments / source boundary | 17.623 | 10.597 | — |
| Catchments / Amazon | 312.100 | 47.467 | — |
| Rivers / clustered 4,096 attributes | 4.331 | 11.162 | 9.867 |
| Catchments / clustered 4,096 attributes | 6.196 | 16.650 | — |
| Rivers / dispersed 128 attributes | 111.290 | 115.437 | 83.224 |
| Catchments / dispersed 128 attributes | 110.869 | 111.886 | — |

GP source-boundary first result is 5.684 s, but this queue has no matched original
or IPC river boundary trial. Do not manufacture that comparison. Absent-ID checks
use source maximum + 1, not arbitrary interior absence. Exact reuse, request/body-byte,
phase and materialization measurements are retained in the JSON rather than repeated
in another table. Returned body bytes are not wire traffic. No provider-general
latency or causal R2-versus-Hetzner comparison follows from these runs.

The native GP path combines footer pruning, column pre-buffering and reuse of
selected group/row addresses; IPC record fetch also consults its locator. Its
first-spatial advantage is an **as-used reader/layout result**, not proof that
encoding alone caused it. GP still opens a 10.646 MB footer. Local small results
favored IPC, illustrating why local timing alone could not select the remote path.

The matched remote zero-to-65,536-byte read-ahead controls reduce small-river first
requests from 76 to 58 original and 96 to 52 IPC, while body bytes rise from
70.388 to 70.763 MB and 13.126 to 14.167 MB. First results improve from 13.599 to
11.808 s and 13.881 to 9.568 s respectively. This isolates a reader-policy benefit,
not a physical-layout change; single ordered trials still do not establish an optimum.

Composed spatial → supplied flow → exact records improves first results from
43.149 to 17.140 s for rivers with query-owned adjacency reuse and 23.465 to
8.647 s for catchments with selective adjacency access. These are **IPC workflows**, not measured GP compositions.
Candidate node-2 incidence completes in 4.815 s; there is no matched remote
original-node comparison. The source checks preserve connectivity beyond discovery
bounds, not clipping or a new traversal engine. No complete remote projected census
was added by this queue; remote bulk-throughput claims remain limited to the earlier
whole-file/repeated-work evidence.

## Recommended direction and exact remaining uncertainty

Spatial-first priority makes the river GP result a defensible direction despite
clustered-ID regressions. Recommend a spatially organized **single authoritative
feature representation per domain**, with co-located independently projected
attributes and exact WKB. Favor native GeoParquet rather than further custom feature
storage machinery. Keep compact producer-prepared ID and conservative spatial access,
and distinct immediate forward/reverse relationship structures; consumers traverse
and own query workspace. Bbox overlap is conservative, not exact intersection.
Flow, hierarchy, directed incidence, cross-tier correspondence and local/component
associations keep their supplied meanings, including unknown/not-supplied values.

Required reader behavior is actual column projection, retained metadata per reader,
grouped native Parquet reads, reuse of spatially discovered record addresses and
query-owned adjacency reuse. Tune read-ahead as a disclosed transfer/round-trip
trade-off, not a fixed 64 KiB contract. The local scan controls show substantial
skipped-gap transfer from that policy. Streaming output does not bound total RSS
or native pre-buffer retention. Optional bulk preparation can serve repeated work;
no universal selective-to-bulk crossover has been established.

The GP river artifact is 8.989 GB versus 9.348 GB IPC: it can replace the feature
artifact rather than accompany it. Production lookups/manifests must bind the
actual Parquet identity and address convention, not the trial locator's old IPC
hash. Preserve native types, nulls, schema metadata, exact delivered WKB, meanings
and provenance. Full candidate verification covers all three domains, lookup rows,
bounds and independently expanded immediate edges; GP global verification covers
22,337,300 river rows only. Selected HTTP equality is not full interior authentication.
Final production artifacts still require complete verification.

No substantial feature duplication has earned its storage, build and verification
cost: neither an original-order copy for clustered IDs, separate geometry, nor a
FlatGeobuf derivative is justified by these measurements. The incomplete 256-row
variation trades less materialization for startup/scan costs. Neither it nor 8,192,
Morton order or the measured GP group boundaries is an optimum or production constant.

**The exact all-domain blocker:** no GP catchment or node artifact was built,
measured or fully verified. River results cannot establish their useful-result,
bulk or memory behavior, especially polygon WKB overread. IPC catchments/nodes are
the verified evidence baseline, not a permanent mixed-container recommendation.
Maintaining two feature-container readers/addressing paths has not been justified
against a uniform GP design. GP relationship-to-record composition is also unmeasured;
carrying over relationship semantics does not establish its elapsed time.

These limits block an evidence-complete all-domain production selection, not this
qualified recommendation for maintainer discussion. No further format tournament
or automatic benchmark expansion is warranted. Maintainers must accept the
first-spatial versus clustered-ID trade-off and decide whether the narrowly stated
all-domain uncertainty warrants follow-up under a subsequent production vision.
No production contract, publication or Pourpoint runtime is changed here.
