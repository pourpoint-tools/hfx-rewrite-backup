# HFX selective-access candidates

Produce two experimental HFX 0.4.0 candidates from copies of the existing local
HydroBASINS bundle. Give the maintainer actual datasets and a precise file contract
so a separate effort can build readers and benchmark them. Preserve the originals.
These are experimental alternatives, not an approved HFX release.

Related research: [HFX issue #1](https://github.com/pourpoint-tools/hfx/issues/1).
This is a standalone vision, not a Program Effort. Its scope is narrower than the
issue's research agenda: **produce candidates, not readers or benchmarks**.
It does not resume Pourpoint Effort #3 or change Pourpoint's current input contract.

## Why this work exists

Once Pourpoint knows the upstream drainage-unit IDs, it should be able to locate
their polygons and attributes without scanning all catchment IDs or rebuilding a
global lookup. Publish that lookup with the dataset, organized so a reader can
retrieve only the relevant portions locally or through remote byte-range reads.
Runtime preparation should add little overhead beyond reading and decoding;
this is a design objective, not a performance claim or numerical acceptance gate.

The recorded GRIT initialization took 22.7 minutes with the graph already cached,
including 5,458 preparation requests and about 1.25 GB of response payload. This
was global preparation, not complete delineation timing and not evidence that
WKB decoding is the bottleneck. See the
[pause report](https://github.com/pourpoint-tools/pourpoint/issues/3#issuecomment-6026921887).
Prioritize eliminating expensive prerequisites and unnecessary data access rather
than speculative millisecond savings.

## The two candidates

| Component | Candidate A: published index | Candidate B: index + Arrow catchments |
|---|---|---|
| Catchment data | Preserve existing Parquet bytes | Store attributes and WKB polygons in Arrow IPC file-format record batches |
| Lookup | ID-sorted Arrow IPC index | ID-sorted Arrow IPC index |
| Address | Catchment artifact, row group, row position | Catchment artifact, record batch, row position |
| Connectivity and snap artifacts | Unchanged | Unchanged |

Use established formats rather than a custom binary format. HFX defines the index
schema, discovery metadata, and block organization around them. Use the Arrow IPC
**file** format, not a stream-only layout, so the footer locates record batches.

Both indexes contain unit IDs in sorted order and their record addresses, divided
into independently readable batches. Publish a small directory that maps ID ranges
to index batches. Specify how a reader discovers the directory, the relevant index
batches, and addressed data blocks. A reader must not need to scan catchments or
load the complete index just to locate a requested ID. The mechanism must support
arbitrary positive dataset-local IDs, not assumptions about contiguous IDs,
HydroBASINS ID encoding, or IDs matching physical row positions.

Use uncompressed index batches initially so loaded numeric arrays do not require
decompression or construction of a global dictionary. Keep the directory compact
and avoid making its discovery depend on reading the whole index. Define how to
combine lookups for a set of IDs into shared block reads; document the access
sequence without implementing a production reader.

For Candidate B, preserve current catchment order initially. Size batches using a
byte budget, not just a row count, because polygon sizes vary widely. Document the
budget, whether it applies before or after compression, and the handling of a
single oversized polygon. Preserve all existing catchment attributes, types,
nulls, unit identities, relationships, coordinate reference information, and
**exact WKB bytes**. Keep geometry and attributes addressable together by unit ID.
Candidate B compression, exact schemas, directory encoding, batch budgets,
artifact names, and sharding are reversible engineering choices for the producer;
document the choices precisely rather than reopening the format decision.

Bind each index to the exact artifacts and layout it addresses. Define a practical
way to identify mismatched artifacts without requiring a client to hash or scan the
whole dataset at startup. Producer-side full-file hashes are appropriate evidence.
Rewriting an addressed artifact requires rebuilding its lookup.

An index does not guarantee a one-row physical read. Candidate A retains Parquet's
read and decode granularity. Candidate B explores different block granularity and
runtime-friendly attribute arrays. WKB may still require geometry-library decoding.
Neither candidate promises zero-copy geometry or proven remote performance.

## Source data and preservation

The complete local source bundle is at:

```text
/Users/nicolaslazaro/.prime/agent/session-artifacts/01a1129b-ff00-7678-9ab2-c76e53fe810a/vector-access/data/hydrobasins/
```

It contains `manifest.json`, `catchments.parquet`, `graph.parquet`,
`aux/snap_stems.parquet`, validation reports, and `ATTRIBUTION_AND_PROVENANCE.txt`.
It has 3,786,228 units across source Pfafstetter levels 1–12, represented as HFX
levels 0–11, and tree topology. The snap layer references level 11.
The catchments file is 3,703,151,810 bytes with 924 row groups. Its first geometry
column chunk is about 170 MB compressed: locating a row alone does not establish
cheap polygon retrieval.

Write two separate complete output bundles outside Git at:

```text
/Users/nicolaslazaro/.prime/agent/session-artifacts/hfx-candidates/hydrobasins/candidate-a-index/
/Users/nicolaslazaro/.prime/agent/session-artifacts/hfx-candidates/hydrobasins/candidate-b-arrow/
```

If either destination already contains data, inspect and preserve it rather than
overwriting unrelated or uncertain artifacts. Never modify source files in place.
Preserve attribution and provenance in both outputs. The bundle's license notice
prohibits public/open redistribution as a stand-alone product and marks this
compiled derivative for internal use. Do not upload these candidates or change
remote datasets. Clearly label experimental candidate identity and document its
manifest interpretation; do not masquerade as unchanged conformant HFX 0.3.0 or
publish a final 0.4.0 contract.

The local reference repository is `../deprecated/hfx`; its `spec/HFX_SPEC.md`
matches the pinned 0.3.0 reference linked from this repository's README. Consult it
for source semantics, not as a requirement to preserve the old toolkit. This
repository is intentionally lean and currently has only Python scaffolding. Keep
producer code and documentation proportional to these two candidates. Use uv,
strongly typed Python, Ruff, ty, and small test-first increments for supporting code.

## Deliverables and correctness evidence

Deliver both complete local candidate bundles, minimal reproducible producer
commands, and repository documentation sufficient for an independent reader author.
Record the output paths, source identity, schemas, manifest/discovery rules, index
address semantics, ordering, compression, batch organization, artifact binding,
and distinctions between the candidates. Bulk data remains outside Git.

Verify producer correctness without expanding into a reader or benchmark project:
- Establish that source artifacts remain unchanged and retain their attribution.
- Account for every source unit exactly once in each candidate's lookup; verify
  addresses refer to the correct records using independent source evidence.
- Verify Candidate A preserves the original data artifacts byte-for-byte.
- Verify Candidate B preserves attributes, nulls, relationships, and exact WKB bytes
  keyed by unit ID; verify unchanged graph and snap artifacts in both bundles.
- Cover non-contiguous and shuffled IDs, batch boundaries, and oversized geometry
  handling with focused small fixtures. Document absent-ID behavior and ensure the
  directory cannot route a valid ID away from its index entry.

Small producer tests and bounded verification reads are in scope. A reusable
consumer API, Pourpoint integration, performance harness, latency targets, remote
performance experiments, and reader implementation are not. Do not turn verification
into an alternate engine. Record format facts, not unsupported speed claims.

Upstream membership discovery, graph redesign, snapping policy, rasters, and
GeoArrow coordinate-array geometry are excluded. The clicked unit may differ from
the snapped unit; the snap target's unit ID starts traversal. This work begins
**after traversal has supplied upstream IDs** and does not solve that earlier step.
The HydroBASINS fixture does not establish performance or general graph behavior at
GRIT scale. GeoArrow can be reconsidered later if the maintainer's measurements
show significant geometry decoding or materialization costs.

## Short handoff for the reader-design agent

**Candidate A — published index:** Existing HFX 0.3.0 data files plus an ID-sorted
Arrow IPC lookup mapping unit IDs to catchment row groups and row positions. A
small directory supports selective index reads without scanning all catchment IDs
or loading the whole index.

**Candidate B — published index + Arrow catchments:** The same lookup mechanism,
with catchment attributes and unchanged WKB polygon bytes stored in independently
readable Arrow IPC batches organized by a byte-size budget. Preserve catchment
order initially. Connectivity and snap data remain unchanged.

Both start with known upstream IDs. A removes global client-side lookup construction;
B also explores finer retrieval granularity and less attribute conversion. Neither
promises zero-copy geometry or measured speed. The maintainer owns the subsequent
reader design and benchmarking effort.
