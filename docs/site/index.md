# HydroFabric Exchange

HFX describes normalized hydrofabric data for watershed engines. A bundle brings
source catchments, rivers, relationships and optional native rasters together
with explicit identities and provenance. HFX specifies what the stored data means
and how to find it. An engine such as Pourpoint selects features, traverses
relationships and delineates contributing areas; source normalization belongs
outside the engine.

The current HFX 0.4.0 representation is `spatial-geoparquet-adjacency`, version 1.
Its feature records are GeoParquet, with Arrow IPC lookups and immediate
relationships. Matching only `format_version` does not establish compatibility.

Read the specification in this order:

1. [Data model](data-model.md): features and distinct relationships.
2. [Bundle organization](bundle.md): discovery, provenance and integrity.
3. [Vector schemas](vector-data.md): exact fields and source meanings.
4. [Spatial storage and relationships](spatial-layout.md): addressing and access.
5. [Native-grid rasters](raster-data.md): optional direction and accumulation.

This contract describes representation, not a certification of source hydrology.
Dataset licenses, missing information and source caveats remain relevant to every
consumer.
