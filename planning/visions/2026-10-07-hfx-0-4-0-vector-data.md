# HFX 0.4.0 vector data

Formalize candidate B as HFX 0.4.0 vector data, convert the public GRIT vector
bundle, and publish it at a new versioned public R2 URL. This gives Pourpoint a
concrete contract and dataset for reader development and benchmarking.

This is a standalone vision. Pourpoint's reader work and vision revision remain
separate. Candidate B is selected; preserve the underlying data information.

## Contract and documentation

Write the format contract in one concise file: `docs/v0.4.0/vector-data.md`, titled
“HFX 0.4.0 Vector Data”. Describe files, manifest fields, schemas, relationships,
batching, compression, lookup addressing, artifact identity, and range access
precisely enough to produce and consume conforming data. Use plain technical
language. Exclude promotional language, contrastive negation, em dashes,
justification, comparisons, and benchmark numbers from that specification.
Future raster documentation can sit alongside this file.

Implement the selected candidate B design:

- Publish an ID-sorted lookup mapping each catchment ID to its record batch and row.
- Store catchment attributes and exact WKB together in byte-budgeted Arrow IPC
  file-format record batches.
- Publish the lookup range directory so consumers can find relevant lookup batches
  without scanning worldwide IDs or constructing a global catchment locator.
- Preserve IDs, attribute values, nulls, relationships, CRS, and exact WKB bytes.
  Carry forward additional source fields and relevant schema metadata.
- Preserve graph and both snap artifacts byte-for-byte.
- Describe the delivered vector artifacts directly in the 0.4.0 manifest.
  Exclude raster declarations from this vector-only delivery.

Use `docs/selective-access-candidates.md` as the technical starting point. Its B
layout includes an uncompressed `id: int64`, `block: int32`, `row: int32` lookup;
an exact-ID range directory; Zstandard-compressed catchment batches; an 8 MiB
logical uncompressed batch budget with oversized rows alone; and artifact binding
for bounded mismatch checks. Finalize the experimental discovery and metadata
wording into a coherent released contract while preserving B's selected design.
Document exact batch-budget semantics and required reader behavior. Routine
contract details remain engineering work within this scope.

Limit the redesign to representation and access. Preserve the existing hydrologic
information and graph/snap contracts. Keep raster design and conversion for later.

## Source and destination

Source:
`https://basin-delineations-public.upstream.tech/grit/hfx-v0.3.0/`

Destination:
`https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0/`

The live source manifest reports 22,337,300 units, DAG topology, EPSG:4326, and
these artifacts. HEAD checks during discovery returned 200 with byte-range support:

| Vector artifact | Source bytes |
| --- | ---: |
| `catchments.parquet` | 32,508,030,908 |
| `graph.parquet` | 699,720,490 |
| `aux/snap_segments.parquet` | 3,674,757,248 |
| `aux/snap_reaches.parquet` | 6,478,991,001 |

The source also declares `aux/d8/flow_dir.tif` and `aux/d8/flow_acc.tif`.
Leave these raster files in the cloud and outside the new vector bundle.
Preserve applicable source identity, provenance, and attribution.

The destination manifest returned 404 during discovery. Verify the destination
prefix and actual R2 bucket/write configuration before publishing; the public URL
does not establish write access or prove the entire prefix is empty. Preserve all
existing cloud objects. Publish the new bundle as immutable data, with its manifest
made available after the referenced artifacts are ready. Keep credentials outside
Git. Any correction to a published bundle must preserve the identity guarantees
needed for consistent range reads.

## Local production and verification

Use small, strongly typed Python scripts in `scripts/` for conversion, validation,
and initial access tests. Follow repository uv, Ruff, ty, and test-first guidance.
Keep the work proportional to this delivery. A general-purpose toolkit, validation
CLI, reusable reader library, and package release are outside scope.

Work locally with the approximately 200 GB of free space available during discovery.
The vector source is approximately 43.4 GB. Download only the vector inputs and
required small metadata. Read and convert catchments incrementally. Graph and snap
files require no conversion or duplicate local copies. Determine output size and
monitor free space; available space is a planning assumption, not a size guarantee.
A VM is optional if transfer or resource conditions require it.

Verify the complete converted catchment information against independent source
reads, including IDs, attributes/nulls, schema semantics, and exact WKB. Check every
lookup address and directory range, unique ID coverage, and unchanged graph/snap
hashes. Keep validation bounded in memory and separate from consumer startup.
Use focused tests for addressing, absent IDs, batch boundaries, oversized rows,
and preservation. Reuse useful existing producer/verifier logic without expanding
this into a framework or retaining a requirement to produce candidate A.

Upload only verified vector output to the new prefix. Verify uploaded artifact
identities and test selective lookup and catchment reads through the public URL,
including real byte-range responses and consistent object identity. Demonstrate
access without eager worldwide catchment preparation. Bounded head/tail hashes
are mismatch checks; full producer/upload verification and immutable publication
provide the accompanying integrity evidence.

After conversion validation, upload verification, and public selective-read checks
pass, remove this work's downloaded sources and generated local bulk outputs.
Retain scripts, documentation, and a small verification record with source/output
identities, counts, commands, checks, and the published URL. Preserve pre-existing
local datasets and unrelated work.

## Evidence and delivery boundary

Relevant evidence:

- [Candidate contract](../../docs/selective-access-candidates.md).
- [Local candidate verification](../../docs/candidate-results.md).
- [Pourpoint reader work](https://github.com/pourpoint-tools/pourpoint/issues/3).
- [Reader experiments](https://github.com/pourpoint-tools/pourpoint/issues/19).
- Pourpoint's `experiments/catchment_read/results/README.md`,
  `http_results/README.md`, and `hetzner_results/README.md` describe local,
  loopback HTTP, and real object-store measurements. These are linked from the
  reader work and experiment records above.

The experiments support selective catchment access after requested IDs are known.
GRIT-scale conversion and public R2 access require verification in this delivery.
Full cold-start performance, graph preparation, snapping performance, and complete
delineation benchmarking belong to Pourpoint's subsequent work. Existing
HydroBASINS candidate artifacts carry redistribution restrictions and stay outside
this publication.

Delivery is complete when the concise vector specification and scripts are
available, verified GRIT 0.4.0 vector data is publicly readable at the new URL,
selective access has passed against that publication, the small verification record
is retained, and this work's temporary bulk files have been cleaned up. The existing
0.3.0 publication remains unchanged.
