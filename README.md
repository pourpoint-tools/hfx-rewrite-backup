# HFX

Private workspace for rethinking **HydroFabric Exchange**, a standard for
normalized hydrofabric data consumed by watershed delineation engines such as
[Pourpoint](https://github.com/pourpoint-tools/pourpoint).

This is a standards-first project: the aim is a clear, lean standard described
with minimal documentation and very little supporting code. Both the format and
the repository's purpose are open to redesign, including changes that better
serve the Python rewrite of Pourpoint.

The revised [GRIT spatial stored contract](docs/v0.4.0/spatial-layout.md) uses
GeoParquet features and separate immediate relationships. The
[global delivery record](docs/v0.4.0/grit-final-delivery.md) tracks verified publication
and resource cleanup. Existing IPC reader compatibility is not implied.

The earlier [HFX 0.4.0 Vector Data contract](docs/v0.4.0/vector-data.md) specifies
catchment and river IPC batches, ID lookups, directed graphs, source nodes and
explicit drainage-unit associations. Rivers retain native identity and attributes;
snapping is one possible use, not their stored data model.
The [raster contract](docs/v0.4.0/raster-data.md) adds optional native-grid D8 pairs
and permits explicit immutable references to unchanged raster objects. The
[river source evidence](docs/v0.4.0/grit-river-evidence.md) records original examples
and implementation decisions; it is not a production delivery receipt.
The [completed GRIT river delivery](docs/v0.4.0/grit-river-delivery.md) records the
new public bundle, verification and cleanup. The [private TDX delivery](docs/v0.4.0/tdx-handoff.md)
records its accepted source coverage and verification; current Pourpoint reader
compatibility is not assumed.
Small production and verification scripts live in `scripts/`. The earlier
[selective-access candidates](docs/selective-access-candidates.md) remain experimental evidence.
The package version `0.0.0.dev0` is a setup placeholder, not an HFX format version or release
plan. No package publishing or CI is configured.

## Existing HFX reference

The existing project remains at [CooperBigFoot/hfx](https://github.com/CooperBigFoot/hfx).
Its [format 0.3.0 specification](https://github.com/CooperBigFoot/hfx/blob/c18a8a6a115e2045080d8752279d39db2b9b29b6/spec/HFX_SPEC.md)
and implementation at commit
[`c18a8a6a115e2045080d8752279d39db2b9b29b6`](https://github.com/CooperBigFoot/hfx/tree/c18a8a6a115e2045080d8752279d39db2b9b29b6)
are reference evidence, not requirements to preserve every feature or design.
The format and Rust toolkit have separate version tracks.

This repository starts with fresh history. It does not import the old code,
specification, or planning material. The existing repository and Pourpoint's
current input contract remain unchanged; a future replacement contract needs
explicit coordination.

## Development

Use Python 3.13 and [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run pytest
uv run ruff format --check
uv run ruff check
uv run --group raster-experiment ty check src scripts tests
uv build
```

The raster producer checks use optional dependencies. Run
`uv run --group raster-experiment pytest` to include their tests; the default
`uv run pytest` skips them when those dependencies are absent. The full type
check above includes the raster scripts. See [scripts/README.md](scripts/README.md)
for producer verification commands.

See [AGENTS.md](AGENTS.md) for development conventions.

## Earlier GRIT vector production

The earlier [GRIT vector record](docs/v0.4.0/grit-verification.md) and
[raster delivery record](docs/v0.4.0/grit-raster-verification.md) contain the
public URL, artifact identities, verification results and cleanup status.

The commands below reproduce the earlier normalized catchment/snap delivery, not
the revised original-source river bundle. They cannot restore lost river fields.
Use new, disjoint source/output directories on the same filesystem. Download the
four vector inputs and source `manifest.json`, `NOTICE`, `CITATION.txt`, and
`README.md`. Verify the source hashes before conversion. The converter hardlinks
unchanged graph/snap files; keep both directories immutable during verification.
It refuses an existing output directory. Failed outputs stay available for inspection.

```bash
uv run python scripts/convert_vector.py SOURCE OUTPUT
uv run python scripts/verify_vector.py SOURCE OUTPUT --report verification.json
uv run python scripts/check_vector_access.py PUBLIC_BUNDLE_URL --ids PRESENT_ID ABSENT_ID --source SOURCE --report public-access.json
```

The verifier receipt must be outside source and output. Conversion and verification
read all source records; the HTTP probe reads only requested remote batches. Its
optional `--source` check scans local source rows independently. Monitor free disk
space during production. Publish only verified outputs at a confirmed unused
prefix, preserve existing objects, and publish `manifest.json` last. Verify upload
identities and public range access before removing this run's local bulk files.
The approved additive GRIT raster extension follows the
[manifest amendment rules](docs/v0.4.0/vector-data.md#artifact-identity-and-range-access)
instead of requiring a new prefix; vector artifacts stay unchanged.
Credentials and bulk data stay outside Git.

## License

[MIT](LICENSE).
