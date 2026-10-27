# Project Instructions

## Purpose

HFX (HydroFabric Exchange) specifies normalized hydrofabric data consumed by
watershed engines such as Pourpoint. The authoritative current specification
starts at `docs/site/index.md`. The current HFX 0.4.0 representation is spatial
GeoParquet with IPC lookups and immediate relationships; format version alone
does not select representation compatibility.

Keep source normalization outside the engine. Preserve production tools and
source provenance; coordinate contract changes explicitly with consumers.
Pourpoint assembles these documentation sources into the shared site. Do not
maintain another specification copy or a separate HFX publishing lifecycle.

## Development guidelines

- Use `uv` for project dependencies and execution.
- Write strongly typed Python throughout, including internal code.
- Use Ruff for formatting and linting, and ty for type checking.
- Prefer suitable testing utilities, assertions, and fixtures provided by
  dependencies over hand-rolled equivalents. Add custom fixtures where
  project-specific behavior requires them.
