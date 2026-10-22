# TDX HFX 0.4.0 private vector delivery

Produce and publish a valid worldwide, vector-only TDX-Hydro bundle in the final
HFX 0.4.0 layout on the maintainer's private Hetzner Object Storage. Use temporary
Hetzner compute for bulk work. Delivery under this vision completes
[HFX #33](https://github.com/pourpoint-tools/hfx/issues/33); publishing this document
does not complete the issue or start production.

## Target format and scope

Use the finalized [spatial GeoParquet layout](../../docs/v0.4.0/spatial-layout.md):
one authoritative GeoParquet feature file per represented domain, artifact-bound
ID lookups, conservative spatial bounds, and separately addressable immediate
forward/reverse relationships. The manifest declares `format_version: "0.4.0"`,
`representation: "spatial-geoparquet-adjacency"`, and `representation_version: 1`.
The earlier [vector contract](../../docs/v0.4.0/vector-data.md) supplies field meanings,
not the target IPC feature layout. The [TDX handoff](../../docs/v0.4.0/tdx-handoff.md)
remains source evidence; its IPC production advice is superseded by this target.

Deliver original NGA TDX rivers and catchments across all 62 processing basins.
Preserve native fields, types, nulls, source identities, geometry order and supplied
connectivity. Keep processing-basin identity alongside native IDs; the basins are
source partitions, not invented hierarchy tiers. Represent all source rivers,
including those without a represented catchment, rather than reducing rivers to
snapping aids. Verify polygon-to-river associations from original identities.
Do not invent source nodes, tiers, outlets or relationships merely to match GRIT.
No raster files or raster references are part of this delivery.

This is a TDX normalization and publication effort, not another layout study,
hydrological repair project, or general toolkit. Pourpoint implementation is out
of scope. Provide a concise consumer handoff with the actual stored contract and
verification evidence; shared version numbers do not establish reader compatibility.

## Original-source fidelity

Reacquire the original NGA vector pairs as needed, using release
`NGA-TDX-Hydro-20230126` as the identified source baseline. Pin actual acquisition
identities and retain provenance. Establish source schema, CRS, area units,
relationships and geometry behavior before scaling. Source `basins.streamID` and
`streamnet.LINKNO` provide the association evidence; verify complete coverage,
duplicates and unmatched identities rather than assuming every river has a polygon.
Preserve original area attributes separately from derived normalized areas.

The existing 0.3.0 bundle is comparison evidence, not a sufficient normalization
input. Its reduced river model excludes polygonless reaches and contracts their
connectivity. Historical delivery also mixed earlier and corrected outlet
conventions. Later corrective code does not itself prove a corrected publication.
Do not carry those losses or outlet assumptions into the new bundle.

Relevant historical evidence lives in the deprecated `CooperBigFoot/hfx` repository:
[pristine NGA source decision](https://github.com/CooperBigFoot/hfx/blob/c18a8a6a115e2045080d8752279d39db2b9b29b6/docs/decisions/2026-07-21-tdx-hydro-pristine-nga-source.md),
[adapter notes](https://github.com/CooperBigFoot/hfx/blob/c18a8a6a115e2045080d8752279d39db2b9b29b6/adapters/tdx-hydro/README.md),
and [global delivery history](https://github.com/CooperBigFoot/hfx/issues/108).
These are evidence, not compatibility requirements. Old ID numbering, polygon
dissolves, coordinate clamps and outlet inferences require fresh justification
against the current contract; do not inherit them silently.

TDX source caveats include processing-boundary truncation, missing upstream area,
coastal extensions and dateline cuts. Missing downstream links do not classify
natural terminals. Preserve uncertainty and document necessary transformations;
do not silently reverse, simplify, repair or discard source geometry. Any source
anomaly that conflicts with the contract requires an explicit decision before
production proceeds, not a relaxed invariant hidden in an anomaly report.

Retain applicable attribution, licensing and transformation notices. The inspected
original NGA license is CC BY-SA 4.0, not GRIT's CC BY-NC license. Private publication
is the maintainer's explicit access requirement, not a claim that CC BY-SA itself
prohibits large-scale redistribution.

## Private publication and temporary infrastructure

Use the existing `hetzner-pourpoint` AWS CLI profile and `pourpoint-hfx` bucket at
`fsn1.your-objectstorage.com`. Publish to a new, unused TDX 0.4.0 prefix. Preserve
the existing 0.3.0 publication and unrelated objects. Keep access private and
available through the maintainer's existing authorized access arrangements;
do not enable anonymous access or change permissions. Verify authenticated
consumer-facing range reads rather than requiring public HTTP access.

The approved temporary infrastructure ceiling is **EUR 50**, interpreted from
“50 bucks again” as the same currency used for GRIT. Include estimated compute,
attached storage, IPs, transfer and applicable taxes; ongoing dataset storage is
outside this ceiling. Track spend and stop before exceeding the ceiling. It is
not a provider-enforced spending cap.

Provision new temporary Hetzner compute; the prior GRIT VM was removed. Select
machine and storage sizes from TDX source sizes and meaningful sample measurements,
not GRIT's final cost or capacity assumptions. Favor economical completion; no
hard deadline or latency target was selected. Keep bulk data off the maintainer
laptop and credentials and bulk data outside Git. Monitor memory, disk and spend;
preserve diagnosis evidence if a run cannot safely continue.

## Verification and completion

Use the [GRIT delivery workflow](../../docs/v0.4.0/grit-final-delivery.md) as an
operational example, not inherited proof of TDX fidelity or permission to delete
old publications. Reuse suitable format machinery without pretending GRIT-specific
source mappings are TDX mappings. Exact VM sizing, grouping parameters, native
field mappings and the new prefix are implementation choices within this contract.

Before publication, independently verify complete source-to-output feature
coverage, native values/types/nulls, identities, geometry fidelity under documented
necessary transformations, associations and supplied connectivity. Verify final
ID addresses, conservative bounds and complete immediate relationships in both
directions against their declared meanings. Distinguish full checks from sampled
geometry/topology checks and preserve source limitations.

Stage verified files, verify complete uploaded artifact identities/readback, and
publish the manifest last. Check the final assembled bundle through authenticated
access, including representative projected/full records, known and absent IDs,
spatial discovery and relationship-to-record reads. Report observed access behavior
without inventing latency guarantees. Selected reads do not replace full content
verification. No publication on failed verification.

Retain compact source inventories, hashes, verification receipts, access results
and cost/cleanup evidence. After verified delivery, remove this effort's temporary
VM, attached storage and owned IPs, and verify each is absent. Do not delete unknown
objects or resources. Report any retained resources and ongoing costs honestly.

Success is a valid, fully verified global vector-only bundle at the reported private
Hetzner location, preserved prior publications and access policy, a concise consumer
handoff, and accounted-for temporary-resource cleanup within budget.
