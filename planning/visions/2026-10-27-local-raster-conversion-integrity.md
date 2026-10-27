# Local raster conversion integrity

Repair [HFX issue #65](https://github.com/pourpoint-tools/hfx/issues/65): spatial
conversion must not emit a bundle that declares local rasters but omits their
files or artifact identities, and verification must not accept that result.
Implementation of this vision completes #65; publishing this document does not.

## Context

HFX owns the converter and its verifier. Pourpoint consumes the resulting bundle
and cannot recover files omitted by conversion. The raster contract permits both
bundle-local files and explicit external references; this repair does not change
that contract.

The issue records an inventory reproduction at commit
`65ff4b28a80932a5e234021b63880b9f3d8a18f5`. In `src/hfx/spatial_bundle.py`,
`_provenance` excludes TIFF files while `_semantics` retains auxiliary declarations.
Verification derives its expected inventory from the same filter, so it can
accept dangling references. The reproduction uses placeholder bytes, not a valid
raster pair; use it as evidence of reference handling, not raster conformance.

## Required outcome

- Never report successful conversion with dangling local raster declarations.
  Preserve supported local raster files and their identities unchanged, or reject
  unsupported local-raster inputs explicitly before producing an accepted bundle.
  The discussion did not choose between these converter support policies; the
  implementing agent should choose and explain the smallest sound repair.
- Verification must independently check that retained local raster references
  resolve to included files with matching artifact identities. Sharing the
  converter's omission must not make a broken bundle pass.
- Keep valid vector-only bundles and external raster references working. Do not
  silently remove raster declarations to make an incomplete bundle appear valid.
- Keep this a focused converter/verifier repair with meaningful regression tests,
  not raster processing or a new general validation framework.

## Evidence of completion

Reproduce the reported failure before repairing it. Exercise a valid local D8
raster pair, not only the placeholder inventory probe. Demonstrate either unchanged
preservation with successful verification, or explicit unsupported-input rejection.
Demonstrate that verification rejects a bundle retaining a local raster reference
when its file or fingerprint entry is absent, and rejects mismatched identities.
Use the repository's normal test, lint and type-check commands as applicable.

Confirm the current published GRIT manifest uses external raster references and
record the bounded check. The known finding does not establish damage to GRIT:
its rasters are separately hosted and referenced by URL and identity. No GRIT
regeneration or R2 update is expected or authorized by this vision. If new evidence
shows production impact, report it and seek separate authorization for remediation.
Previously converted local-raster bundles could require repair; no such published
bundle has been established by this discussion.

## Boundaries

Do not change the HFX format, raster semantics, native grids, or Pourpoint behavior.
Do not relocate converters or redesign repository responsibilities. HFX currently
contains producer tooling despite its standards-first purpose; whether that
code should move to a separate repository is separate work, not settled here.
Do not fold in the documentation cleanup from Pourpoint #46, republish datasets,
or perform a full production raster scan. Leave reversible file-preservation
mechanics and focused test organization to implementation.
