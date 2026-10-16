# TDX handoff

Use a new session and dedicated effort to convert original TDX data under the
[HFX 0.4.0 vector contract](vector-data.md). Do not convert or replace the hosted
TDX bundle as part of GRIT delivery. This handoff does not design a Pourpoint
runtime or claim current reader compatibility.

## Known original evidence

The user-supplied `~/Downloads/TDX_streamnet_2020071190_01.gpkg` is
3,697,729,536 bytes, with layer metadata dated 2023-01-26. Preserve that file.
[Source observations](grit-river-evidence.md#other-source-comparison-and-limits)
include `1/2 → 2754` and `2754/2755 → 5507 → 12388`. A single river tier needs
no invented parents. Preserve `LINKNO` and processing-basin identity separately;
source IDs require basin namespacing in a multi-basin compilation.

All seven inspected internal edges had coordinate order opposite downstream flow.
Keep native geometry order and verify orientation coverage before declaring it;
connectivity must not depend on reversing lines. `LINKNO=1104039,DSLINKNO=-1`
does not establish a precise termination category. Retain that uncertainty.

The matching basin download failed. `WSNO` does not prove polygon presence.
Acquire the applicable original polygons and compare the complete `streamID` set
against river IDs, checking missing, unmatched and duplicate identities before
claiming an original polygonless-river case. A labeled null-association fixture
only proves that the format permits absent associations.

## Reuse without a new framework

- Reuse the compressed IPC writer, lookup/directory and graph conventions, and
  the selective HTTP probe in `scripts/check_vector_access.py`; see
  [probe semantics](selective-http-probe.md).
- Use `scripts/produce_grit.py` and `scripts/verify_grit.py` as small source-based
  examples of typed normalization and independent full verification, not TDX
  adapters. Their GRIT acquisition, layer mappings, node fields, grouping and
  receipt binding are source-specific; do not rename the scripts and assume
  equivalent semantics.
- Establish original CRS, field types/nulls, source order/area meanings, directed
  edges, polygon associations and actual geometry from small originals first.
  Check source-to-HFX fidelity independently, then scale with bounded-memory
  coverage and explicit resource estimates. Do not infer nodes or associations
  from coincident geometry.
- Obtain approval for compute/budget and a new immutable publication destination;
  preserve existing bundles. Verify artifacts before publishing the manifest,
  then measure actual public selective reads. Keep source licensing and acquisition
  identities with the receipt; GRIT's license does not establish TDX permissions.

Temporary research under `/tmp/hfx17-source-examples/` is not a durable input.
Reacquire or reproduce missing evidence from identified originals. GRIT's
[delivery record](grit-river-delivery.md) supplies the completed GRIT evidence;
no TDX conversion has been performed here.
