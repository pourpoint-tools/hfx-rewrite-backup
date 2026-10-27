# TDX original normalization

These offline commands build **private normalized staging**, not a publishable
spatial bundle. One-basin local downloading and processing is authorized subject
to available disk and memory. This does not establish that global assembly fits
the laptop; size approved temporary compute and storage separately.

```sh
uv run --group vector-production python -m scripts.produce_tdx inventory.json staging
uv run --group vector-production python -m scripts.verify_tdx inventory.json staging --report original-verification.json
```

Inventory shape (repeat `sources` for each processing basin):

```json
{"release":"NGA-TDX-Hydro-20230126","sources":[{"basin":"7020000010","catchments":{"path":"/source/basins.gpkg","sha256":"ACQUIRED_FULL_HASH"},"rivers":{"path":"/source/streamnet.gpkg","sha256":"ACQUIRED_FULL_HASH"}}]}
```

For a basin whose polygon original is unavailable, replace its `catchments` object
with `{"status":"unavailable","reason":"Original polygon source unavailable"}`.
Do not omit the domain, attach a source path to this declaration, or omit its rivers.
The [historical partial delivery](tdx-handoff.md) has 62 river sources and 59 polygon
sources. Its missing originals for `1020027430`, `5020049720`, and `6020006540` have
since been recovered. The full-coverage delivery requires all 62 paired originals:
no basin may be marked unavailable. The commands still accept explicit subsets
and unavailable-source declarations, but require at least one supplied catchment source.

Additional acquisition URL/response/license provenance may remain in this inventory;
its exact bytes and per-source metadata are retained. Hashes must come from the
acquisition inventory, not be substituted to bypass a mismatch. The release name
is not an immutable URL. Original NGA data is CC BY-SA 4.0; retain original license,
attribution and acquisition documents alongside the inventory for delivery.

- The observed source declarations are supported, not a general GeoPackage adapter.
  `INTEGER`, `MEDIUMINT`, `REAL` retain int64, int32, float64 types and native nulls,
  except catchment `streamID`: both integer declarations map losslessly to int64.
  `source-metadata.json` retains each basin/domain's original declarations and
  supplied/unavailable status; the delivered field records the lossless mapping.
  Unsupported declarations fail. Other native feature schemas must match.
- IDs follow sorted processing-basin identity, then native `fid` order. Source
  `fid` identifies each feature; `streamID` is an association key, never a reason
  to dissolve polygons. Native values remain intact under the documented mapping.
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
  unmatched rivers within supplied polygon sources remain represented. No scalar
  local association is invented. River `local_catchment_coverage` is a nonnull
  string: `supplied` means associations were checked against the supplied polygon
  source; `unavailable` means no polygon source was available and associations are
  unknown. Empty lists in the latter case do not establish naturally polygonless
  rivers. The field and its categorical meanings survive spatial conversion.
  Existing rejection of null or unmatched polygon `streamID` remains: widening
  preserves nulls, but does not authorize guessing associations for null keys.
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
