# TDX HFX 0.4.0 private vector delivery

Produce and publish a verified vector-only TDX-Hydro bundle on the maintainer's
private Hetzner Object Storage: rivers from all 62 processing basins and catchments
from the 59 available polygon originals. Explicitly document the three missing
polygon sources. Delivery under this vision completes
[HFX #33](https://github.com/pourpoint-tools/hfx/issues/33); publication of this
vision does not complete it.

## Confirmed scope decisions

The maintainer accepts missing polygon originals for processing basins
`1020027430`, `5020049720`, and `6020006540`. Keep their original rivers and supplied
river connectivity. Do not exclude those rivers because polygons are unavailable.
Do not acquire these missing polygons as a prerequisite, repeat exhausted downloads,
or substitute processed datasets. This accepted coverage replaces the earlier
124-original and complete-worldwide-catchment requirements.

Record available and missing source coverage by domain and processing basin in
machine-readable provenance and the consumer documentation. Associations for these
three basins are unavailable, not evidence that their rivers naturally have no
catchments. Distinguish them from genuinely unmatched rivers within the 59 supplied
polygon sources. Do not invent polygons, associations or catchment connectivity.
The precise representation of this distinction is an implementation choice; make
its meaning unambiguous to consumers and verify it independently.

Lossless type harmonization is approved. Store catchment `streamID` consistently
as **int64**, widening the int32 source values exactly. Preserve values, nulls and
source identity; retain original per-source declarations in provenance and document
the conversion. Do not introduce separate int32/int64 columns. Other justified
lossless conversions may be made with explicit source mappings and independent
verification; changes that could alter values, precision, nulls or meaning still
require an explicit decision. Exact physical source width is not required for an
authorized lossless conversion. Geometry repair, polygon dissolves and connectivity
inference are not authorized by this type-harmonization decision.

There are no remaining known human decisions blocking this agreed scope. Full
production validation may expose new material conflicts; investigate those rather
than weakening checks silently.

## Verified resume state (2026-10-25)

The permanent private archive is
`s3://pourpoint-hfx/raw/tdx-hydro/NGA-TDX-Hydro-20230126/`.
Read `inventories/121-files.json`, not the older root inventory, for current coverage.
It contains all 62 river originals and 59 polygon originals totaling
**332,385,001,472 bytes**. A fresh name/size listing matched, and the cumulative
inventory was uploaded and read back byte-for-byte. Full content-readback evidence
comprises 66 reconciled earlier originals and 55 additional originals matching
historical SHA-256 and size; this was not a new full readback of all 121 files.
Preserve the raw archive permanently. Source license/attribution are retained in
`LICENSE.txt` and `NOTICE.txt`; private access is unchanged. Archive storage costs
are authorized separately from temporary compute.

All temporary servers, attached volumes and owned IPs from the acquisition/sample
run were removed and verified absent. **No VM or production job remains active.**
The heartbeat is paused; do not create a persistent goal. Earlier running-VM
instructions and archive-only handoffs are obsolete. Estimated cumulative temporary
cost including conservative prior/transfer reserves is **EUR 12.89**, not an invoice
or a reset budget. Reconcile retained resource/cost evidence before spending again.

Durable local evidence is under `~/.prime/agent/tdx-resume-20261024/`:

- `inventory-121.json`, `inventory-121-readback.json`, and
  `archive-listing-121.json` record the permanent archive snapshot.
- `production/metadata-final/` contains all 121 source schema/count records.
  The 62 river files have matching declarations and **15,940,505 rows**.
  Among 59 polygon sources, `1020018110` declares `streamID MEDIUMINT` (int32);
  the other 58 declare `INTEGER` (int64). The former also declares `POLYGON`
  rather than `GEOMETRY`; exact source WKB remains authoritative.
- `production/final-vm-evidence/` contains original/spatial verification receipts,
  topology results, timings, manifests, provenance and logs for the two samples.
- `resources-after-cleanup.txt` and `final-budget-estimate.json` record cleanup/cost.
- `preserved-partials/` retains eight failed archive partials (71,149,249,955 bytes)
  and two failed production-transfer partials (2,683,437,056 bytes), all copied with
  matching SHA-256. They are evidence, not complete originals or normalization inputs.

Credentials and bulk data stay outside Git. Preserve these local files and earlier
user evidence under `~/hfx-acquisition/` and `~/hfx-campaign-evidence/`. Prefer the
permanent archive for reproducible inputs. Sample outputs and the production copy
of the originals were removed with the VMs; reproduce from the archive when needed.
No global normalized TDX bundle has been published.

## Existing tools and remaining implementation

Reuse the merged tooling, not the old toolkit:
[#53](https://github.com/pourpoint-tools/hfx/pull/53) plural local associations,
[#54](https://github.com/pourpoint-tools/hfx/pull/54) represented domains,
[#55](https://github.com/pourpoint-tools/hfx/pull/55) original normalization/verifier,
[#56](https://github.com/pourpoint-tools/hfx/pull/56) authenticated access,
[#57](https://github.com/pourpoint-tools/hfx/pull/57) bounded verification windows,
and [#59](https://github.com/pourpoint-tools/hfx/pull/59) basin-local producer/verifier
workspace. Target `9db0e60143cefa3e3e923c2037f35bfcf6533f46` passed 216 tests both
locally and on production Linux, with independent review. Rerun current validation.

[TDX normalization](../../docs/v0.4.0/tdx-normalization.md) describes the existing
commands and paired-source inventory. It still requires matching schemas and paired
sources; those restrictions must be updated for the two confirmed decisions above.
The current producer rejects mixed int32/int64 `streamID` schemas. Implement the
lossless mapping and missing-polygon inventory/coverage semantics in the producer,
independent original verifier and relevant contract/docs. Keep the generic storage
layout lean; this is not authority for a new toolkit. Coordinate the actual consumer
contract explicitly with the separate
[Pourpoint #44](https://github.com/pourpoint-tools/pourpoint/issues/44) follow-up;
do not implement Pourpoint or imply current reader compatibility.

PR #59 bounds Python topology workspace by the largest basin, not a fixed RSS cap.
The independent verifier uses temporary SQLite for actual output relationships
(8 MiB cache, 4096-row ingest), while deriving expectations separately from original
sources. Global spatial numeric arrays still grow with feature count. Current tools
keep all supplied originals locally available through pre/post hashing; they do not
provide a per-basin artifact merge/rebase command. Size scratch and final output
storage accordingly rather than assuming one-basin laptop processing solves assembly.

Two complete pairs passed exact original-to-staging and full staging-to-spatial
verification with the merged tools:

| Basin | Catchments | Rivers | Flow edges | Local associations |
|---|---:|---:|---:|---:|
| `7020000010` | 331,263 | 331,386 | 327,808 | 331,263 |
| `1020018110` | 924,556 | 515,435 | 514,528 | 924,556 |

Polygonless rivers, distinct polygon identities sharing `streamID`, and finite
zero-length lines were preserved (149 and 87 zero-length rivers respectively).
These single-schema samples do not verify the new harmonized combined output or
missing-polygon behavior. Add independent multi-basin tests for both before production.

On a CPX62 (32 GB RAM), the larger pair normalized in 11m29s at about 1.35 GiB peak
RSS and independently verified in 9m07s at about 1.28 GiB. Its spatial build/full
verification peaked around 3.12 GiB. These are sample measurements, not global fit
or latency guarantees. A CCX43 request was rejected by the project's dedicated-core
quota; do not assume larger dedicated instances are available. Temporary attached
storage is available separately from VM size.

Read-only full within-basin topology screens checked 1,681,345 candidate pairs for
`7020000010` and 9,054,460 for `1020018110`, finding no positive planar intersection
area, invalid features, dateline flags or overlay errors. Source hashes stayed
unchanged. The larger screen took about 119 minutes. The method used original WKB,
disk-backed spatial candidates and a strictly positive computed degrees-squared
threshold, not an accepted numerical tolerance or geometry repair. This is evidence
for those two basins, not worldwide or cross-basin certification. Report actual
coverage and investigate any discovered conflicts; do not conflate full WKB fidelity
with exhaustive topology checking.

## Target format and source fidelity

Use the [spatial GeoParquet layout](../../docs/v0.4.0/spatial-layout.md): one
authoritative feature file per represented domain, artifact-bound ID lookups,
conservative spatial bounds, and separately addressable immediate forward/reverse
relationships. Declare `format_version: "0.4.0"`,
`representation: "spatial-geoparquet-adjacency"`, `representation_version: 1`.
The earlier [vector contract](../../docs/v0.4.0/vector-data.md) supplies field
meanings, not the target IPC feature layout. Amend relevant fidelity wording for
approved lossless harmonization rather than retaining contradictory requirements.

Use original release `NGA-TDX-Hydro-20230126` and pin actual acquisition hashes.
Preserve native attributes and nulls, subject only to documented approved lossless
mappings; preserve exact embedded WKB, geometry order, source identities and supplied
river connectivity. Keep processing-basin identity alongside native IDs, not as
invented hierarchy tiers. Verify polygon-to-river associations using original
`basins.streamID` and `streamnet.LINKNO` for the available polygon sources. Preserve
original area attributes separately from derived normalized areas. Missing downstream
links do not establish natural terminals. Catchment connectivity remains
`not_supplied`; do not infer outlets, nodes, upstream areas or graph contractions.
No raster files or references are part of this delivery.

The existing 0.3.0 bundle is comparison evidence, not a sufficient input. Its reduced
river model excludes polygonless reaches and contracts their connectivity; outlet
conventions also varied. Do not inherit polygon dissolves, coordinate clamps or
outlet assumptions. Historical [PR #221](https://github.com/CooperBigFoot/hfx/pull/221)
records a valid 55-of-62 partial 0.3.0 fabric; its absent set differs from this run.
That precedent supports truthful coverage reporting, not copying its semantics.

TDX source caveats include processing-boundary truncation, missing upstream area,
coastal extensions and dateline cuts. Preserve uncertainty. Do not silently reverse,
simplify, repair or discard source geometry. Any newly discovered conflict outside
the approved missing-coverage and lossless-type decisions requires investigation
and, if it changes intended fidelity, an explicit decision before publication.
Retain CC BY-SA 4.0 licensing, attribution and transformation notices. Private access
is the maintainer's requirement, not a claim that the license prohibits redistribution.

## Private publication and resources

Use AWS CLI profile `hetzner-pourpoint`, bucket `pourpoint-hfx`, endpoint
`https://fsn1.your-objectstorage.com`. Publish at a new unused TDX 0.4.0 prefix.
Preserve the old 0.3.0 publication, permanent raw archive and unrelated objects.
Do not enable anonymous access or change permissions. Verify authenticated
consumer-facing range reads.

The cumulative temporary infrastructure ceiling remains **EUR 50**, including
compute, attached storage, IPs, transfer and applicable taxes. Ongoing dataset
storage is outside it. Track spend and stop before exceeding the ceiling; this is
not a provider-enforced cap. The earlier EUR 12.89 estimate does not reset it.
Provision only needed temporary resources after reconciling actual current state
and pricing. Base sizing on source bytes and measured working memory, not GRIT costs.
One-basin local downloading/processing is authorized, subject to free disk/memory;
it does not prove global assembly fits the laptop. No hard latency target was chosen.
Keep credentials/private access details and bulk payloads out of Git.

## Verification and completion

Complete the accepted 62-river/59-polygon scope, not an unqualified worldwide
catchment claim. Independently verify every supplied source feature, native value,
null, identity, exact geometry, supplied connectivity and available association
against final output. For harmonized fields, prove exact values/nulls and approved
output type while retaining original declarations. Verify all available catchment
associations; separately prove missing-source basin coverage without fabricating
associations or misclassifying those rivers as naturally polygonless.

Verify final ID addresses, conservative bounds and complete immediate relationships
in both directions. Reconcile source basin rosters and feature counts, including
rivers from the three missing-polygon basins. Distinguish full checks from sampled
or selected-basin topology checks and disclose coverage limitations.

Stage only verified files. Verify complete uploaded artifact identities/full content
readback, publish the manifest last, and GET-verify its exact bytes. Check the
assembled bundle through authenticated full/projected records, known/absent IDs,
spatial discovery and relationship-to-record reads against trusted references.
Selected access tests do not replace full content verification. No publication on
failed verification. The [GRIT delivery record](../../docs/v0.4.0/grit-final-delivery.md)
is an operational example, not inherited proof or permission to delete prior objects.

Provide a concise consumer handoff stating actual stored contract, location,
verification evidence, approved type conversion, all three missing polygon basins,
and what missing coverage means for associations. Shared version numbers do not
establish Pourpoint reader compatibility. Preserve compact inventories, hashes,
receipts and cost/cleanup evidence. Remove this effort's new temporary servers,
volumes and owned IPs after verified delivery and confirm absence; preserve unknown
resources and unique unverified evidence.

Success is the valid, fully verified private vector bundle for the accepted coverage,
preserved prior publications/access policy, documented limitations and consumer
handoff, and accounted-for temporary-resource cleanup within the cumulative budget.
Only then close #33. Raw archival, sample verification or a partial implementation
PR alone does not complete this outcome.
