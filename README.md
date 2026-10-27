# HFX

HydroFabric Exchange specifies normalized hydrofabric data for watershed engines
such as [Pourpoint](https://github.com/pourpoint-tools/pourpoint). It preserves
source identities, typed attributes, relationships and optional native-grid D8
rasters without moving source normalization into the engine.

Start with the [current specification](docs/site/index.md):

- [Data model](docs/site/data-model.md)
- [Bundle and manifest](docs/site/bundle.md)
- [Vector schemas](docs/site/vector-data.md)
- [Spatial storage and relationships](docs/site/spatial-layout.md)
- [Native-grid rasters](docs/site/raster-data.md)

The current representation requires `format_version: "0.4.0"`,
`representation: "spatial-geoparquet-adjacency"`, and `representation_version: 1`.
Features are GeoParquet; lookups and immediate relationships use Arrow IPC.
The format version alone does not imply compatibility with earlier IPC features.

These sources form the HFX section of Pourpoint's shared documentation site.
The eventual address is https://pourpoint-tools.github.io/; publication remains
disabled during private development. Pourpoint owns the shared site configuration
and pins the exact HFX revision used for its releases. HFX checks build proposed
content through that same configuration and never publish.

## Development

Use Python 3.13 and [uv](https://docs.astral.sh/uv/):

```bash
uv sync --group raster-experiment --group vector-production
uv run --group raster-experiment --group vector-production pytest
uv run ruff format --check
uv run ruff check
uv run --group raster-experiment --group vector-production ty check src scripts tests
uv build
```

Production tools remain in `scripts/` and `src/hfx/`. Their retained source
identities and attribution live in [scripts/provenance](scripts/provenance/README.md).
See [raster verification](scripts/README.md) and [development conventions](AGENTS.md).
Package version `0.0.0.dev0` is a development placeholder, not a format version.

## License

Repository code is [MIT](LICENSE). Dataset licenses are separate; GRIT source and
derived data retain CC BY-NC 4.0 and their attribution requirements.
