# GRIT physical layout selection

Find a defensible physical layout for HFX using the actual global GRIT data on R2.
The goal is fast time to useful spatial results on first access, while keeping large
requests and bulk reads efficient. Return an evidence-backed recommendation for
maintainer discussion; this work does not adopt a production contract or re-wrangle
the production publication.

Related: [HFX #35](https://github.com/pourpoint-tools/hfx/issues/35).
Coordinate findings with [Pourpoint #36](https://github.com/pourpoint-tools/pourpoint/issues/36)
before its final reader/runtime design. This is the focused follow-up to the
[completed interface experiments](2026-10-16-hfx-data-interface-experiments-with-grit.md),
not a restart of broad architecture discovery. Preserve those experiments and receipts.

## Priorities and settled direction

- Spatial access has highest priority. Lead with small-to-medium interactive windows,
  elongated corridors and queries crossing storage boundaries. Large spatial selections,
  requests for many features together and bulk scans must also remain efficient.
  “Large batches” here means large consumer requests, not a requirement for large
  on-disk record batches.
- Time to useful results is the main measure. Include discovery and retrieval of the
  requested bounds, attributes or geometry, not merely candidate IDs. Exercise selected
  relationships and records together where the workflow requires them; report geometry
  decoding separately.
- Fast first reads matter, not just cache hits. A small query must not require a
  pre-existing local cache, global download or global preparation. Repeated reads should
  also be fast, but report them separately rather than using them to conceal startup.
- Extra published data is very much acceptable when its benefit is hard won: demonstrate
  a substantial benefit against simpler alternatives, and account for storage, build and
  verification costs. One authoritative feature representation plus compact indexes is a
  starting preference, not a prohibition on duplication.
- Known-ID access, immediate relationship access and bulk preparation remain important
  comparisons. Spatial improvements must expose their costs to these paths rather than
  silently sacrificing them.

No physical layout is selected. File count or sharding, record order, batch sizes,
compression, metadata organization, separate versus co-located geometry and the physical
representation of access structures remain engineering choices to investigate. Neither
existing source order nor the candidate Morton order is binding. Do not guess a row cap
between the two measured variants. No numerical latency, memory or request-count threshold
has been agreed.

## Starting evidence and real data

Read all comments on #35, the merged [findings](../../experiments/data_interface/REPORT.md),
[reproduction instructions](../../experiments/data_interface/REPRODUCE.md) and
[candidate sketch](../../experiments/data_interface/README.md). The
[current vector contract](../../docs/v0.4.0/vector-data.md) describes the existing
publication, not a compatibility constraint for this investigation. PRs
[#32](https://github.com/pourpoint-tools/hfx/pull/32),
[#36](https://github.com/pourpoint-tools/hfx/pull/36) and
[#37](https://github.com/pourpoint-tools/hfx/pull/37) preserve delivery and experiment context.

Use the existing R2 infrastructure, not a newly provisioned storage service:

- AWS CLI operations use `aws --profile upstream-r2`; use the configured R2 endpoint.
  Do not expose credentials or account configuration in Git or reports.
- Bucket: `basin-delineations-public`; source prefix:
  `grit/hfx-v0.4.0-rivers-2026-10-12/`.
- Public range-read root:
  <https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0-rivers-2026-10-12/>.
- Source manifest SHA-256:
  `b9a38083131dcf1a4c7c4e73ebe9a97dff2a4b7ef91a8df53f8bc38cadfa48db`.
- The verified publication contains 67,036,015 catchment, river and source-node records
  and about 37 GB of vector/provenance artifacts. See the
  [delivery record](../../docs/v0.4.0/grit-river-delivery.md) for identities and licensing.

Reuse verified local inputs or candidate artifacts if available and identity-matched;
do not assume their old local paths still exist. The previous temporary candidate R2
prefix was deleted. Real remote reads are required to support remote-access conclusions;
synthetic fixtures and local timings cannot substitute for global GRIT and actual R2/HTTP
measurements. Existing hosted vectors are sufficient starting inputs; original-source
re-ingest is not required for this follow-up.

The completed evidence establishes that IPC projection can skip unrequested compressed
buffers before decompression. Co-located attributes and WKB do not inherently force a
geometry read. Smaller batches reduced some geometry overread but increased metadata,
startup and scan costs. Projected remote reads sometimes multiplied requests enough to
outweigh byte savings. Previous baseline readers also repeated avoidable footer work.
Neither the 8,192-row nor 256-row candidate is recommended for adoption.

The starting comparisons already exist:

| Layout | What it contributes to the comparison |
| --- | --- |
| Original GRIT publication | Production baseline with a corrected projected/grouped reader |
| 8,192-row candidate | Complete spatially ordered candidate with batch bounds, ID access and immediate relationships |
| 256-row variation | Rivers/catchments-only feature variation exposing reduced overread versus larger metadata and slower scans; not a complete alternative bundle |

Reuse their existing artifacts when verified and available, or reproduce only what the
focused comparison needs. The next metadata/layout variation is not preselected: derive
it from residual measured costs after reader improvements. Do not rebuild every layout
or publish every candidate merely to repeat an already answered comparison.

## Focused investigation

First establish what a corrected reader can do with unchanged artifacts. Use actual
column projection, retain reusable metadata within the reader instance and investigate
range-request grouping. Include opening and all prerequisite reads in first-result
measurements. Fair comparisons must use comparable reader improvements on original and
candidate artifacts; distinguish reader changes from physical-layout changes.

Then address material residual costs with focused metadata or physical-layout variations.
Compact or selectively readable metadata, spatial organization and independently readable
information are possibilities, not selected mechanisms. Existing libraries and formats
should be investigated before inventing custom machinery. Test an alternative such as
Parquet where an actual IPC weakness justifies it, not as an exhaustive format tournament.
Do not simply accumulate sidecars around a bad underlying layout.

Use a representative, bounded workload set grounded in the prior source-only witnesses:

- Spatial discovery followed by projected attributes and geometry/full-record retrieval
  for small and medium windows, corridors, storage-boundary crossings and large regions.
- Clustered and scattered known IDs, absent IDs and requests for many records together.
- Immediate forward/reverse relationships and selected spatial-to-flow-to-record sequences,
  including connectivity beyond the discovery window.
- Large projected scans and bulk connectivity acquisition/preparation, plus repeated use.

Cover rivers and catchments at relevant tiers; include source nodes where they exercise
a distinct access cost. Reuse the independent witnesses where applicable and extend them
only where new workloads need them. This is access measurement, not an optimized traversal
engine or implementation of watershed selection.

Measure total time to useful results, opening/metadata and fetch phases, actual HTTP
request counts and returned bytes, selected versus fetched data, geometry overread and
bulk throughput/preparation. Report publication size, producer cost, retained buffers and
peak process memory where a change materially affects them. Bytes and request counts
explain elapsed time; neither is an independent optimization target. Extra transfer to
remove round trips may be worthwhile, but make that compromise visible.

Separate first-use trials in fresh processes from same-instance reuse. Disclose local
filesystem, CDN and network cache uncertainty: a fresh consumer is not proof of a cold
CDN. Use controlled comparisons to explain mechanisms and actual remote trials to check
that benefits survive network conditions. Report concurrency and apply comparable policies;
do not attribute a transfer-state change to layout. Keep experiments proportional to the
remaining decision. If uncertainty remains, identify the exact choice it blocks rather
than automatically expanding the matrix.

## Correctness, scope and publication safety

Preserve exact delivered WKB, native types, nulls, schema metadata, source meanings and
provenance. Keep catchment, river and node identities and tiers distinct. Flow, hierarchy,
directed node incidence, cross-tier correspondence and local/component associations are
different relationships. Preserve splits, reconvergence and unknown/not-supplied semantics;
never invent flow from shared nodes or geometry. Bounding-box overlap returns conservative
candidates, not exact intersection or containment.

Producer-prepared ID, spatial and immediate forward/reverse access remain the interface
direction. Consumers execute traversal and own query workspace; do not publish transitive
closures or runtime-specific snapshots. Bind derived artifacts to exact authoritative
identities. Preserve independent selected-result and source-fidelity checks; fully verify
any global derived artifact used to support a recommendation. Selected-read checks are not
full interior authentication.

Use small typed probes with uv, Ruff, ty and test-first development. Reuse the completed
experiment where useful; do not build a supported reader library, generic cache framework,
query optimizer or benchmark service. Bulk datasets, credentials and full request logs
stay outside Git. Preserve compact results, commands, code/dependency versions, input
identities and meaningful rejected alternatives.

Leave production R2 objects, manifests and rasters unchanged. Read-only access through the
existing profile is the established path; it does not authorize new uploads or paid compute.
If remote candidate measurements require publication, obtain approval for a new empty
experiment-only prefix and its retention/cleanup plan. Follow the prior verified upload,
manifest-last publication, immutable identity checks and exact owned-object cleanup pattern.
Do not reuse the deleted prefix or modify existing publications. GRIT retains CC BY-NC 4.0.

Exclude production contract adoption, full GRIT re-wrangling, Pourpoint runtime changes,
snapping policy, clipping, mainstem choice, delineation and raster redesign.

## Deliverable and stopping point

Return a focused report and reproducible compact evidence recommending a coherent physical
layout and required reader behavior, with explicit compromises for first spatial results,
large requests, bulk use and reuse. Show which gains come from reader fixes versus storage
changes. Any substantial duplication must have measured justification against simpler
alternatives. Explain rejected layouts and remaining decision-blocking uncertainty.

Return the findings to #35 and Pourpoint #36 for maintainer confirmation before production
adoption or full re-wrangling. A defensible choice need not win every workload. Do not close
#35 or merge production changes merely because the experiments are complete. Production
work requires a subsequent agreed vision.
