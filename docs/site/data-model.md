# Data model

## Features and identity

A catchment is a drainage polygon at a declared resolution tier. A river is a
source river feature, not a catchment boundary or a universal snapping segment.
Optional source nodes describe river endpoints. Nodes are not invented where the
source supplies none. Catchments, rivers and nodes have independent positive
integer ID domains: the same number in two domains identifies different objects.
IDs are dataset-local, not row positions or globally stable identifiers.

Source identity is separate. `source_namespace` and `source_id` retain the source
layer and feature identity; native identifier fields retain their own types.
Coincident geometry or a shared association key does not merge source features.

## Relationships answer different questions

- **Hierarchy:** parent and child relations connect coarser and finer tiers.
  Smaller level numbers are coarser. River and catchment tiers are independent.
- **Flow:** upstream and downstream relations describe supplied same-tier directed
  connectivity. They are immediate edges, not precomputed contributing basins.
- **Node incidence:** endpoints connect rivers to source nodes. Sharing a node
  does not supply every possible incoming-to-outgoing flow edge.
- **Node correspondence:** coarser and finer nodes preserve source cross-tier
  correspondence, not polygon containment or river constituent membership.
- **Drainage associations:** local catchments describe local drainage associated
  with a river. Component catchments describe a connected network component.
  Neither is automatically the accumulated upstream contributing area.

A river can have multiple represented local catchments. The authoritative
`local_catchment_ids` lists and reverse `local_river_ids` preserve all associations.
Do not infer associations solely from spatial intersection.

## Missing information is not a terminal

An empty adjacency list is valid but does not alone say that a feature is a
natural outlet. `catchment_connectivity` distinguishes supplied connectivity
from a level with no supplied edges. Feature nulls and source coverage metadata
separate no represented association from unavailable evidence. Subset cuts retain
external source edge identities and caveats; they do not become source terminals.
Optional absent domains are not dummy empty feature tables.

## Quantities and geometry

`area_km2` is local geodesic polygon area. `up_area_km2` is inclusive same-level
upstream area under documented dataset semantics. Native source area, partitioned
drainage area, mainstem-following area and polygon-union area are not interchangeable.
Unsupported upstream values remain null. A single outlet coordinate is supplied
only when the source describes one outlet; multiple or absent outlets are not
replaced by an arbitrary point.

Vector coordinates use longitude/latitude WGS84. Geometry retains its source
meaning and normalized WKB; packaging does not repair flow continuity. Optional D8
rasters retain their native grids and declared encoding and units. Raster
accumulation and vector upstream area can describe different quantities.
