# GRIT river source evidence and decisions

Original-data inspection on 2026-10-12 informed the [vector contract](vector-data.md).
These are source observations, not a converted-bundle, worldwide fidelity or
selective-access receipt. The [published vision](../../planning/visions/2026-10-12-hfx-0-4-0-river-data-and-grit-delivery.md)
requires those later checks before delivery is complete.

## Source identity and reproduction

GRIT v1.0 is [Zenodo record 17435232](https://zenodo.org/records/17435232),
released December 15, 2025. Read its product README §§4,6,7 alongside Wortmann
et al., “Global River Topology (GRIT): A bifurcating river hydrography,”
[doi:10.1029/2024WR038308](https://doi.org/10.1029/2024WR038308).
Data and derived samples retain **CC BY-NC 4.0**, attribution and change notices;
the repository's MIT code license does not replace the data license.

Full originals passed the published MD5 checks; ZIP extraction also checked CRCs.
All five GeoPackages declare EPSG:8857. Download URLs have the form
`https://zenodo.org/api/records/17435232/files/NAME/content`.

| NAME | Compressed bytes | Verified MD5 |
| --- | ---: | --- |
| `GRITv1.0_segments_SP_EPSG8857.gpkg.zip` | 107984343 | `e6c5db8d8ecd06d0bdc9bdb5eaebff09` |
| `GRITv1.0_reaches_SP_EPSG8857.gpkg.zip` | 568680851 | `7e2609ec1da4d71b39a6b1cf59f85042` |
| `GRITv1.0_segment_catchments_SP_EPSG8857.gpkg.zip` | 279788308 | `171d32a7dbaf7760545349db65515285` |
| `GRITv1.0_reach_catchments_SP_EPSG8857.gpkg.zip` | 728927168 | `5d5b416c3737c9d92dab0b4222f4d863` |
| `GRITv1.0_component_catchments_GLOBAL_EPSG8857.gpkg.zip` | 360101987 | `c7086353ca7cc3504df80ac23e0cedeb` |
| `README.pdf` | 150250 | `d31f56d7d0243f923db881ebfaa981d3` |

Reproduce from read-only SQLite connections: enumerate feature tables through
`gpkg_contents`, inspect `PRAGMA table_info`, and select line/polygon `global_id`
in `(70010735,70010734,70000197,70008597)` at segment tier. Select reaches by
`segment_id` in that list; select endpoint nodes by the line node IDs. Polygon
tables are `segment_catchments__1`, `reach_catchments__1` and
`component_catchments__1`. Select component IDs 70000129, 70115212, 370650032.
Use the complete SP line and polygon tables for anti-joins in both directions,
not a selected sample, to establish absence and reference coverage.

Read original geometries through GeoPackage-aware tools; a GeoPackage blob is not
itself WKB. Preserve its exported WKB before any transform. Native-plane geometry
checks below used Shapely. Delivery must separately record and independently
verify EPSG:8857 to EPSG:4326 reprojection, unchanged coordinate order, source
attribute types/nulls and every renamed/cast column. No projected-plane comparison
below proves delivered WKB fidelity.

## Original records and relationships

The BORN segment diamond is `70010735 → {70010734,70000197} → 70008597`.
Its constituent reaches are:

| Segment | Reaches in flow order |
| ---: | --- |
| 70010735 | 70106320 → 70106321 → 70106322 → 70106323 |
| 70010734 | 70106319 |
| 70000197 | 70000097 |
| 70008597 | 70078460 through 70078474 |

All 25 lines have native `catchment_id=70000129` (component), while native
`global_id` matches their own local polygon. Each reach's `segment_id` identifies
its parent river and its polygon's parent segment polygon independently.
Do not use the shared component key as the local polygon key. Source `cat` is
not interchangeable with `global_id`: segment 70010735 has `cat=9009`.

Complete SP audits found 134557 segment lines/polygons and 1676707 reach
lines/polygons, with zero missing, unmatched, duplicate or null IDs. Every local
polygon component reference resolves in the 82557-row global component table;
all reach-to-segment references resolve and agree with line membership. Numeric
IDs collide across layers: all SP segment polygon IDs occur among reach polygon
IDs. HFX IDs must distinguish them; retain native IDs and layer namespaces.

All four original segment polygons exactly equal their constituent reach-polygon
unions in native EPSG:8857. Selected polygons are valid, have no positive-area
same-tier overlap, and lie within component 70000129. This is sample evidence,
not global nesting certification. Source polygon `area` is local equal-area km²:
segment 70010734 stores 0.365512 versus measured 0.3655125. Preserve it separately
from HFX geodesic area and river partitioned/mainstem drainage areas.

River line membership has different geometry: the four segment-to-reach-union
Hausdorff distances are 23.057749, 14.667962, 20.543090 and 25.086759 metres
respectively. Do not impose exact line-union equality. Product documentation says
vector polygons were simplified and do not exactly align with raster catchments.
Earlier author WFS exports differed in schema, IDs, area and geometry; their
apparent nesting failures are **not original-file evidence**.

## Nodes, flow and terminals

Full original SP graphs are DAGs: Kahn removal exhausted all 134557 segments and
1676707 reaches, with 131331 and 1673481 directed edges respectively. All upstream
and downstream lists reciprocate, resolve and agree with endpoint incidence in
both directions; no duplicate list entries or self-links were found. This is not
a worldwide DAG proof. Production must investigate any cycle before claiming
conformance; no silent edge deletion or redirection is allowed.

Node 70000364 is a source bifurcation, node 70000365 a confluence. Keep the
segment-node and reach-node identities distinct. Reach nodes carry nullable REAL
`segment_node_id` and `n_segments`: the two junctions have their matching segment
IDs and `3.0`; internal reach node 70085009 has both null. Across SP, 137785
references are nonnull, integral and resolve one-to-one; 1542150 are null.
An HFX int64 correspondence does not replace the original float64 column.

For the 25 selected lines, the first native coordinate equals the upstream node
point and the last equals the downstream point. This supports orientation 1 only
for those checked rows. Preserve the original point geometry and typed node
attributes, source incidence strings and width-share ordering.

Segment node 370009903 (MURR) has `continuity_violated=1`, `cycle=0`, source type
`confluence`, no incoming lines and three outgoing lines. Retain this anomaly;
acyclicity is not hydrological certification. Reach layers lack those diagnostic
columns; do not invent source zeros. Actual segment node types include `outlet`
(12 rows), which the README's enumerated list omits. Preserve that literal code
with uncertain meaning, not an invented ocean/sink classification.

Component 70000129 has six source coastal-outlet nodes:
70000324, 70012133, 70012134, 70012137, 70012138, 70012143. Selecting one as its
unique outlet would discard information. Original polygon-only components
70115212 (BORN, `is_coastal=1,is_sink=0`) and 370650032
(MURR, `is_coastal=1,is_sink=1`) have neither SP local polygons nor river lines
by ID or component association. The flags are not mutually exclusive.

The tiny diamond has external source neighbors; cutting them does not create
natural outlets. A complete component example can avoid those cuts. The later
conversion receipt must distinguish its actual selection from this original
four-segment investigation.

## Maintainer decisions after the published vision

On 2026-10-12 the maintainer explicitly approved:

- Keep components as the coarsest catchment tier. Permit multiple or no represented
  outlets, including coastal and inland sink polygon-only cases. Do not invent
  outlet coordinates or component flow edges. Declare unsupplied connectivity
  separately from source termination.
- The new GRIT 0.4.0 bundle must reference the existing unchanged redesigned raster
  objects, with explicit immutable external references. **No raster duplication
  or reprocessing.** Accept the cross-prefix retention dependency, preserve exact
  fingerprints and the [earlier raster receipt](grit-raster-verification.md).
- Acquire the three local original polygon archives above for investigation;
  acquisition and checks completed. User-supplied and pre-existing data remain.

These decisions supplement the published vision; they were not already contained
in its original wording. Exact experimental/public write destinations, compute
provisioning and a total budget still require approval. No upload or provisioning
is evidenced here. Keep 8388608-byte batches and 65536-row lookup batches; no
storage-format competition or latency target was introduced.

## Other-source comparison and limits

HydroRIVERS v10, selected by `MAIN_RIV=10000009`, has
`10000003/10000004 → 10000009`; all three reference HydroBASINS 1120031210.
Its MultiLineString geometry is already EPSG:4326. Preserve `ORD_STRA`, `ORD_CLAS`
and `ORD_FLOW` independently. The original archive SHA-256 is
`c0938490d168c6aafdcb62e92a9a1e9b7e9188d20f91698a84d15afdbb5aa262`;
read the October 2019 technical documentation. Target basin rows remain unverified.
Samples stay local under their source redistribution restrictions.

Original TDX processing basin 2020071190 has `1/2 → 2754`,
`2754/2755 → 5507 → 12388`; all seven checked internal edges have vertex order
opposite downstream flow. Preserve native order. `LINKNO=1104039,DSLINKNO=-1`
does not establish a precise terminal category. The supplied GeoPackage is
3697729536 bytes with layer metadata dated 2023-01-26. Polygon acquisition failed;
`WSNO` is not proof of polygon presence. A labeled null-association fixture does
not prove an original polygonless TDX river. Full TDX conversion is a separate effort.

Original research artifacts were retained outside Git under
`/tmp/hfx17-source-examples/` and `/tmp/hfx-river-investigation/`. Those locations
are disposable evidence, not normative dependencies: use the source identities,
selection and checks above to reacquire/reproduce. Full production verification,
remote requests/body bytes, selected versus fetched batches, first/repeated-access
timings, final public identities and cleanup belong in separate delivery receipts.
