# TDX original normalization

These offline commands build **private normalized staging**, not a publishable
spatial bundle. Use approved temporary compute; do not download bulk originals to
the laptop.

```sh
uv run --group vector-production python -m scripts.produce_tdx inventory.json staging
uv run --group vector-production python -m scripts.verify_tdx inventory.json staging --report original-verification.json
```

Inventory shape (repeat `sources` for each processing basin):

```json
{"release":"NGA-TDX-Hydro-20230126","sources":[{"basin":"7020000010","catchments":{"path":"/source/basins.gpkg","sha256":"ACQUIRED_FULL_HASH"},"rivers":{"path":"/source/streamnet.gpkg","sha256":"ACQUIRED_FULL_HASH"}}]}
```

Additional acquisition URL/response/license provenance may remain in this inventory;
its exact bytes and per-source metadata are retained. Hashes must come from the
acquisition inventory, not be substituted to bypass a mismatch. The release name
is not an immutable URL. Original NGA data is CC BY-SA 4.0; retain original license,
attribution and acquisition documents alongside the inventory for delivery.

- The observed source declarations are supported, not a general GeoPackage adapter.
  `INTEGER`, `MEDIUMINT`, `REAL` retain int64, int32, float64 types and native nulls.
  Unsupported declarations fail. Across basins native feature schemas must match.
- IDs follow sorted processing-basin identity, then native `fid` order. Source
  `fid` identifies each feature; `streamID` is an association key, never a reason
  to dissolve polygons. Native fields and declared types remain intact.
- Embedded WKB is copied without reversal, repair, dissolve or serialization.
  Only GeoPackage headers are removed. Inputs must declare EPSG:4326 and 2D.
  Processing basin is not a hierarchy tier. All features have level 0.
- Polygon local area subtracts geodesic hole areas from exterior areas on WGS84.
  Raw river areas are retained; unsupported normalized upstream area stays null.
  Outlets are null and orientation is unspecified. Finite zero-length source lines
  remain unchanged; their geometry does not supply direction or termination.
- `DSLINKNO` and `USLINKNO1/2` must agree completely; unresolved references other
  than `-1`, duplicates, self-links and cycles fail. Missing links are not natural
  terminal classifications. No cross-basin inference or contracted polygon graph.
- `local-associations.parquet` supplies every river/catchment association;
  polygonless rivers remain represented. No scalar local association is invented.
  Catchment connectivity is `not_supplied`, without a dummy graph or node files.

The verifier reads original SQLite values independently of the ingestion/mapper,
checks full feature populations, native values/types/nulls, exact WKB, derived
areas/bounds and both supplied graph directions and associations. It pins source
hashes before/after. Polygon overlap is **not checked**; no worldwide topology
certification or 62-basin completeness is claimed by these sample-capable tools.
Final spatial feature/lookup/relationship verification remains a separate step.

Geometry is streamed in groups of 4096 rows before byte-budget splitting. The
producer re-reads projected numeric staging columns and validates relationships
one basin at a time. The independent verifier retains source topology for one
basin and indexes actual output relationships in temporary SQLite storage, with
an 8 MiB page cache, outside the bundle. Graph and association row order is not
required. Temporary verifier storage is removed on success or failure.

Numeric memory scales with the largest basin, not a fixed byte limit. Measure
peak RSS and scratch disk on meaningful samples before sizing global work; final
spatial assembly has separate workspace needs. Failed artifacts remain for
diagnosis. Neither command provisions, downloads, publishes or reads credentials.
Reports must remain outside bundles.
