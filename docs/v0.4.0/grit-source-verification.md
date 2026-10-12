# Independent GRIT verification

Run from the repository root after installing `uv sync --group vector-production`:

```sh
uv run --group vector-production python -m scripts.verify_grit   originals.json output/ new-receipt.json new-scratch.sqlite --worked-example
```

`originals.json` is supplied independently, not read from the output manifest. Its
`sources` entries give original GeoPackage `path`, `region`, and `product`;
`components` optionally selects complete source components. The producer's archive
identities remain in that same inventory. The verifier never imports the producer.
`--worked-example` additionally checks the four documented BORN segment polygons,
their 21 reach polygons and component 70000129 in original EPSG:8857. Omit it for
invented fixtures or inventories without this original example.

The scratch SQLite database must not exist. It holds disk-backed delivered rows,
identities, lookup addresses and edges; it is retained for diagnosis. The receipt
must be new and outside the output. No failed run writes a success receipt.

## Checks and limits

All selected originals are read through Fiona/GDAL, including native physical
field types and nulls, every native attribute, fid, and the source schema ledger.
GDAL exports and transforms original geometry; coordinate, ring and part order
are compared against delivered WKB with absolute tolerance **1e-9 degree**.
The receipt records the maximum observed difference and tool versions. Native
IDs are joined by product/layer/region namespace, not treated as global IDs.

Checks cover strictly coarser parents, local/component associations, endpoints,
cross-tier nodes, reciprocal source edges, node incidence in both directions,
DAGs, graph coverage, bounds, source-derived outlets, full fingerprints, and every
lookup address and directory entry. Declared categorical columns must have typed,
complete code meanings. Original property meanings are not independently certified
from their labels. Geodesic areas are recomputed from delivered geometry with the
same geodesic library as the producer: this is consistency, not an independent
geodesic algorithm proof. GDAL and pyproj also share PROJ mathematics.

The four-group polygon check uses GEOS native-plane difference/intersection area,
with **0 m² tolerance** because these original shared boundaries are exact. It
checks containment and disjoint interiors, not exact child-union equality. Its
coverage is explicit; it is not worldwide polygon topology certification.

This script checks local vector output, not publication readiness. It rejects
raster declarations rather than falsely certify them. External raster receipt
binding and fresh pinned public ranges, upload verification, remote selective
read measurements, licensing/publication review and full regional acquisition
remain delivery steps. Source archive-member binding is the producer's separately
tested acquisition check; this verifier binds and rereads the loose originals.
IPC batch compression and lookup layout reuse existing independent checks; this
verifier does not rederive the producer's incoming-group byte-budget splitting.

## Original small experiment

Untouched producer v2 sample, 2026-10-12: 1,197 catchments (3 components,
135 segments, 1,059 reaches), 1,194 rivers and 1,176 nodes. Complete component
70000129 plus polygon-only 70115212 and 370650032. Final independent verification
passed in 18.95 s wall time, peak RSS 184,107,008 bytes. Maximum coordinate error
was **0.0 degree**. Four segment/21 reach polygon checks passed with zero outside
and overlapping area. This is offline verification, not delineation performance.

Fiona 1.10.1 / GDAL 3.9.2 reads originals; rasterio 1.5.2 / GDAL 3.12.2 /
PROJ 9.8.1 transforms them. pyproj 3.8.0 uses PROJ 9.8.1. An initial Fiona transform
failed the unchanged tolerance by 6.56e-9 degree: PROJ 9.7 replaced the approximate
authalic-latitude inverse used by older Equal Earth implementations. The modern
GDAL path fixed the difference without widening tolerance. The nonzero source
coordinate regression preserves that evidence.

Compact hashes, layer schemas and methods are in
[the sample receipt](receipts/grit-river-sample-verification.json). Bulk originals,
failed scratch outputs and development timing logs remain outside Git. This
receipt is a local sample, not a public GRIT delivery receipt.
