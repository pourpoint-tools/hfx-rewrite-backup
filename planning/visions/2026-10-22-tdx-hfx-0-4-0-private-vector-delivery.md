# TDX HFX 0.4.0 private vector delivery

Deliver a fully verified private TDX-Hydro vector bundle from **all 62 river and
62 polygon originals** of `NGA-TDX-Hydro-20230126`. The three previously unavailable
polygon originals have now been recovered. No intentionally missing source coverage
is accepted for this follow-on delivery.

## Completed delivery and new scope

The accepted 62-river/59-polygon delivery completed
[HFX #33](https://github.com/pourpoint-tools/hfx/issues/33), which is closed.
Its [consumer handoff](../../docs/v0.4.0/tdx-handoff.md) and
[verification receipt](../../docs/v0.4.0/receipts/tdx-delivery.json) remain the record
of that valid partial-coverage delivery: 15,940,505 rivers and 13,890,015 catchments.
Preserve its private prefix unchanged:
`s3://pourpoint-hfx/tdx/hfx-0.4.0/NGA-TDX-Hydro-20230126-20261026/`.

This revision defines a standalone full-coverage follow-on, not a reopening of #33
or a finding that its delivery was invalid. Earlier missing-source acceptance and
run-resume instructions no longer define the new target. Preserve the historical
handoff and receipt; provide a distinct full-coverage handoff and receipt when done.

## Originals and preparation

Preserve the permanent raw archive at
`s3://pourpoint-hfx/raw/tdx-hydro/NGA-TDX-Hydro-20230126/`.
Its `inventories/121-files.json` records the previous 62 river and 59 polygon
originals. Add the recovered polygons for `1020027430`, `5020049720` and `6020006540`
without replacing existing originals or inventory evidence. Produce a cumulative
124-original inventory with exact sizes and historical SHA-256 identities, reconcile
its basin/domain roster with the archive, and read back its complete uploaded bytes.
Verify full content identity of the three additions; retain and reconcile the full
content-verification evidence for the other 121 originals. A listing alone is not
content verification. Keep license and acquisition provenance alongside the archive.

Recovery evidence and originals are outside Git under
`~/.prime/agent/tdx-us-wget-experiment-20261026/`, with originals in `recovered/`.
Amazon and North Africa are locally preserved with matching historical hashes;
Australia has passed remote full size/hash verification, but its local copy and
verification are still pending at this draft's preparation. Do not treat an
in-progress local file as a complete source or remove its only verified remote copy.
Reconcile current preservation and resource state before starting production.
Earlier evidence remains under `~/.prime/agent/tdx-resume-20261024/`,
`~/hfx-acquisition/` and `~/hfx-campaign-evidence/`; failed partials are evidence,
not normalization inputs.

Read metadata from all 124 originals. Derive full feature and relationship counts
from verified metadata and data, not estimates or extrapolation from the previous
59 polygon sources. Inspect the three new schemas and source fidelity before
production. Reuse the current [normalization tools](../../docs/v0.4.0/tdx-normalization.md)
and approved catchment `streamID` int64 mapping, including exact widening of int32
values with original declarations retained. Investigate newly exposed material
schema or fidelity conflicts; do not silently coerce values or weaken checks.
Changes that could alter values, precision, nulls or meaning require an explicit
decision. Reversible execution choices belong to the implementing agent.

## Contract and fidelity

Use the existing [spatial GeoParquet layout](../../docs/v0.4.0/spatial-layout.md):
`format_version: "0.4.0"`, `representation: "spatial-geoparquet-adjacency"`,
`representation_version: 1`. Keep one authoritative feature file per represented
domain, artifact-bound ID lookups, conservative bounds and complete immediate
relationships in both directions. This is vector-only delivery, not a new toolkit.

Preserve every original feature, native attribute and null under approved lossless
mappings, exact embedded WKB and geometry order, basin-qualified native identities,
and supplied river connectivity. Preserve finite zero-length rivers and separate
polygons sharing `streamID`. Verify plural polygon-to-river associations against
original `basins.streamID` and `streamnet.LINKNO`; do not dissolve polygons or drop
polygonless rivers. All 62 basins now have supplied polygon coverage. Distinguish
actual unmatched rivers from missing input; no basin may be marked unavailable to
make this delivery pass. Retain the existing coverage field and its meanings.

Keep original area attributes distinct from derived areas. Processing basins are
not invented hierarchy tiers. Missing downstream links do not establish natural
terminals. Catchment connectivity remains `not_supplied`: no inferred graphs,
outlets, nodes, upstream areas, geometry repair, coordinate clamps or graph
contractions. The old 0.3.0 bundle is evidence, not an input. Preserve source caveats
about boundary truncation, missing upstream area, coastal extensions and dateline
cuts, and retain CC BY-SA 4.0 attribution and transformation notices.

## Resources and budget

The ceiling is **CHF 50 cumulative temporary infrastructure cost**, not a new
CHF 50 allowance. Include compute, temporary attached storage, IPs, transfer and
applicable taxes. Ongoing retained dataset/object storage is excluded. The earlier
delivery estimate was approximately EUR 21; the subsequent experiment raised the
conservative cumulative reservation to approximately CHF 28.30 before the small
Australia retry. These are planning estimates, not invoices or live exchange quotes.
Reconcile all prior costs, retry cost, active resources and current pricing before
provisioning, retain a conservative reserve, and stop before exceeding the ceiling.

Validate an affordable execution and storage plan against measured memory, scratch
space and time. Basin-local producer/verifier workspace does not bound global
spatial numeric arrays or prove laptop assembly fits. The existing tools require
originals locally available for pre/post hashing; do not assume a per-basin merge
command exists. Previous successful delivery is useful sizing evidence, not a
full-coverage fit guarantee. Keep credentials and bulk payloads outside Git.

## Verification, private publication and handoff

Independently verify every original feature, value/null, source identity, exact
geometry, supplied flow edge and association against normalized staging, including
the approved type mapping and original declarations. Then fully verify final
spatial records, ID addresses, conservative bounds and immediate forward/reverse
relationships. Reconcile all 62 paired basins and actual counts. No publication
on failed verification; report and investigate conflicts rather than omitting data.

Use a **new unused private prefix** in bucket `pourpoint-hfx`, through AWS CLI
profile `hetzner-pourpoint` and endpoint `https://fsn1.your-objectstorage.com`.
Preserve prior publications, the raw archive and unrelated objects. Do not enable
anonymous access or change ACLs or other permissions. Upload only verified artifacts,
perform full authenticated content size/hash readback, publish the manifest last,
and GET-verify its exact bytes.

Check authenticated full/projected records, known/absent IDs, spatial discovery,
and relationship-to-record reads in both directions against the verified local
bundle, explicitly covering all three recovered basins. Selected consumer probes
do not replace full content verification. Full WKB fidelity is not worldwide
polygon-topology certification; distinguish full checks from the earlier two-basin
overlap screens and state actual topology-check coverage.

Provide a concise new handoff with the exact private location and stored contract,
all-62-basin coverage, measured counts, hashes and verification receipts, approved
mapping, limitations and cost/cleanup evidence. Update current normalization guidance
to distinguish the full-coverage target from the historical partial delivery without
rewriting historical evidence. Coordinate consumer changes through
[Pourpoint #44](https://github.com/pourpoint-tools/pourpoint/issues/44); shared version
numbers and HFX probes do not establish Pourpoint compatibility or authorize its
implementation.

After data verification, refresh the Desktop Cartopy map from the verified
full-coverage data. Identify its source bundle and coverage; a visualization is not
verification evidence for feature fidelity or topology.

Preserve compact inventories, hashes, reports and unique recovery evidence. Remove
this effort's temporary servers, volumes and owned IPs only after durable data and
evidence preservation; verify their absence and account for final cumulative cost.
Preserve unknown resources. Success is the independently verified private
124-original delivery, new consumer handoff and refreshed full-coverage map, with
prior publications/access policy preserved and cleanup completed within budget.
Do not reopen or close #33 again as part of this follow-on.
