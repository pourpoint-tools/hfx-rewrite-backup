# HFX data interface experiments with GRIT

Design and measure a straightforward candidate for an efficient HFX data interface,
using the delivered GRIT dataset. Return findings for the maintainer to discuss
before finalizing the format. This is an experiment handoff, not approval to adopt
a production layout or re-wrangle the public dataset.

Related: [HFX #35](https://github.com/pourpoint-tools/hfx/issues/35).
Coordinate the findings with [Pourpoint #36](https://github.com/pourpoint-tools/pourpoint/issues/36).

## Outcome and design direction

HFX is a data contract consumed by a downstream delineation engine, not an
implementation of delineation or a serialization of one Python runtime.
Its storage and access conventions should let consumers obtain needed information
without unnecessary worldwide scans, unrelated geometry reads, or rebuilding the
same reusable indexes on every laptop. Useful common preparation belongs in
production when it can be performed once and published portably.

HFX 0.4.0 is still being designed. Existing schema, storage, indexes, ordering,
manifest and reader decisions are evidence, not compatibility constraints.
Reconsider them where needed for a comprehensive, consistent contract. Do not
assume the answer is to add sidecars indefinitely to the existing layout.

The agreed direction is:

- Independently accessible relationships, bounds, source attributes and geometry.
  Independent access is the requirement; a separate file for each is not selected.
- Producer-prepared ID, geographic and forward/reverse relationship access.
- Selective access for small requests and efficient bulk access for repeated work.
- Consistent conventions across catchments, rivers and source nodes, without
  collapsing their different identities or meanings.
- Laptop use without requiring cloud machines, whole-dataset memory residency or
  global preparation merely to answer a small query.
- Preservation of source information, native types, nulls, exact delivered geometry,
  schema metadata, categorical meanings and provenance.

Not every query can avoid a scan. Arbitrary attribute predicates may scan their
relevant columns; they should not inherently require unrelated attributes or WKB.
Do not build a universal query optimizer or an index for every source column.

The eventual goal, after the maintainer reviews this evidence and settles the
contract, is a fully verified re-wrangled GRIT publication on public R2, comparable
in delivery rigor to [PR #32](https://github.com/pourpoint-tools/hfx/pull/32).
That production phase needs a subsequent agreed vision or revision of this one.

## Consumer workflows informing the tests

Pourpoint plans point watersheds, upstream contributing areas for geometry targets,
river networks within a basin or geometry, and downstream river tracing beyond a
selected basin. Its complete delineation and Engine API are not implemented.
These workflows motivate composable data access, not feature implementation here:

| Workflow | Access sequence to exercise |
| --- | --- |
| Point watershed | Spatial candidates, upstream catchment membership, selected bounds/polygons; optional raster access remains separate |
| Geometry contributing area | Spatial candidates, upstream relationships beyond the target envelope, selected polygons |
| Rivers in a basin or geometry | Spatial access and explicit catchment associations, selected river attributes/geometry |
| Follow rivers beyond a basin | Downstream relationships beyond a spatial selection, selected river records |

Use [Pourpoint's contributing-area definition](https://github.com/pourpoint-tools/pourpoint/blob/f449c0fbf57a6e6516b3fe8b53df0fd4da0397ba/docs/upstream-contributing-area.md):
land with some downstream path to any part of the target, including its boundary.
Spatial windows must not truncate connectivity. Bounding-box overlap returns
candidates, not exact intersection or containment. A basin association is not a
substitute for exact geographic selection.

Keep same-tier flow, parent membership, directed endpoint incidence, node cross-tier
correspondence, and local/component catchment associations distinct. Preserve
splits and reconvergence. Shared nodes do not imply every possible flow pair.
River, node and catchment tiers and ID domains are separate. Missing connectivity
is not a known terminal; GRIT component catchment connectivity is not supplied.
Do not infer missing edges or hydrological associations from geometry.

## Evidence to inspect before designing candidates

Read the current [vector contract](../../docs/v0.4.0/vector-data.md),
[GRIT delivery record](../../docs/v0.4.0/grit-river-delivery.md) and its receipt.
The verified public input is:

<https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0-rivers-2026-10-12/manifest.json>

It contains 22,419,857 catchments, 22,337,300 rivers and 22,278,858 nodes, with about
37 GB of vector/provenance artifacts. Pin the manifest identity and actual
contract/code revisions used; do not rely on a mutable latest manifest.

In `../pourpoint`, read these files directly from Git tag
`archive/river-runtime-experiments-2026-10-16`, not the current working tree:

- `experiments/river-runtime-design/REPORT.md`
- `experiments/river-runtime-design/architecture-findings.md`
- `experiments/river-runtime-design/contract-findings.md`
- `experiments/river-runtime-design/review.md`
- `experiments/river-runtime-relationships/REPORT.md`
- `experiments/river-runtime-relationships/review.md`

For example, use `git show archive/river-runtime-experiments-2026-10-16:<path>`
from that checkout. Obtain the archive if unavailable before relying on its claims.

Those experiments establish that prepared relationships make traversal fast, but
structural preparation still scans feature IPC containing WKB. One downstream
traversal took about 0.9 ms prepared versus 55 s with repeated graph scans.
Combined structural river/node representations plus flow retained 4.248 GB versus
16.070 GB for all nongeometry residency. Structural river preparation took about
33 s versus 39 s for full attribute residency; a validated structural snapshot
reopened in about 1.15 s. These warm/uncontrolled-cache laptop observations are
not acceptance targets, and no alternate producer-published layout was tested.

Also inspect Pourpoint `docs/runtime.md` and the actual access paths. Existing
known-ID lookup and native-grid raster window access are useful strengths.
Whole-graph preparation triggered by selected-record validation is partly a reader
choice, not inherently a storage requirement. Separate reader-induced costs from
format-induced costs; do not give the candidate an artificial advantage by retaining
avoidable baseline coupling. Report both as-used and fairly isolated costs where
that distinction matters. Current reader compatibility with the delivered river
bundle is not established.

## Experiment strategy

Start with one coherent candidate using established columnar storage and indexing
techniques, plus the current publication as baseline. Describe its logical tables,
authoritative fields, access paths and identity bindings before implementing the
small access probes. This is a proposed contract sketch, not a normative revision.

Investigate suitable existing libraries and representations rather than inventing
custom machinery. Choose routine mechanisms independently. Do not run an exhaustive
format tournament: test alternatives where a material trade-off or measured weakness
justifies them. Do not assume separate files, a database, Arrow IPC, Parquet, a
particular index, or a runtime snapshot is the winner.

### 1. Independent information access

Compare the current combined feature batches with a candidate that separates
structural information, source attributes and geometry access. Where useful, compare
physical separation against independently readable columns. Exercise bounds-only,
relationship-only, selected attributes, geometry, and complete-record retrieval.
Include clustered/scattered IDs, overlapping requests, small/large basin selections,
and regional or global scans of a few actual source attributes.

Determine how much unrelated data is fetched or decompressed, the cost of joining
information back into complete records, and whether one layout serves selective and
bulk use adequately. Measure geometry retrieval separately from geometry decoding.

### 2. Producer-prepared relationships

Compare consumer-built indexes with portable published forward/reverse access,
including a compact adjacency candidate usable selectively and in bulk.
Exercise upstream/downstream flow, parent/children, node/incident rivers,
coarser/finer node correspondence, and catchment/associated rivers. Cover river and
catchment flow where supplied; never invent a component graph.

Test small and large traversals, splits/reconvergence, repeated and overlapping
queries. Include remote traversal: a few bytes per edge can still be slow if each
step requires another sequential HTTP request. Measure grouping, reuse and the
crossover between selective reads and bulk acquisition explicitly.

Indexed immediate neighbors are a sensible starting hypothesis. Do not precompute
every feature's full upstream/downstream set by default; quantify duplication and
build costs before considering that alternative. Consumers still execute their
queries; producer preparation does not imply precomputing every possible result.

### 3. Geographic discovery and physical locality

Compare current bounding-box filtering with a published spatial access structure
and useful spatial ordering/block organization. Test rivers and catchments at
available tiers. Use small, elongated, large and partition-boundary-crossing windows,
empty results, and features crossing query boundaries. Include source-node access
where it exercises a distinct requirement.

Measure candidate discovery and subsequent selected reads together and separately.
An index returning IDs scattered across many blocks may still be expensive.
Evaluate block size, physical ordering and compression only through focused
variations that expose request-count versus overread trade-offs. Check conservative
candidate completeness independently; exact geometry filtering is a reference or
probe operation, not a new production selection feature.

### 4. Combined access sequences

Combine promising choices into the workflow-shaped sequences above: candidates,
relationships, bounds, then requested attributes or geometry. Use independently
established selections, not a new delineation or river-selection implementation.
Show costs for small first use and substantial repeated local work. A global graph
already prepared outside the timer must not hide the candidate's startup cost.
Check whether changes that help one primitive harm the complete access sequence.

## Data scale, correctness and measurement

Use real GRIT throughout. Small complete components and explicit fixtures support
correctness and development; they cannot establish global index size, locality,
startup or traversal costs. Scale promising structures to the global counts and
exercise realistic global addressing before recommending adoption. Start with an
input inventory and resource estimate. Acquire only needed artifacts where possible;
verified hosted vectors may be sufficient without reacquiring all original sources.

Verify requested identities, supplied edges, reverse relationships, tiers, nulls,
native attributes and exact WKB against independent input reads. Include absent IDs,
sparse/non-row IDs, optional relationships, batch boundaries, split/reconvergence
and cut-edge behavior. Preserve absence/unknown semantics. Derived indexes must
agree with authoritative records and bind to their exact artifact identities.
Full producer verification and ordinary reader checks have different costs; explain
which integrity checks occur during each measured operation.

Report reproducible commands, dependency/code versions, input identities and raw
small machine-readable results. Measure:

- producer build time, peak memory, temporary disk and publication size;
- opening, first use, consumer preparation, repeated use and reopening;
- actual range requests and returned body bytes for remote reads;
- selected versus fetched blocks/rows, requested versus materialized data;
- retained buffers, query workspace and process peak memory, clearly distinguished;
- local and remote elapsed time, with decoding separately identified.

Use modest repetitions in fresh processes and disclose filesystem-cache state,
reader caches, concurrency, hardware and network conditions. Do not label uncontrolled
filesystem reads cold or call local results remote evidence. Track caching and
prefetch consistently; report total-to-result as well as phases. There are no agreed
numerical performance thresholds. Return trade-offs and limitations rather than
inventing pass/fail budgets or claiming complete delineation performance.

## Boundaries and delivery

Use uv, strongly typed Python, Ruff and ty for experiment code. Follow repository
test-first guidance with focused independent cases. Build small probes, not a
supported reader library, generalized compiler, cache framework or benchmark service.
Keep experiment records/code in a focused repository experiment directory; keep
bulk datasets, generated candidate artifacts and credentials outside Git.

Do not implement snapping/ranking, clipping policy, mainstem choice, delineation,
impact analysis or visualization. Do not rewrite rasters or expand this into a
raster redesign without evidence of a relevant blocker. Do not modify Pourpoint's
production runtime or claim its adoption of the experimental interface.

Public GRIT retains CC BY-NC 4.0 terms. Preserve provenance and existing publications.
Read-only public access is allowed; obtain explicit approval for any experimental
upload destination, paid compute and budget. Use disjoint immutable experimental
outputs. Do not overwrite R2 objects, amend the production manifest or provision
production infrastructure under this handoff. If resources block representative
measurements, report the precise need rather than silently changing scope.

Deliver a concise report with:

- the candidate interface and physical layout, with shared conventions and exceptions;
- measured comparisons against baseline and justified variations;
- correctness evidence and exact source/derived bindings;
- recommended producer versus consumer responsibilities;
- rejected alternatives, meaningful regressions and unresolved uncertainty;
- proposed contract changes and the estimated path/cost to full GRIT re-wrangling.

Return the findings to the maintainer and Pourpoint #36 before any production
adoption. A negative or inconclusive result is valid. Stop for discussion: the
maintainer will bring findings back to decide how to finalize HFX and authorize
the subsequent full dataset delivery.
