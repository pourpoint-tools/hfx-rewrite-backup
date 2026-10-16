# GRIT physical-layout investigation

**In progress. No layout or production contract is selected.** Remote corrected-
reader trials, the GeoParquet comparison and the final recommendation are pending.
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

## Reproduction and remaining decisions

Use the [current reproduction commands](REPRODUCE.md#current-workload-and-workflow-probes)
with the same columns, source witnesses and reader options across layouts. The
measured reader commit is `528a58865f6992cf57af1771fbea13afff976519`; per-trial code,
wrapper, workload and receipt hashes are in the local JSON. Its audit binding
identifies the full immutable external aggregation; duplicated cumulative snapshots
and comparison tables are omitted from the committed projection. The current source-only
generator reproduces all old and added witness entries exactly, excluding intentional
extension timing/provenance fields. New generated-file hashes do not replace the
original workload hashes bound to measured receipts. Full request logs, bulk data
and machine paths stay outside Git.

Remote behavior, a same-boundary GeoParquet comparison, useful relationship/record
sequences, corrected projected bulk costs and a final layout recommendation remain
unfinished. Local first-use gains do not settle them. Keep #35 open and return the
complete findings to maintainers and Pourpoint #36 before production adoption.
