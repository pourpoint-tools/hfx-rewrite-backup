# TDX HFX 0.4.0 private vector delivery

Produce and publish a valid worldwide, vector-only TDX-Hydro bundle in the final
HFX 0.4.0 layout on the maintainer's private Hetzner Object Storage. Use temporary
Hetzner compute where needed; one-basin local work is also authorized below.
Delivery under this vision completes
[HFX #33](https://github.com/pourpoint-tools/hfx/issues/33); publishing this document
does not complete the issue or start production.

## Resume state: verified raw archive (2026-10-23)

Raw acquisition is partly complete; global HFX production and delivery are not.
The permanent private archive is
`s3://pourpoint-hfx/raw/tdx-hydro/NGA-TDX-Hydro-20230126/`, accessed with the
profile and endpoint below. Its cumulative inventory is `inventories/66-files.json`;
root `inventory.json` and `verification.json` describe only the initial 12-file
snapshot. Later per-file/addition receipts are under `receipts/`. Read the cumulative
inventory before reacquiring anything.

- All **62 original river GeoPackages** are archived.
- Four original polygon GeoPackages are archived: `2020003440`, `4020050470`,
  `6020000010`, and `7020000010`. **58 polygon files remain missing.**
- The 66 files total **99,949,490,176 bytes**. Every local source SHA-256 and full
  archived-object readback SHA-256 matched retained historical acquisition hashes.
  The final remote file-name/size inventory and cumulative inventory readback matched.
  These are original files, not a delivered HFX bundle or proof of normalized fidelity.
- Preserve this raw archive permanently. Temporary-compute and derived-bundle cleanup
  must not delete it. Deletion needs explicit maintainer authorization. Private access
  is unchanged; this is a retention rule, not an object-lock/WORM guarantee. Source
  license and attribution are stored in `LICENSE.txt` and `NOTICE.txt`. Ongoing raw
  storage costs are authorized separately from temporary compute.

The river workaround is the public
[ArcGIS TDX Hydro collection](https://www.arcgis.com/home/group.html?id=117d140bc2d042b78370d0c3ab99d054).
Its file-item `/data` endpoints support byte ranges. Newly acquired river files
matched historical NGA hashes in full, despite some mirror filenames using a
`_02` suffix. Per-file source URLs are in the cumulative inventory. No original
polygon mirror was found; do not substitute processed GEOGLOWS or WikiWatershed data.
NGA full downloads repeatedly disconnected on German/US compute and the laptop;
both tested NGA server addresses ignored byte ranges. A faster address and session
cookies did not resolve this. Historical downloads using the same URLs succeeded;
the reset cause remains unknown, not proof that all polygon files are unavailable.
[WikiWatershed #14](https://github.com/WikiWatershed/global-hydrography/issues/14)
asks for unchanged originals or another source. Check for replies before repeating
research. NGA's published contact is `SFNAGGeoscienceApplications@nga.mil`; no email
was sent. External correspondence still needs maintainer authorization.

### Implemented tooling and remaining verification

The contract amendment and tools are merged: [#53](https://github.com/pourpoint-tools/hfx/pull/53)
(plural local associations), [#54](https://github.com/pourpoint-tools/hfx/pull/54)
(represented domains), [#55](https://github.com/pourpoint-tools/hfx/pull/55)
(original normalization/verifier), [#56](https://github.com/pourpoint-tools/hfx/pull/56)
(authenticated reads), and [#57](https://github.com/pourpoint-tools/hfx/pull/57)
(bounded verification windows). See [TDX normalization](../../docs/v0.4.0/tdx-normalization.md)
for commands and inventory shape; reuse these tools rather than rebuilding them.
The merged target passed 199 tests with the vector-production and raster-experiment
optional groups. Rerun current validation before continuing.

One complete original pair, `7020000010`, passed independent original-to-staging
and full staging-to-spatial verification: 331,263 catchments, 331,386 rivers,
327,808 flow edges, and 331,263 local associations. Its 123 polygonless rivers and
149 finite degenerate source lines were retained. No polygon overlap check was
performed. This sample does not establish global conformance. Catchment connectivity
is `not_supplied`; no contracted catchment graph, invented nodes, or outlet inference.
Plural local associations preserve separate polygon identities; existing published
GRIT data need no rewrite. [Pourpoint #44](https://github.com/pourpoint-tools/pourpoint/issues/44)
is the separate reader/runtime follow-up, not proof of reader compatibility.

On an 8 GiB CPX32 sample VM, normalization took about seven minutes and peaked at
926 MiB RSS; original verification took about six minutes and peaked at 742 MiB.
The revised spatial verifier checked the same unchanged output in about six minutes
with 1.91 GiB peak RSS. Catchment source decoding still amplified logical input by
18 times. These are sample measurements, not global sizing or latency guarantees.
Global numeric workspace, all-basin schema/anomaly checks, polygon topology coverage,
final assembly, private publication, authenticated consumer checks and handoff remain.

Local evidence for this session is under
`~/.prime/agent/tdx-source-sample-20261022/` (source/verification receipts, transport
research and archive inventories). Acquired river originals and per-file receipts
are under `~/hfx-acquisition/tdx-20230126/`. Twelve earlier originals remain under
`~/hfx-campaign-evidence/2026-08-07-close-the-seven-basin-coverage-gap/off-vm/acquired-source/`.
Preserve these user files. The deprecated checkout `../deprecated/hfx` and that
historical evidence root contain original acquisition hashes. Prefer the durable
private archive over depending on local session files. Temporary VM sample outputs
were removed with the VMs; reproduce them from archived originals and merged tools.
All temporary servers, volumes and owned IPs from this session were removed; no
compute or transfer remains active. Reconcile retained cost evidence against the
EUR 50 total before provisioning again; the earlier conservative estimate was under
EUR 1.72 before the final short-lived retry VM, not a provider invoice or a reset budget.

Next: acquire and permanently archive the missing polygons, verify paired source
identities and anomalies, then normalize/verify the full collection and deliver the
private spatial bundle. Do not close #33 based on the raw archive alone.

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

Provision new temporary Hetzner compute only when needed; prior VMs were removed.
Select machine and storage sizes from TDX source sizes and meaningful sample
measurements, not GRIT's final cost or capacity assumptions. The maintainer later
authorized downloading and processing one basin at a time on the laptop, followed
by verified archival/upload. This supersedes the earlier no-local-bulk restriction.
Check current free disk and memory first; keep originals until their permanent
archive copies are verified. Local permission does not establish that global
assembly fits the laptop. Favor economical completion; no hard deadline or latency
target was selected. Keep credentials and bulk data outside Git. Monitor memory,
disk and spend; preserve diagnosis evidence if a run cannot safely continue.

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
