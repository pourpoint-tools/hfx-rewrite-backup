# HFX 0.4.0 river data and GRIT delivery

Finish HFX 0.4.0 so rivers are stored as connected features in their own right,
with snapping as one use of that data. Deliver a lean normative Markdown contract
and a verified public GRIT bundle using it. Specification alone is not completion.

Related HFX issue: https://github.com/pourpoint-tools/hfx/issues/17

This standalone vision records the confirmed discovery outcome. It expands #17's
original format-only scope to include full GRIT production and publication. TDX
conversion remains a separate future effort. The old Rust implementation and
previously compiled bundles are evidence, not compatibility requirements.

## Stored data model

Use the same basic structure for river granularity as for catchment granularity:

- Positive dataset-local `int64` HFX IDs. They may reuse source IDs but need not.
  Preserve source identity and its namespace independently. Do not assume IDs are
  row numbers, globally unique across datasets, or stable across independent versions.
- A nonnegative `int16` `level`, with smaller numbers for coarser tiers.
- A nullable `int64` `parent_id` identifying the larger river feature of which a
  finer feature is a constituent part, at a strictly coarser available river level.
- River geometry, spatial bounds, and additional typed source attributes.
- Directed connectivity within each river level, separate from parent membership.
  One model must preserve both single-downstream and branching networks, including
  reconvergence. Do not force branching fabrics into trees.
- Explicit river-to-drainage-unit associations, separate from river parents and
  flow edges. Multiple rivers may associate with one polygon; a river may have no
  polygon. Do not derive hydrological association merely from spatial intersection.

GRIT segments form a coarser river tier and their constituent reaches a finer tier.
A one-tier fabric does not need invented parents. River tiers do not automatically
correspond to catchment tiers. Stream order is an attribute, not a hierarchy level.
Source-declared constituent membership does not require exact geometric equality
between a parent line and the union of its child lines.

Keep geometry in EPSG:4326 under the vector contract. Support the observed
LineString and MultiLineString inputs. Do not silently reverse, simplify, clip or
repair source geometry. Document any necessary transformation, including
reprojection from original projected inputs. Flow connectivity must not depend on
assuming the first vertex is upstream. Finalize any orientation declaration needed
for unambiguous interpretation without designing the consumer runtime.

HFX defines minimum structural fields, not an identical complete attribute schema
for every source. Preserve useful source attributes, types, nulls and meanings.
Retain native stream-order definitions and distinguish partitioned drainage area,
mainstem-following area, local area and upstream polygon-union area. Do not relabel
one as another or turn source order into a universal snapping weight.

## Dataset-defined meanings

Allow a dataset to declare a typed categorical column with its own code-to-meaning
dictionary. HFX standardizes how the dictionary is represented and linked to the
column, not a fixed vocabulary or cross-dataset equivalence of codes or labels.
Specify column binding, physical type, code meanings and null interpretation.
This is semantic metadata, not merely Arrow dictionary compression.

Use the same mechanism where useful to describe river and catchment levels. For
`level`, dataset descriptions supplement the HFX ordering rule; they do not replace
parent references or connectivity. A dataset-defined `termination_kind` is an
example, not a mandatory closed set of outlet categories. Preserve available
source termination explanations. Missing links alone do not prove natural outlets.
Distinguish source terminals from edges cut by an experimental or published subset.

The review may clarify existing catchment-level metadata and shared conventions.
It does not authorize a speculative generic relationship framework or require
rewriting unrelated catchment and raster storage.

## Physical storage and small experiment

Reuse the selected HFX 0.4.0 vector approach:

- River attributes and WKB together in byte-budgeted, compressed Arrow IPC files.
- An ID-sorted lookup addressing record batch and row, plus a small directory for
  selective ID lookup without scanning worldwide river IDs.
- Separate graph data readable without river geometry or all source attributes.
  The existing Parquet graph with `id`, `level`, and `upstream_ids` is the starting
  point, including support for a river feeding multiple downstream neighbors.
- Root-manifest artifact discovery, fingerprints, lookup binding, immutable data
  artifacts and consistent range-read identity checks.

Reuse existing batch, compression and access lessons. Adapt catchment-specific
metadata and source-Parquet-specific production instructions where needed rather
than inheriting them accidentally. Choose exact artifact names and manifest fields
as ordinary engineering work. Do not restart a storage-format competition without
a measured problem. Spatial candidate discovery also needs accessible bounds;
the ID lookup alone does not supply spatial selection.

First convert small original examples, then read them back independently. Show
source fields beside HFX records and account for retained, changed and omitted
information. Verify IDs, relationships, nulls, attributes and geometries. Compare
exact exported WKB where no transformation is needed; independently verify and
record necessary source-format or CRS transformations.

Run an instrumented selective remote-read demonstration on an approved isolated
experimental prefix, preferably Hetzner, then verify the production publication on
public R2. Report requests, received body bytes, selected versus fetched batches,
preparation, first access and repeated access. Do not call these measurements full
delineation performance. No numerical latency threshold has been agreed. A tiny
sample can verify addressing and fidelity but cannot prove global-scale performance.
Preserve existing objects; obtain approval for a new write destination before upload.

Use small strongly typed Python production and verification scripts, with uv,
Ruff, ty and focused test-first checks. Reuse existing useful code. Do not build a
general compiler, source-adapter framework, validator CLI or supported reader library.

## Source evidence and remaining engineering work

The following examples were read from original data during discovery. Preserve a
small reproducible evidence record during implementation; do not rely on the
conversation or treat local experimental files as the normative specification.

### HydroRIVERS

HydroRIVERS v10 contains `10000003` and `10000004` flowing into `10000009`.
All three reference finest-level HydroBASINS unit `1120031210`. A source selection
by `MAIN_RIV=10000009` returned those three rows. They need one river level and
no river parents. Preserve `ORD_STRA`, `ORD_CLAS` and `ORD_FLOW` separately.
The observed source geometry type is MultiLineString. `NEXT_DOWN=0` and
`ENDORHEIC=0` support a source-described ocean-draining terminal, not an independent
coastline certification. Original basin target rows and nesting were not verified.

The hosted HydroBASINS bundle contains HydroBASINS standard without-lakes v1c,
Pour Points v1 and HydroRIVERS v10. Its existing snap artifact discarded native
river identity and connectivity; it is not sufficient source material for restoring
those fields. The original user-supplied river archive is
`~/Downloads/HydroRIVERS_v10.gdb.zip` (SHA-256
`c0938490d168c6aafdcb62e92a9a1e9b7e9188d20f91698a84d15afdbb5aa262`).
Read `~/Downloads/HydroRIVERS_TechDoc_v10.pdf` alongside it. Preserve the source
license and redistribution restrictions; do not publish HydroRIVERS samples on
public R2 merely because GRIT is hosted there.

### GRIT

Original v1.0 SP segment and reach archives from
[Zenodo record 17435232](https://zenodo.org/records/17435232) passed their published
MD5 checks. The [v1.0 product README](https://zenodo.org/api/records/17435232/files/README.pdf/content)
is essential alongside the earlier [paper](https://doi.org/10.1029/2024WR038308).

A real BORN-domain example is:

```text
70010735 → {70010734, 70000197} → 70008597
```

The four segments have 21 constituent reaches. Segment `70010735` contains
`70106320 → 70106321 → 70106322 → 70106323`; the two branches contain
`70106319` and `70000097`; segment `70008597` contains `70078460` through
`70078474`. Original reach edges reproduce the same split and reconvergence.
Each selected reach has one source `segment_id`; all selected internal edges were
reciprocal and consistent with endpoint node IDs. External source references were
retained as sample boundaries, not rewritten as outlets. Source ID reuse in this
sample does not establish worldwide collision freedom across tiers or feature types.

All four segment geometries differ from their constituent reach unions, with
measured native-plane Hausdorff distances of roughly 15–25 m. Preserve the declared
membership and both geometries rather than impose an exact-union invariant.

Original node `70000364` is a bifurcation and `70000365` a confluence. Node layers
also carry identity, type, direction/continuity diagnostics and other attributes.
A lines-only mapping can lose this information. Determine the smallest explicit
way to preserve useful node identities, relationships and attributes before fixing
the contract: a typed node table is a concrete option, not a preselected universal
node framework. Preserve source node layer/tier identity, point geometry, line endpoint/incidence
relationships, available cross-tier node references, attributes and nulls. Verify
those facts in the worked example, without requiring invented
nodes in sources that do not supply them. Do not silently project or discard node
information. Account for any intentional omission and raise material information-loss
trade-offs with the maintainer.

The shared river `catchment_id=70000129` identifies a component catchment, not
each river's local polygon. Acquire and inspect small original catchment cases
before finalizing association fields. Product documentation describes matching
segment/reach polygon IDs and reach-to-segment membership, but those polygon rows
were not inspected during discovery. Verify matched, missing, duplicate and unmatched
IDs, including a coastal/sink polygon-only case. Check whether nesting, disjointness
and outlet assumptions in the existing catchment contract hold for the sampled
source polygons; record simplification and anomalies rather than inventing exact
geometric equality. Verify cardinality, polygon availability and level semantics.
Do not blindly inherit previous adapter graph/area transformations.
Inspect actual cycle/continuity flags and distinguish preservation from hydrological
certification. Reconcile any observed cycles with the current tree/DAG requirements:
an anomaly note alone does not establish conformance. Do not silently delete or
redirect source edges to satisfy the contract. If originals contradict a required
invariant, investigate and make the contract decision explicit before production;
raise consequential scope or semantic trade-offs with the maintainer.

### TDX comparison and limits

The original `~/Downloads/TDX_streamnet_2020071190_01.gpkg` is 3,697,729,536 bytes,
with layer metadata dated 2023-01-26. Observed links include `1/2 → 2754` and
`2754/2755 → 5507 → 12388`. They need one river tier and no parents. Source IDs
require processing-basin namespacing in a multi-basin compilation. All seven tested
internal edges had native coordinate order opposite to downstream flow.
`LINKNO=1104039` has `DSLINKNO=-1`, but its precise termination category is not
established. Preserve that uncertainty.

The matching basin download failed. No original polygonless-river example was
verified; `WSNO` is not proof of polygon presence. The format must permit absent
associations and test that behavior with an explicitly labeled fixture. Do not
claim that fixture proves an original TDX case. Original TDX polygon absence needs
the complete applicable polygon `streamID` set and remains for the later TDX effort;
it need not block GRIT. MERIT Hydro and MERIT Basins remain comparison evidence,
not ingestion targets.

Local research reports, source records and reusable small samples are under
`/tmp/hfx17-source-examples/`: `hydro.md`, `grit.md`, `tdx.md`, the corresponding
`*-records.json`, `hydro-sample.arrow`, and `grit-source-sample-wgs84.json`.
These are temporary working evidence, not guaranteed durable inputs. If absent,
reacquire from the identified originals. Keep bulk and credentials outside Git;
retain compact provenance and reproduction information in the implementation.

## GRIT production and publication

The existing public bundle is
`https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0/`.
It is an earlier delivery of the unfinished 0.4.0 design, not a requirement to retain
the old snap-target model. Finish format version **0.4.0**, not 0.5.0.

Return to original GRIT inputs for river information discarded by existing
normalization. Reuse existing catchment or raster artifacts only after establishing
that their semantics and declarations conform to the finalized contract. Do not
reprocess unchanged rasters merely because river storage changes. Define the
manifest treatment of old snap artifacts explicitly; do not preserve redundant
snap copies or change their meaning accidentally. Source normalization remains
outside the engine, regardless of who writes the wrangling code.

Use original GRIT v1.0 vectors from [Zenodo record 17435232](https://zenodo.org/records/17435232):
regional segment and reach GeoPackages (each including line and node layers),
segment and reach catchments, component catchments, and the product README and
license. The South Pacific segment/reach pair has already been downloaded and
checksum-verified as described above. The listed EPSG:8857 archives across those
five vector products total approximately 21.4 GB compressed. This is a source
transfer estimate, not an estimate of extracted data or peak working disk. Verify
release identities and archive checksums when acquiring the remaining regions.
Download required originals directly to the production server, not through the
maintainer's laptop. Existing compiled snap artifacts cannot restore discarded
source fields. No raster download or rewrite is planned; preserve the existing
raster data and adjust publication references only as required.

Use a temporary Hetzner **CPX62 in Falkenstein (`fsn1`)** for full GRIT production;
keep small development tests local. The selected configuration is x86 with 16
shared vCPUs, 32 GB RAM and 640 GB local SSD, initially without an attached volume.
The 2026-10-12 CLI inspection reported availability and a net server rate of
EUR 0.2083/hour, approximately EUR 5/day before tax. The maintainer accepted that
approximate daily cost. Recheck availability and pricing before provisioning; do
not silently substitute another server type. The active hcloud context was
`pourpoint`, with no servers or volumes at inspection.

Provision when the production scripts and small experiment are ready, not during
vision authoring. Before provisioning, estimate extracted inputs, output, temporary
disk, RAM, transfer and duration; process incrementally and monitor free space.
Confirm the total budget and provisioning approval with the maintainer. EUR 30 was
proposed as a compute budget but has not been approved. Any such budget is an
operational limit, not a provider-enforced spending cap; object storage/API and
other charges are separate. Delete this effort's server after successful public
verification and preservation of receipts, subject to the failure-preservation
rules below. No server has been provisioned by this vision publication.
The AWS CLI profiles `upstream-r2` and `hetzner-pourpoint` were found locally;
verify current bucket-specific permissions, endpoint and destination rather than
assuming profile presence grants write access. Account-wide R2 bucket listing was
denied during discovery. Never expose credentials in code or reports.

Obtain approval for the exact publication destination before writing. Prefer a new
immutable delivery prefix that still declares `format_version=0.4.0`. Preserve
existing bundles and their valid reads. This vision does not authorize replacing
objects under the existing prefix or changing a public entry point without an
approved safe publication plan. Publish verified artifacts first and the manifest
last. Check uploaded full identities and actual public selective reads against the
verified output. Retain consistent-manifest and object-version guarantees.

Full production verification must establish source-to-HFX fidelity across delivered
records, complete ID/lookup coverage, valid parent and flow references, association
semantics, and preservation of declared source attributes and geometry. Keep this
bounded in memory and separate from consumer startup. Document inherited anomalies
rather than silently repairing source hydrology. Retain GRIT CC BY-NC 4.0,
attribution, source versions, transformations and caveats.

After successful upload and public verification, clean up only this effort's
approved disposable bulk and compute resources. Preserve user-supplied downloads,
pre-existing data and failed outputs needed for diagnosis. Retain compact delivery
receipts with final URL, manifest/artifact identities, counts, verification results,
commands and cleanup status.

## Deliverables and boundaries

Delivery is complete when:

1. Lean normative Markdown describes the finalized stored model and interoperable
   artifact layout, with experiment and production notes kept separate.
2. Small source-based examples demonstrate hierarchy, branching, retained meanings,
   geometry and selective remote reads; limitations are explicit.
3. The complete GRIT bundle conforms, passes full production/upload verification,
   and is readable selectively at the approved public R2 destination.
4. Existing publications remain readable, and receipts and cleanup are recorded.

Do not implement runtime representation, readers, API changes or engine behavior
in `../pourpoint`. Useful measured findings may be posted as evidence comments on
[Pourpoint #36](https://github.com/pourpoint-tools/pourpoint/issues/36), separating
observations from recommendations. This permission does not authorize changing
its code, publishing a runtime design, changing its Program, or marking it complete.
The current Pourpoint reader is not presumed compatible with the revised contract.

After GRIT succeeds, prepare a focused TDX handoff for a new session and dedicated
effort: the contract, reusable small production tools, known source mappings,
failed polygon acquisition and outstanding verification. Do not convert or replace
the hosted TDX bundle within this effort.
