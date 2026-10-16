# GRIT 0.4.0 river delivery

Published and publicly verified on **2026-10-16**; compute cleanup is complete.
Public bundle:
<https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0-rivers-2026-10-12/>.

This bundle stores GRIT v1.0 segments, reaches and source nodes alongside their
catchments under the [vector contract](vector-data.md). It retains branching and
reconvergence, source identity, typed attributes and nulls. It emits no redundant
snap copies and does not replace the earlier publication. The current Pourpoint
reader is **not presumed compatible**; engine integration remains separate work.

The [compact receipt](receipts/grit-river-delivery.json) binds the completed local
checks and full authenticated readback of all 17 artifacts plus the manifest.
The manifest was published last, and public selective reads passed for all three
feature families. The published manifest SHA-256 is
`b9a38083131dcf1a4c7c4e73ebe9a97dff2a4b7ef91a8df53f8bc38cadfa48db`.

| Delivered feature family | Records |
| --- | ---: |
| Catchments: components, segments, reaches | 22,419,857 |
| Rivers: segments, reaches | 22,337,300 |
| Nodes: segment and reach layers | 22,278,858 |

The 17 local artifacts total **36,981,583,471 bytes**, excluding the 12,188-byte
manifest. Original inputs comprise 29 GeoPackages and 43 feature layers across
seven regions plus GLOBAL components. Acquisition and reproduction are described
in [worldwide production](grit-worldwide-production.md); the
[independent verifier](grit-source-verification.md) rereads every original row.

## Verified locally

Full checks passed for source attributes/types/nulls, namespaced identities,
parents, local/component associations, endpoints, cross-tier node references,
reciprocal edges, both complete DAGs, lookup coverage and source-slice budgets.
Independent GDAL reprojection from EPSG:8857 to EPSG:4326 matched all coordinate
sequences with maximum difference **0.0 degree** at **1e-9 degree** tolerance.
Geometry was not reversed, simplified, clipped or repaired. Orientation remains
unspecified; source-directed endpoints and edges determine flow.

Native areas remain distinct from derived geodesic local area; upstream
polygon-union area is not supplied. Component flow connectivity is not supplied,
and component outlets remain null rather than inventing one outlet. Source cycle
and continuity diagnostics, including the undefined `interbasin` label, remain
preserved. A verified DAG is not hydrological certification.

Polygon containment/disjointness checks cover only four BORN segments, 21 reaches
and component 70000129, with zero outside/overlap at 0 m² native-plane tolerance.
**No worldwide polygon-topology certification is claimed.** GDAL and pyproj share
PROJ mathematics; area recomputation is consistency checking, not an independent
geodesic algorithm proof.

## Public selective reads

Three IDs per feature family, selected from the first, middle and last lookup
batches, matched the verified local sample rows completely, including schemas,
attributes, nulls and WKB. No absent-ID claim follows from this run. Requests
pinned strong ETags and used one manifest snapshot matching the full local receipt.

| Artifact | Phase | Requests | Body bytes | Seconds |
| --- | --- | ---: | ---: | ---: |
| catchments | preparation | 8 | 4,518,155 | 4.167 |
| catchments | first_access | 6 | 9,347,256 | 4.665 |
| catchments | repeated_access | 6 | 9,347,256 | 8.912 |
| rivers | preparation | 8 | 4,504,042 | 5.029 |
| rivers | first_access | 6 | 3,300,288 | 3.550 |
| rivers | repeated_access | 6 | 3,300,288 | 2.901 |
| river_nodes | preparation | 8 | 4,490,625 | 4.559 |
| river_nodes | first_access | 5 | 3,123,376 | 2.996 |
| river_nodes | repeated_access | 5 | 3,123,376 | 2.034 |

The compact receipt records selected, touched and fully fetched batch indices for
each phase. Preparation fetched no complete catchment or river data batch; it
fully fetched node batches 0 and 1. First and repeated access each fetched the
three selected catchment/river batches and two of three selected node batches;
node batch 0 was already buffered. Each selection fetched three lookup batches.
Repeated access retains preparation buffers and IPC metadata, not selected-batch
caches. Preparation includes duplicate footer requests and their actual received
bytes. These single-run body-byte/timing measurements are not wire traffic,
consumer startup promises or delineation performance; no latency threshold applies.
See [probe semantics](selective-http-probe.md) and the separate
[small remote experiment](grit-river-http-experiment.md).

## Rasters, licensing and cleanup

The bundle references the unchanged [existing raster objects](grit-raster-verification.md)
directly, with exact full identities and a publisher commitment to retain them
for this bundle's lifetime. It is not self-contained. No raster is copied or
reprocessed. Fresh public head/tail checks and four decoded 1024-square windows
passed on 2026-10-16; this is bounded access evidence, not a fresh full raster hash.
After publication, the same checks passed again at **11:21 UTC**. The old 0.4.0
manifest remained byte-identical, and all 12 other artifacts passed bounded
identity checks. Large old vectors were not decoded or fully rehashed.

GRIT v1.0 derives from [Zenodo record 17435232](https://zenodo.org/records/17435232)
and retains **CC BY-NC 4.0**, source README/license, attribution and transformation
notes. The repository's code license does not replace the data license.

Cleanup passed at **11:22 UTC**: production server `169904835` was deleted;
provider server, volume and primary-IP lists were empty. Compact server receipts,
logs and selected samples were preserved outside bulk storage before deletion;
temporary upload credentials were removed. User-supplied downloads and existing
publications were not deleted. Estimated server cost was **EUR 21.05**, not an
invoice; other charges are excluded. The compact receipt binds cleanup evidence
and the preserved evidence archive. The isolated small experiment is documented
separately; its retention status is not established by this compute cleanup.

TDX conversion remains a [separate handoff](tdx-handoff.md), not part of this delivery.
