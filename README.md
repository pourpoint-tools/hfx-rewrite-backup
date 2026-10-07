# HFX

Private workspace for rethinking **HydroFabric Exchange**, a standard for
normalized hydrofabric data consumed by watershed delineation engines such as
[Pourpoint](https://github.com/pourpoint-tools/pourpoint).

This is a standards-first project: the aim is a clear, lean standard described
with minimal documentation and very little supporting code. Both the format and
the repository's purpose are open to redesign, including changes that better
serve the Python rewrite of Pourpoint.

This repository contains a small local producer for two
[experimental selective-access candidates](docs/selective-access-candidates.md).
It does not define an approved replacement standard or a general-purpose toolkit.
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
uv run ty check src
uv build
```

See [AGENTS.md](AGENTS.md) for development conventions.

## License

[MIT](LICENSE).
