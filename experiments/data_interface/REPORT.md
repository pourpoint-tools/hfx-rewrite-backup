# HFX data interface findings

**Interim report.** Global correctness and the first local measurements passed.
Both global layouts passed complete verification; 134 local runs are complete. True remote candidate measurements are blocked pending approval of an immutable experimental upload
prefix. This is evidence for discussion, not adoption of a new format.

Related: [HFX #35](https://github.com/pourpoint-tools/hfx/issues/35),
[Pourpoint #36](https://github.com/pourpoint-tools/pourpoint/issues/36), and the
[published vision](../../planning/visions/2026-10-16-hfx-data-interface-experiments-with-grit.md).

## Findings so far

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
4. **Local evidence does not settle HTTP behavior.** Projection reduces bytes but
   can multiply requests. One real river batch required 583,216 bytes/one range in
   full versus 2,921 bytes/five projected ranges. These were correctness
   diagnostics concurrent with acquisition, not isolated timing comparisons.

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
changed. Remote selective/bulk crossover remains unmeasured.

Combined access sequences also passed independent seeds and closure hashes:
small catchment selection grew from three spatial seeds to ten upstream polygons,
with 30.0 ms candidate cached startup versus 131.5 ms bulk and 3.550 s original
consumer; geometry decoding was separate. Two spatial river seeds traced beyond
the window to 1,290 records in 117.9 ms candidate cached startup versus 220.6 ms
bulk and 5.004 s original. These are access sequences, not delineation, snapping
or a production river-selection policy. [Raw compact summaries](results/) retain
producer, traversal and workflow observations. Remote measurements remain pending.

Source-node spatial discovery exercises a distinct domain without a supplied graph.
The original projected bounds scan returned five IDs in 6.468 s/475.62 MB versus
8.32 ms/5.81 MB with candidate spatial batches. Independent selected row/schema/null
comparison matched both layouts. IPC projection reads top-level schema fields;
the access result explicitly restores caller-requested column order. An initial
stream-hash difference was only column order: restoring the same requested order
makes both hashes equal. The follow-up
source scan overlapped reverse-index timings; affected reverse timings are excluded
until the clean rerun. [Node correctness](results/node-spatial-correctness.json).

Complete-record, selected-source-attribute and small-window probes covered every
available river/catchment tier in 22 additional local cases. Exact selected
Arrow stream identities agreed with independent original-source reads.
[Compact full-record/attribute/tier results](results/full-attributes-tiers-summary.json).
A component-catchment association returned 393,725 explicit river IDs (3.1498 MB);
that stored association is not a geographic-intersection result.

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
locality/geometry overread versus metadata/startup/global-scan cost. Finish remote
request-count/coalescing and traversal crossover measurements, then discuss trade-offs. Parquet remains a justified focused alternative only if a material IPC
weakness remains; no exhaustive format tournament was run. A SQLite HTTP VFS,
runtime-specific snapshots, native-coordinate geometry rewrite and precomputed
transitive closures add no demonstrated need here. Full closures would duplicate
reached IDs for every seed, unlike immediate edges; no global closure size was
measured or invented.

A subsequent agreed production vision is still required. Starting from verified
hosted vectors, this laptop trial measured roughly 414 s build plus 432 s complete
verification and a 37.55 GB output; it did not measure original-source re-ingest,
full production review or upload/readback time. Production would need approved
immutable destination/retention, full uploaded identity readback, public selective
checks, provenance/licensing and manifest-last publication comparable to PR #32.
Original rasters and publications remain unchanged. Remote evidence and final
format choices are unresolved; findings must return to the maintainer and
Pourpoint #36 before production adoption.
