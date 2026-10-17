# HFX data interface findings

Historical interface experiment. The later [physical-layout recommendation](PHYSICAL_LAYOUT.md)
adds same-host HTTP comparisons without replacing these receipts.

Global verification and 134 local runs passed. Actual remote work completed with
36 successful result processes and eight explicitly partial request-capped diagnostics.
The approved temporary publication was removed and the original public manifest
remained unchanged. This is completed experimental evidence, not format adoption.

Related: [HFX #35](https://github.com/pourpoint-tools/hfx/issues/35),
[Pourpoint #36](https://github.com/pourpoint-tools/pourpoint/issues/36), and the
[published vision](../../planning/visions/2026-10-16-hfx-data-interface-experiments-with-grit.md).

## Findings

1. **The current IPC files already support independent columns.** PyArrow 25.0.1
   `IpcReadOptions(included_fields=...)` skips unrequested compressed buffers.
   Earlier full-batch WKB scans were partly reader-induced. Physical separation
   of attributes and geometry is not required merely to avoid WKB reads.
2. **Small published spatial metadata and immediate reverse relationships help
   first use.** The candidate provides these without global consumer preparation.
   Traversal still executes in the consumer, including paths outside a spatial
   window. No full upstream/downstream closure is published.
3. **Neither tested row cap is ready for adoption.** The 8,192-row cap overreads
   WKB for some known IDs. A 256-row variation reduced that overread but increased
   catalogs/footer startup to about 80 ms/17.9 MB per domain and slowed global
   projected scans. Smaller blocks alone do not solve the trade-off.
4. **HTTP request count can outweigh byte savings.** Candidate small spatial and
   combined sequences improved, but projected known-ID access often regressed.
   Whole-file preparation amortized in the measured large repeated-work series,
   at the cost of global buffers and much greater transfer. Cache/network state
   was uncontrolled; neither a universal crossover nor a format winner follows.

## Candidate interface and physical layout

The [contract sketch](README.md) describes the candidate and experimental constants.
Each independent catchment, river and source-node domain retains every original
feature column, native type, null, field/schema metadata and exact delivered WKB.
Records sort by `(level, Morton(bounds center), id)`; IDs remain identities, not
physical positions. Sixteen-bit axes cover longitude/latitude. Morton sorting is
only a locality heuristic. Complete feature envelopes, not center points, define
published conservative batch bounds. Query discovery reads the small batch
catalog, then projects `id`, `level` and per-feature bounds in matching batches.
Bounding-box overlap is a candidate result, not exact intersection or containment.

Known IDs use ID-sorted `(id, block, row)` IPC lookup and a small ID-range directory.
Feature batches initially cap at 8,192 rows and 8 MiB logical Arrow bytes, with
oversized rows intact. Feature IPC uses Zstandard; relationship IPC is uncompressed.
Complete records remain in one columnar table, so fetching attributes then geometry
needs ID/address reuse rather than an independently maintained row join.

ID-sorted Arrow `list<int64>` relationships publish immediate neighbors in both
supplied flow directions, parent/children, directed node incidence, coarser/finer
node correspondence and separate local/component catchment associations. Those
relations keep separate names, tiers and target domains. Feature scalar references
and original graph lists remain authoritative; reverse lists are derived. Shared
nodes create no extra flow pairs. Component connectivity stays `not_supplied`;
empty adjacency does not certify a natural terminal.

The root experiment manifest binds exact input and derived artifact SHA-256
identities. Lookup schema and spatial declarations bind their addressed feature
file; relationship declarations identify authoritative source columns and both ID
domains. Original categorical bindings are remapped to candidate feature paths.
Copied source provenance/license documents and the pinned original manifest remain
bound. This is a portable Arrow representation, not a Python object snapshot.

## Inputs, scale and producer cost

Input: 22,419,857 catchments, 22,337,300 rivers and 22,278,858 source nodes. Original
vector/provenance artifacts total 36,981,583,471 bytes. Public manifest SHA-256:
`b9a38083131dcf1a4c7c4e73ebe9a97dff2a4b7ef91a8df53f8bc38cadfa48db`.
The [source revisions](results/source-revisions.json) bind the contract, delivery
receipt, Pourpoint runtime and archived downstream experiments used here.

| Global producer operation | Elapsed | Process lifetime peak RSS |
| --- | ---: | ---: |
| Candidate build, including source identity checks | 414.452 s | 15.164 GB |
| Complete source/derived verification | 431.640 s | 21.309 GB |

The first 2 GB DuckDB sort failed before emitting a catchment file. The successful
run used an 8 GB engine pool, one sort thread and disabled insertion-order
preservation; explicit total sorting determines output order. The engine setting
is not a process memory cap. An actual spill snapshot was 23.188 GB, not a precise
peak trace. The failed empty scratch directory and failure receipt were retained.

Candidate publication: **37,546,154,090 bytes**, including the manifest. Feature
files occupy 31.458 GB, ID lookups 1.073 GB, all immediate relationship tables
5.013 GB and directories 1.911 MB, plus provenance. This is slightly larger than
the original publication, not a free speedup. Candidate manifest SHA-256:
`155535aea34d16e8369ec0db416d2f58058911553c28e9031148607bb7511049`.
Its bytes are immutable; future code labels feature and relationship compression
separately rather than editing the measured manifest's ambiguous compression field.

## Local comparisons

Apple M4 Max, 64 GiB RAM, macOS 15.7.3; Python 3.13.14, PyArrow 25.0.1, NumPy 2.5.3
and DuckDB 1.5.6. Each CLI runs in a fresh process, with modest same-instance repeats.
Filesystem cache is uncontrolled, not cold. Serialized local reads are not physical
disk traffic or HTTP response bytes. Independent source validation occurs outside
timers but can warm files. No geometry decode is hidden in WKB receipt timings.
The main local matrix was serialized. A follow-up node correctness scan overlapped
the tail of reverse/extra probes and possibly the smaller-block build startup;
the retained seven reverse-index results are clean isolated reruns. Variant
producer startup may have overlapped that scan; its build time is not a precise
layout speed comparison.

Isolated global few-column scans include Python row/null/materialization census;
geometry is not decoded. All row counts and null censuses match:

| Domain / fields (+ID) | Original full / projected | Candidate full / projected |
| --- | ---: | ---: |
| Rivers / source_length, source_is_mainstem | 38.071 / 4.692 s | 9.381 / 0.324 s |
| Nodes / source_node_type, source_drainage_area | 23.625 / 4.654 s | 0.991 / 0.308 s |
| Catchments / area_km2, source_area | 45.538 / 4.410 s | 30.435 / 0.517 s |

Projected original/candidate serialized bytes were 418.56/209.60 MB for rivers,
200.76/64.33 MB for nodes and 404.22/288.13 MB for catchments. Original projected
scans issue 350,000–515,000 small serialized reads over roughly 87,000 batches;
candidate scans issue 15,000–27,000 over 2,720–6,706 batches. Larger batches reduce
compression and Python per-batch overhead as well as reads: elapsed improvements
are not purely an ordering effect. Full catchment process peak grew from 0.437 GB
to 1.045 GB. Tiny logical-byte differences reflect validity-buffer/block padding;
complete source row equivalence passed separately. Initial diagnostic river
full-scan timings overlapped tail hashing and are not the isolated figures above.
[Compact raw scan comparison](results/global-column-scans.json).

| Small spatial access | Opening | Discovery/selected access | Scope |
| --- | ---: | ---: | --- |
| Original river graph, retained metadata | ~203 ms | ~407 ms | Fair isolated bounds comparator |
| Original river record probe | included | 918.7 ms total | Seven bounds records; graph footer reopened |
| Candidate river record probe | included | 13.56 ms total | Same seven bounds records |
| Original/candidate catchment record probe | included | 933.4 / 21.39 ms total | Same eight bounds records |

The original record probe reopens its roughly 63 MB graph footer per selection:
an avoidable reader choice, **not** an inherent repeated format cost. The isolated
bounds comparator is narrower than the complete record sequence; neither number
is substituted for the other. Candidate row selectivity itself was not always
tighter; small metadata and local batches explain the improvement. Scattered
three-river record startup regressed: 11.92 ms versus 4.84 ms, with 17,857 versus
532 rows materialized.

For the independently established 1,292-river downstream membership, total first
result was 87.3 ms with uncached published batches, 52.4 ms with query-owned batch
reuse, 157.4 ms with bulk published adjacency and 3.933 s with a fair projected
original-graph consumer preparation. Query-owned reuse reduced serialized reads
from 155.069 MB to 0.507 MB and retained 0.504 MB. Bulk retained 447.215 MB. These
costs include opening/preparation, rather than hiding a global graph outside time.

The 88,513-river upstream case took about 5.5–5.9 s across published strategies.
The deliberately shared `union1d`/frontier algorithm dominates; this is not an
optimized engine or a regression against the archived millisecond traversal.
Batch reuse reduced reads from 1.578 GB to 2.366 MB, but local elapsed time barely
changed. The actual HTTP comparison below separates first use from repeated-work amortization.

Combined access sequences also passed independent seeds and closure hashes:
small catchment selection grew from three spatial seeds to ten upstream polygons,
with 30.0 ms candidate cached startup versus 131.5 ms bulk and 3.550 s original
consumer; geometry decoding was separate. Two spatial river seeds traced beyond
the window to 1,290 records in 117.9 ms candidate cached startup versus 220.6 ms
bulk and 5.004 s original. These are access sequences, not delineation, snapping
or a production river-selection policy. [Raw compact summaries](results/) retain
producer, traversal and workflow observations. Actual remote results follow below.

Source-node spatial discovery exercises a distinct domain without a supplied graph.
The original projected bounds scan returned five IDs in 6.468 s/475.62 MB versus
8.32 ms/5.81 MB with candidate spatial batches. Independent selected row/schema/null
comparison matched both layouts. IPC projection reads top-level schema fields;
the access result explicitly restores caller-requested column order. An initial
stream-hash difference was only column order: restoring the same requested order
makes both hashes equal. The follow-up
source scan overlapped earlier reverse-index timings; the retained seven reverse
comparisons are completed isolated reruns. [Node correctness](results/node-spatial-correctness.json).

Complete-record, selected-source-attribute and small-window probes covered every
available river/catchment tier in 22 additional local cases. Exact selected
Arrow stream identities agreed with independent original-source reads.
[Compact full-record/attribute/tier results](results/full-attributes-tiers-summary.json).
A component-catchment association returned 393,725 explicit river IDs (3.1498 MB);
that stored association is not a geographic-intersection result.

## Actual HTTP comparisons

The final serial matrix has 44 processes: 36 completed results passed; eight
request-capped diagnostics remained partial. This replaces the initial planned
matrix, not a claim that every initially proposed path completed.
These are serialized laptop runs, not cold-cache measurements. First use includes
opening, preparation and result acquisition; Shapely decoding remains separate.
Same-instance repeats retain bounded metadata; adjacency batch reuse resets per query.

| First result | Original seconds / GETs / MB | Candidate seconds / GETs / MB |
| --- | ---: | ---: |
| rivers clustered-projected | 4.247 / 9 / 5.553 | 7.054 / 18 / 2.163 |
| rivers clustered-full | 4.696 / 10 / 5.713 | 5.062 / 13 / 7.051 |
| rivers scattered-full | 6.312 / 14 / 7.742 | 7.241 / 17 / 14.315 |
| catchments clustered-projected | 4.578 / 9 / 5.567 | 15.240 / 39 / 2.866 |
| catchments clustered-full | 4.019 / 10 / 12.320 | 8.683 / 16 / 26.169 |
| catchments scattered-full | 7.386 / 14 / 13.753 | 6.830 / 17 / 15.991 |

Projection saved bytes but often multiplied sequential requests. It was not a
general remote win. Candidate clustered catchments required 28 fetch GETs on each
same-instance projected repeat versus one original GET; exact source rows matched.
Fresh-process catchment projected reruns reproduced the same transfer census:
4.830 s versus 14.099 s (original then candidate), not confidence intervals.

### Completed spatial and workflow sequences

| Candidate bounds discovery + records | Rows | First seconds / GETs / MB |
| --- | ---: | ---: |
| rivers small | 7 | 35.327 / 91 / 6.282 |
| catchments small | 8 | 55.632 / 139 / 5.662 |
| rivers large_amazon | 75495 | 134.658 / 334 / 25.030 |
| catchments large_amazon | 75929 | 276.185 / 631 / 28.405 |

Source as-used small river/catchment sequences matched the same 7/8 rows: 168.288 s, 684 GETs, 71.877 MB / 225.025 s, 922 GETs, 71.257 MB.
The isolated original comparator retains Parquet metadata and does only graph
selection, not records. River/catchment totals were 154.579 s (652 GETs) / 205.408 s (886 GETs).
It still projected many small graph ranges. This is not a controlled pure-layout
speedup: original reader behavior and supplied graph organization both matter.

These results fetched bounds, not regional WKB. Candidate local milliseconds did
not translate into remote milliseconds: request latency matters despite small bodies.

| Small spatial → supplied flow → decoded records | Seeds / reached | Startup seconds | First GETs / MB |
| --- | ---: | ---: | ---: |
| Candidate rivers, cached | 2 / 1290 | 49.986 | 132 / 43.409 |
| Original rivers, whole graph | 2 / 1290 | 201.345 | 508 / 740.396 |
| Candidate catchments, cached | 3 / 10 | 35.704 | 85 / 12.734 |
| Original catchments, whole graph | 3 / 10 | 78.072 | 240 / 725.300 |

Workflow seeds/closures and source identities matched independent witnesses. This
driver checks addressed output IDs, not independent complete-row equality for every
workflow; global verification and separate record probes establish value/WKB fidelity.
The original file strategy includes actual graph acquisition and reverse preparation.
Its geography and record paths still use the explicitly measured as-used reader.

### Flow acquisition and repeated use

Candidate query-owned batch reuse reads immediate adjacency once per reached batch.
Whole-file strategies acquire and verify the complete relevant artifact into temporary
local storage, then project and prepare within the first-result timer. They are not
equal-byte comparisons: candidate adjacency includes all relationships (2.298 GB);
the original graph is 596.714 MB. Prepared repeated traversals issue zero HTTP GETs.

| Supplied river membership | Candidate cached first / repeat | Candidate whole file first / repeat | Original whole graph first / repeat |
| --- | ---: | ---: | ---: |
| 4: 1,292 inclusive | 5.794 / 2.873 s | 159.148 / 0.037 s | 14.423 / 0.038 s |
| 1233924: 88,513 inclusive | 21.694 / 15.054 s | 30.231 / 4.938 s | 13.685 / 4.964 s |

No first-use reached-count crossover between candidate query-owned batch reuse
and whole-file preparation was observed at 1,292 or 88,513 IDs. The same candidate artifact downloaded in 156.806 and 23.252 seconds
in the two runs: cache/CDN/route/transfer state was uncontrolled. Reached count did
not cause that transfer-time difference. The common NumPy frontier algorithm also
accounts for seconds in the larger traversal; this is not delineation performance.


The large cached query used 42 GETs / 2.366 MB and retained
2.354 MB of adjacency. Candidate whole-file preparation retained
447.215 MB and used 2.298 GB temporary disk; original whole-graph preparation
retained 450.007 MB and used 596.714 MB temporary disk. Logical buffers,
workspace and lifetime RSS remain distinct in [sequence receipts](results/remote-sequences.json).

### Observed repeated-work crossover

Ten same-seed, 88,513-ID queries ran in each of two fresh processes: candidate
whole-file first, then candidate query-owned batch reuse. Each of the 20 closures
matched its independent source witness. Cumulative phase sums include opening,
acquisition and preparation once, plus each actual measured query:

| Query count | Whole-file cumulative seconds | Cached cumulative seconds |
| ---: | ---: | ---: |
| 1 | 27.903 | 17.568 |
| 2 | 32.790 | 33.201 |
| 10 | 71.744 | 158.326 |

The first observed whole-file total no slower than cached was query 2. This is
actual repeated-work amortization, not a universal query-count or reach-count
threshold. Whole-file retained the projected global graph; cached cleared adjacency
between queries. CDN/network/filesystem state and run order were uncontrolled.
Totals are phase sums, not wall-clock process times. Small-work repeated crossover
was not established beyond two queries. [All ten points and bindings](results/remote-repeated-work.json).

### Associations and bounded diagnostics

Association composition remained explicit association∩bbox, not flow, containment
or delineation. Actual HTTP first/repeat seconds were:

| Composition | Association / spatial / result IDs | First / repeat seconds |
| --- | ---: | ---: |
| local_river_ids ∩ small | 1 / 7 / 1 | 35.612 / 29.384 |
| component_river_ids ∩ large_amazon | 393,725 / 75,495 / 0 | 79.522 / 70.752 |

The empty component result is valid. Source record values and independent ID
witnesses matched; original reverse preparation is reported separately, not hidden.

Eight real-HTTP diagnostics stopped before GET 129 after 128 successful GETs.
This is a resource budget, not a performance threshold. Uncached traversal,
projected batch-by-batch bulk and original projected graph preparation did not
finish at either flow size. Neither original Amazon discovery finished. Observed
bodies/time-to-stop were:

| Partial path, small / large | Actual MB | Seconds to cap |
| --- | ---: | ---: |
| Candidate uncached | 6.116 / 8.014 | 31.532 / 31.531 |
| Candidate projected bulk | 5.577 / 7.203 | 30.655 / 30.186 |
| Original projected consumer | 62.671 / 62.670 | 30.942 / 31.083 |
| Original Amazon rivers / catchments | 67.165 / 67.405 | 33.577 / 33.264 |

These are partial transfer observations, never completed query times or estimates.
Equal GET counts do not mean equal information or progress; original partials
include large graph-footer reads. [Stop receipts and raw hashes](results/remote-diagnostics.json).

### Temporary publication lifecycle

Approved upload published 26 objects / 37,546,154,090 bytes in
3418.153 s (10.984 MB/s), separate from producer build/verify.
Local SHA-256, multipart identity/HEAD checks and public manifest/bounded artifact
readback passed; public checking was not a second full global download. Full-file
flow acquisition additionally checked complete downloaded SHA-256 and length.

Only the 26 exact experiment-owned keys were then deleted with matching ETags;
each returned 404, the prefix was empty and no multipart uploads remained. The
original public manifest SHA-256 was unchanged before/after. Local originals and
candidates were not deleted. The candidate URL is historical and no longer serves
data. [Upload, public identity and cleanup evidence](results/remote-lifecycle.json)
retains every owned object identity. No production runtime or input contract changed.

[Compact remote records](results/remote-records.json),
[isolated graph comparisons](results/remote-isolated-spatial.json) and
[code/raw-receipt bindings](results/remote-code-bindings.json) preserve exact units,
phase boundaries and provenance without committing range logs or global data.

## Focused 256-row variation

The only changed layout constant was maximum feature rows, 8,192 → 256; 8 MiB
logical budget, Morton ordering, compression and ID lookup stayed fixed. This
trial rebuilt rivers and catchments only, not nodes or adjacency. Its 31.895 GB
partial publication cannot be compared to the complete 37.546 GB bundle.
River feature bytes grew 9.348 → 9.745 GB (+4.25%); catchments 20.743 → 21.407 GB
(+3.20%). Manifest SHA-256:
`5633d6798795d2c34886676fb85d9f1ec8c62fb85a419b27308403ea0a5e4a8a`.

Build took 472.870 s with 13.457 GB peak RSS; full verification took 358.756 s
with 21.169 GB peak RSS. The measured builder performed a scratch-directory
filesystem census after every output batch. This instrumentation scales with
batch count and may materially inflate producer cost. Future code samples before,
every 1,024 batches and after output; these remain observed, not exact, spill peaks.
Neither existing artifact nor measured receipt was rewritten.

| Operation | Original | 8,192-row candidate | 256-row candidate |
| --- | ---: | ---: | ---: |
| First 16 clustered river WKB, fetch bytes / rows | 1.178 MB / 256 | 5.801 MB / 1,473 | 2.388 MB / 512 |
| First 16 clustered catchment WKB, fetch bytes / rows | 7.794 MB / 173 | 24.308 MB / 1,887 | 19.139 MB / 1,536 |
| Small river discovery + seven records, startup | 918.7 ms | 13.56 ms | 98.35 ms |
| Small catchment discovery + eight records, startup | 933.4 ms | 21.39 ms | 99.13 ms |
| Global projected river scan | 4.692 s | 0.324 s | 12.951 s |
| Global projected catchment scan | 4.410 s | 0.517 s | 16.284 s |

The smaller cap reduced small spatial materialization from 49,968 to 2,816 river
rows and 32,663 to 3,584 catchment rows. But full footer/catalog acquisition and
JSON parsing grew to about 80 ms/17.9 MB opening per domain, dominating first use.
Small same-instance repeated records took about 6 ms. The projected scan now
visits about 87,000 batches, again showing Python/compression/read overhead, not
just ordering. These results do not justify inventing an intermediate row cap.
Compact directory/footer design and HTTP byte/request trade-offs need evidence.
[Variation receipts](results/rowcap256-record-summary.json).

## Reverse preparation and explicit association composition

Clean isolated original-consumer projection plus a sorted numeric reverse index
cost 8.600 s for river parent membership, 2.691/2.428 s for outgoing/incoming node
incidence, 4.022 s for coarser-node correspondence, 2.156/2.667 s for local/component
catchment association and 12.222 s for catchment parent membership. Prepared
queries were microseconds. These are straightforward full-projection/index
comparators, not a claim of an optimal database implementation. Retained Arrow
and numeric index buffers and peak RSS are separate in the
[isolated reverse receipts](results/reverse-isolated-summary.json). Candidate
published immediate lists avoid that global consumer preparation; they do not
avoid consumer traversal or workspace. Catchment 1's 101,634 children are parent
membership, not flow closure.

A composition probe intersected explicit associations with independently checked
bbox candidates, then fetched exact source records. Local catchment 82,558 had
one associated river; seven spatial candidates yielded that one record, with WKB
decode separate: 28.65 ms startup / 9.01 ms same-instance repeat. Component 8,720's
393,725 associated rivers intersected 75,495 Amazon bbox candidates in **zero**
IDs: 88.91 / 62.79 ms. This empty result is valid and is not basin delineation,
containment or evidence that association and geography are interchangeable.
[Composition receipts](results/association-summary.json).

## Reproducibility

[Portable commands](REPRODUCE.md) cover original/candidate records, source attributes,
spatial/tier discovery, selective/cached/bulk traversal, combined workflows,
reverse-index preparation and scans. The measured numerical algorithms were copied
into this experiment, with relative imports, optional geometry decoding and portable
source/report paths. [Preintegration code hashes](results/measurement-source-hashes.json)
preserve the original receipt bindings. Workload and source-only oracle JSON remain
small; no global data or range logs are committed.

A review found that legacy direct relationship probes counted each adjacency batch
under both `lookup_blocks` and `data_blocks`. Serialized bytes were not doubled.
Current direct and cached reads classify adjacency as data only. Keep historical
receipts unchanged; do not sum those old block categories. The review also requested
independent categorical-meaning and source-schema manifest checks; both measured
immutable candidates passed independent metadata audits. The patched verifier
rejects both independent meaning/schema mutations in tiny fixtures, and its
metadata-only helper passed both unchanged global manifests. Full row/edge
verification was not needlessly repeated for this metadata-only repair.
[Patched audit](results/patched-source-claims-audit.json).

## Correctness and integrity

Full verification reread all three original and candidate domains. It checked
schema metadata, exact row values/nulls/native attributes/WKB, sorted unique IDs,
complete lookup coverage and addresses, and exact conservative physical batch
bounds. Every derived relationship was compared to independently expanded source
edge pairs, including both flow graphs and separate cross-domain references.
Each supplied flow graph has 22,395,952 edges. Full source and derived fingerprints
were included in the separately timed producer verification.

Focused independent sparse fixtures cover absent IDs, duplicate request order,
null references, split/reconvergence, batch boundaries, distinct overlapping ID
domains and shared-node incidence without invented flow pairs. Deliberate wrong
bindings, addresses, spatial metadata and edges reject. This does not add worldwide
polygon topology or hydrological certification beyond the source delivery.

Ordinary probes check bounded fingerprints, lookup bindings and selected address
IDs. HTTP uses the existing identity-encoding/206/Content-Range/strong-ETag checks.
Bounded fingerprints do not authenticate arbitrary interior corruption; full
producer/upload verification and trusted immutable manifests remain necessary.

## Proposed contract changes and next delivery

For maintainer discussion, not adoption:

- Keep independent information access as a capability. Require real projected
  buffer access; do not mandate separate geometry/attribute files without evidence.
- Publish ID access, conservative geographic discovery and immediate forward/reverse
  relationships. Declare the authority and target domain of every derived index.
- Let producers perform reusable preparation and full verification once. Consumers
  choose selective, grouped cached or bulk use, execute queries and own workspace.
- Retain exact native data and unknown/cut semantics. Neither geometry nor basin
  membership substitutes for supplied flow or exact geographic selection.

Do not adopt either tested row cap. The completed one-factor variation exposes
locality/geometry overread versus metadata/startup/global-scan cost. Actual HTTP
results add request amplification and an observed repeated-work trade-off, not a
production recommendation. Parquet remains a justified focused alternative only if a material IPC
weakness remains; no exhaustive format tournament was run. A SQLite HTTP VFS,
runtime-specific snapshots, native-coordinate geometry rewrite and precomputed
transitive closures add no demonstrated need here. Full closures would duplicate
reached IDs for every seed, unlike immediate edges; no global closure size was
measured or invented.

A subsequent agreed production vision is still required. Starting from verified
hosted vectors, this laptop trial measured roughly 414 s build plus 432 s complete
verification and a 37.55 GB output, plus separately measured experimental upload
and bounded public readback. It did not measure original-source re-ingest or full
production review. Production would still need an agreed contract, approved
immutable destination/retention and production publication verification comparable
to PR #32. Original rasters and publications remain unchanged. Bring these findings
to the maintainer and Pourpoint #36 before selecting any production design.
