# Experimental selective-access candidates

These are two local **HFX 0.4.0 experiments**, not an approved release or a
replacement for Pourpoint's current contract. They start after traversal supplies
upstream unit IDs. They do not discover upstream membership or change snapping.
The snap target, not necessarily the clicked unit, starts traversal.

- **A (`a-index`)** retains the original Parquet bytes and adds a published lookup.
- **B (`b-arrow`)** replaces only catchments with Arrow IPC file-format batches.
  Attributes and exact WKB stay together. Connectivity and snap files are unchanged.

Neither provides a reader, benchmark, performance claim, zero-copy geometry, or
one-row physical reads. A still has Parquet row-group/column-chunk decode costs.
B uses compressed IPC buffers and WKB still needs geometry-library decoding.
HydroBASINS does not demonstrate GRIT-scale performance or general graph behavior.
See the [published vision](../planning/visions/2026-10-07-hfx-selective-access-candidates.md).

## Reproduce locally

Use Python 3.13 and the committed `uv.lock`. These commands refuse **any existing
destination**, including an empty directory. Inspect and preserve old runs; select
new sibling paths for another run. Failures can leave partial output for inspection.
Only use outputs after independent verification succeeds. Do not modify source
files or generated bundles in place.

```bash
uv sync --locked
SOURCE=/Users/nicolaslazaro/.prime/agent/session-artifacts/01a1129b-ff00-7678-9ab2-c76e53fe810a/vector-access/data/hydrobasins
OUTPUT=/Users/nicolaslazaro/.prime/agent/session-artifacts/hfx-candidates/hydrobasins
uv run python -m hfx.candidates "$SOURCE" "$OUTPUT/candidate-a-index" "$OUTPUT/candidate-b-arrow"
uv run python -m hfx.verify_candidates "$SOURCE" "$OUTPUT/candidate-a-index" "$OUTPUT/candidate-b-arrow" --report "$OUTPUT/verification.json"
```

The complete bundles stay outside Git. **Do not upload them.** The copied
`ATTRIBUTION_AND_PROVENANCE.txt` marks this compiled HydroSHEDS derivative for
internal use and prohibits public/open redistribution as a stand-alone product.
The repository's MIT license does not replace the source-data license.

## Discovery and manifest interpretation

Each root `manifest.json` is an experimental wrapper, **not** a 0.3.0 manifest.
Readers must explicitly opt into its `experimental: true` and `candidate` value;
`format_version: "0.4.0"` alone does not establish a released contract. These field
choices are reversible and have no forward-compatibility promise.

| Field | Meaning |
| --- | --- |
| `source_manifest` | `source-manifest.json`: original manifest bytes, source semantics only |
| `catchments` | `catchments.parquet` for A; `catchments.arrow` for B |
| `lookup` | `lookup.arrow`, Arrow IPC **file**, not stream |
| `directory` | `lookup-directory.json`, UTF-8 JSON described below |
| `index_batch_rows` | Maximum index records per batch; default 65,536 |
| `catchment_batch_bytes` | B logical uncompressed budget; default 8,388,608; ignored for A |
| `artifacts` | Fingerprints of every file except this wrapper manifest |

All artifact names are relative to the bundle root. There is one catchment artifact
per bundle, no sharding, and no artifact-number column in the lookup. Graph and
auxiliary discovery uses the original manifest. Its fabric identity, CRS, topology,
unit count, level semantics, auxiliary declarations and attribution remain valid
source evidence. Its original implicit catchment filename is superseded by the
wrapper. Copied `validation/` reports describe the **source**, not 0.4.0 conformance.

## Lookup and range directory

`lookup.arrow` has exactly these non-nullable fields:

| Field | Arrow type | Address semantics |
| --- | --- | --- |
| `id` | `int64` | Positive, dataset-local unique unit ID |
| `block` | `int32` | Zero-based Parquet row group (A), or IPC record batch (B) |
| `row` | `int32` | Zero-based row within that block |

IDs are strictly ascending globally and within each index batch. Index batches are
**uncompressed**. No assumption is made about gaps, source ID encodings or physical
row order. Schema metadata contains `hfx:catchments_sha256` (ASCII lowercase full
SHA-256 hex of addressed catchments) and `hfx:candidate` (`a-index` or `b-arrow`).

The directory has this shape (illustrative sparse IDs):

```json
{"version": 1, "batches": [
  {"batch": 0, "min_id": 2, "max_id": 13, "rows": 2},
  {"batch": 1, "min_id": 90, "max_id": 700, "rows": 2}
]}
```

There is exactly one entry per index batch, in batch order. Endpoints are inclusive
and equal the batch's first and last IDs. Ranges do not overlap and `rows` is its
record count. Every valid ID falls in exactly one range. A missing ID may fall
inside a range; range membership **does not prove existence**. If no range covers
an ID, or binary search in that range's batch finds no exact ID, return absent.
Never substitute the nearest ID. JSON numbers here represent signed 64-bit
integers: readers must retain exact integer precision (not JavaScript `Number`).

### Selective access sequence (design handoff, not an implemented reader)

1. Read the wrapper and small directory. Check artifact identity as below.
2. Sort/deduplicate requested IDs. Binary-search directory endpoints; group IDs
   by index batch and read each needed batch once.
3. Locate IPC batches via the file trailer/footer: Arrow IPC ends with a
   little-endian 32-bit footer length and six-byte `ARROW1` magic. Fetch the footer
   from that length; its record-batch offsets and lengths locate range reads.
   Fetch schema/dictionary dependencies as required by Arrow. This index has no
   dictionary columns. Do not scan all index batches or all catchment IDs.
4. Binary-search each loaded numeric ID array; retain exact matches and their
   addresses. Group/deduplicate addresses by `(catchment artifact, block)`.
5. A: use the Parquet trailer/footer and row-group column-chunk metadata to fetch
   desired columns. B: use the IPC footer to fetch addressed record batches.
   Read each shared block once and select the requested rows. Restore caller
   order and duplicates if the future reader's API requires them.

IPC footer access may read metadata for all batches, but not their numeric arrays.
The small directory itself is read in full. Remote transport must support byte
ranges over the unchanged file bytes (no transparent content recompression), and
must pin one immutable object version for all requests. No remote tests are claimed.

## B catchment schema and batching

B preserves the source Parquet Arrow schema, field nullability and metadata,
including coordinate-reference/`geo` metadata; it does not reinterpret it as a
GeoArrow coordinate-array extension. GeoParquet covering metadata is retained as
source metadata; Arrow IPC is **not** claimed to be GeoParquet.

The delivered source fields are `id: int64!`, `level: int16!`, `parent_id: int64`,
`area_km2: float32!`, `up_area_km2: float32`, `outlet_lon: float64!`,
`outlet_lat: float64!`, `bbox: struct<xmin: float32!, ymin: float32!, xmax: float32!,
ymax: float32!>!`, `geometry: binary!`; `!` means non-nullable. All additional
source fields, including optional strings, are preserved. No attribute casts,
geometry decoding/re-encoding, coordinate changes, or identity rewrites occur.

The producer reads source rows in original order in groups of at most 4,096.
Within each group it emits the largest prefix whose Arrow `RecordBatch.nbytes`
is at most **8 MiB before compression**. It repeats for the remaining rows.
It does not join across these input boundaries; batches can be smaller than the
budget. `nbytes` counts logical array data, offsets and validity bytes as reported
by PyArrow, not retained allocation size, IPC metadata or total wire size. The
budget is a block-organization rule, not a bound on peak memory or file bytes.
A single row larger than the budget is emitted alone; WKB is never split.
IPC uses **Zstandard buffer compression** with PyArrow's default codec level.
Geometry and attributes are written in the same record batch.

## Artifact binding and safe publication

Each `artifacts` entry contains `size_bytes`, full producer-side `sha256`, and
SHA-256 of the first and last `min(65536, size_bytes)` bytes as `head_sha256` and
`tail_sha256`. Check length and these two bounded regions before trusting a
lookup; the lookup schema also names the exact catchment digest. This catches
common wrong-file/truncation/layout substitutions without a startup full scan.
The directory is fingerprinted just like the index and catchments.

**Bounded fingerprints are mismatch checks, not full integrity verification.**
A same-size interior mutation can evade them. Consumers must use trusted manifests
and immutable bundles. For remote publication (not performed here), pin strong
object versions/ETags across range requests and map them to the published full
SHA-256; an arbitrary ETag is not automatically that digest. Where immutability
cannot be trusted, verify the full digest before use. A startup-only check cannot
protect files modified after the check. Rewriting any addressed file requires
rebuilding and republishing its lookup and fingerprints as a new bundle.

## Correctness evidence

`hfx.verify_candidates` is a local, bounded-read correctness check, not a consumer
API. It retains an int64 ID array (eight bytes per source row) and block offsets,
not a geometry table or global Python dictionary. It hashes artifacts and compares
the entire B row sequence against independent source Parquet reads, including schema metadata, nulls, relationships and exact WKB.
It checks all index addresses against physical source evidence, strict sorted
unique IDs, and directory endpoints. A data files, source manifests, attribution,
graph and snap copies must match source bytes. The producer also hashes all source
files before and after production. Focused fixtures cover shuffled sparse IDs,
invalid IDs, batch boundaries, oversized WKB, optional strings, nulls, preservation
and refusal to overwrite outputs.

The [local run record](candidate-results.md) records the delivered identities,
counts, sizes and validation commands. These are format/correctness facts, not
latency or memory-performance results.
