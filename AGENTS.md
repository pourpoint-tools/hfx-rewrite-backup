# Project Instructions

## Purpose

HFX (HydroFabric Exchange) is a standards-first project for normalized hydrofabric
data consumed by watershed delineation engines such as Pourpoint.
This is a fresh redesign workspace containing only project scaffolding.
The intended repository holds minimal, clear documentation of the standard and
very little supporting code. Do not recreate the old toolkit by default.

HFX format 0.3.0 and the existing `CooperBigFoot/hfx` repository are reference
evidence, not compatibility requirements. Both the format and the repository's
purpose may be reconsidered to better serve the Python rewrite of Pourpoint.
No next-version design or version number has been selected yet.
See README.md for the pinned reference. Investigate old behavior rather than
assuming every result or design choice is correct. Do not import accumulated
planning material or documentation wholesale.

Keep source-fabric normalization outside the delineation engine. Coordinate any
future contract change with Pourpoint explicitly; this scaffold does not change
its current input contract.

## Development guidelines

- Use `uv` for project dependencies and execution.
- Write strongly typed Python throughout, including internal code.
- Use Ruff for formatting and linting, and ty for type checking.
- Prefer suitable testing utilities, assertions, and fixtures provided by
  dependencies over hand-rolled equivalents. Add custom fixtures where
  project-specific behavior requires them.
