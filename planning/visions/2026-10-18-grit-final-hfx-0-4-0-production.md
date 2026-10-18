# GRIT final HFX 0.4.0 production

Publish the complete global GRIT dataset under the finalized working HFX 0.4.0
layout so Pourpoint can finalize its reader and runtime representation.
Effort: [HFX #43](https://github.com/pourpoint-tools/hfx/issues/43).

## Settled direction

Use spatially organized GeoParquet for catchments, rivers and source nodes, with
one authoritative feature representation per domain. Keep attributes independently
projectable and preserve exact delivered WKB, native types, nulls, source metadata,
identities, tiers, relationship meanings and provenance. GRIT remains CC BY-NC 4.0.
This is a physical-layout revision, not hydrological repair or reinterpretation.

Publish producer-prepared ID access, conservative spatial discovery and separately
addressable immediate forward/reverse relationships. Keep flow, hierarchy, directed
node incidence, cross-tier correspondence and local/component catchment associations
distinct, including unknown and not-supplied values. Spatial bounds produce
candidates, not exact intersection results. Consumers execute traversal and own
query workspace; do not publish transitive closures or require private caches.

Prioritize time to useful spatial results on first access while retaining effective
large-request, bulk and reuse paths. Accept the measured clustered-ID compromise.
Do not add duplicate full feature representations or reopen a broad format study.

The existing R2 0.4.0 publication is a working design, not a compatibility promise.
The final destination is `grit/hfx-v0.4.0/` on the existing public R2 host,
`https://basin-delineations-public.upstream.tech/`. Replace its superseded working
vectors after successful verification. This supersedes #43's earlier requirement
to publish at a new immutable prefix and preserve every old vector publication.
The separate `grit/hfx-v0.4.0-rivers-2026-10-12/` bundle is outside cleanup scope.

Keep `grit/hfx-v0.4.0/aux/d8/flow_dir.tif` and
`grit/hfx-v0.4.0/aux/d8/flow_acc.tif` unchanged at their existing URLs. Preserve their
exact identities, declarations and retention commitments. Do not download them in
full, copy, move, rewrite or regenerate them for this vector production run.
Verify public range and decoded-window access against retained raster evidence.

## Contract and production work

Make the revised stored contract explicit in the repository: feature organization,
ordering/grouping, ID address conventions, spatial and relationship access,
metadata discovery and artifact identity bindings. The shared `0.4.0` string does
not establish compatibility with existing readers. Coordinate the actual contract,
not a presumed version match, with Pourpoint.

Leave reversible file sizing, ordering, group boundaries and index encodings to
implementation. Neither experimental row cap nor Morton ordering is a production
requirement. Bind access structures to the actual final artifacts, not old IPC
hashes or experimental address declarations. Keep the layout portable to S3 and
other range-readable object stores. Prefer native formats and minimal supporting
code rather than a new general toolkit.

Use the [physical-layout findings](../../experiments/data_interface/PHYSICAL_LAYOUT.md)
and [#35 discussion](https://github.com/pourpoint-tools/hfx/issues/35) as evidence.
River GeoParquet has full preservation evidence; catchment/node GeoParquet behavior
and GeoParquet relationship-to-record composition still need production checks.
These are tasks within this effort, not reasons to restart format selection.

Use verified inputs and retain traceability to the original GRIT source inventory.
The [prior delivery](../../docs/v0.4.0/grit-river-delivery.md),
[worldwide production record](../../docs/v0.4.0/grit-worldwide-production.md) and
[original inventory](../../docs/v0.4.0/receipts/grit-original-inventory.json)
provide acquisition, identity and independent verification evidence. Preserve exact
normalized geometry while checking source fidelity; do not silently renormalize
or drop information. Historical preservation/publication instructions in those
records do not override this effort's confirmed replacement scope.

## Temporary infrastructure and budget

Use a temporary Hetzner VM for production, separate from the final publication
host. The approved initial infrastructure budget is **EUR 50**. Track total
estimated temporary compute, attached storage, IP and transfer charges, including
applicable taxes; obtain approval before exceeding that ceiling. It is not a
provider-enforced cap and excludes ongoing R2 storage. No deadline or hard latency
threshold was selected.

The proposed starting configuration is a European CCX33 (8 dedicated CPUs,
32 GB RAM, 240 GB local disk) plus a 500 GB attached volume. Live catalog inspection
on 2026-10-18 showed EUR 0.2219/hour before tax for that VM in European locations.
Confirm current prices, availability and volume cost before provisioning. The
rough EUR 7–8/day before-tax allowance is an estimate, not a completion promise.
Sizing is an engineering starting point, not a fixed contract requirement.

The earlier capacity plan allowed about 95 GB originals, 100 GB outputs, 150 GB
scratch and 100 GB headroom. These are estimates, not processing peak bounds.
Monitor disk, memory and spend; retain diagnostic evidence and pause for approval
or a revised approach before exhaustion or budget overrun. Bulk processing stays
on approved compute, not the maintainer laptop. Keep credentials and bulk data
outside Git.

## Verification, publication and cleanup

Require complete source-fidelity verification across all three feature domains,
including row identities, schemas/types/nulls, attributes, metadata and exact WKB.
Independently verify ID coverage/addressing, conservative bounds and complete
immediate relationships in both directions against their authoritative meaning.
Preserve unknown relationships and source caveats rather than inventing links.

Measure representative public first-use and reuse access, projected and full
records, known and absent IDs, spatial discovery, relationship-to-record queries,
large requests and bulk reads. Include catchment polygons and source nodes rather
than inferring their behavior from rivers. Report bytes, requests, elapsed time
and resource use with measurement limitations. Full correctness is required;
selected public reads do not replace full artifact verification. No invented
latency target applies. Investigate substantial regressions and return material
trade-offs for maintainer judgment rather than silently adding fallback formats.

Recheck R2 before bulk transfer using the existing `upstream-r2` profile. #35's
latest operational evidence reported public manifest 403 responses and blocked
cleanup involving owned objects/parts plus a different unowned listed UploadId.
Do not assume those conditions persist or are resolved. Resolve or safely isolate
them; never delete unknown objects or multipart uploads. Authenticated identity
checks do not prove public availability. Hetzner experiment cleanup was verified.

Prefer R2 if reliable. Hetzner remains the agreed alternative host if R2 proves
unusable; report the concrete hosting change and resulting URLs. It must not move
or alter the retained R2 rasters, whose consumer access still needs verification.

Build and verify locally before publication. Stage new vector artifacts without
prematurely destroying the working inputs. Check uploaded identities/readback and
public access, publish the final manifest last, then verify the assembled final
bundle including raster reads. Remove only identified superseded vector artifacts
within the approved `grit/hfx-v0.4.0/` scope after successful cutover. Do not use
broad prefix deletion that could remove rasters or new artifacts. Preserve compact
provenance, full artifact hashes, verification receipts and cleanup evidence.

After verified delivery and evidence preservation, delete this effort's temporary
VM, attached volume and other owned temporary resources. Verify their removal;
volumes can survive VM deletion. If blocked, report retained resources and ongoing
cost rather than claiming cleanup complete.

## Completion and Pourpoint handoff

Success means a documented final contract, fully verified global delivery at the
reported public location, unchanged accessible rasters, successful final public
reads, and accounted-for cleanup within the approved budget.

After delivery, post a concise comment on
[Pourpoint issue #36](https://github.com/pourpoint-tools/pourpoint/issues/36)
(the adjacent `../pourpoint` repository). Link the settled contract, final manifest
and verification evidence; explain access semantics, compatibility implications
and material limitations so the maintainer can finalize the reader and runtime
representation. Do not describe a planned delivery as completed.

Pourpoint implementation, raster redesign, TDX conversion and another broad layout
study are outside scope. Publishing this vision does not itself start production.
