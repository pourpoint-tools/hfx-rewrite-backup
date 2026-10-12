# Selective HTTP probe

`check_vector_access.py` is an experiment, not a supported reader. Choose
`--artifact catchments`, `rivers`, or `river_nodes`; catchments is the default.
It reads one manifest snapshot and the selected declaration's data, lookup and
directory. Other artifacts, graphs and original source files are not read remotely.

```sh
uv run python scripts/check_vector_access.py "$BUNDLE_URL" \
  --artifact rivers --ids 1 513 --source /path/to/verified-sample \
  --report /path/outside-sample/river-access.json
```

`--source` accepts local IPC or Parquet, or a local bundle directory. Compare
against a sample already independently verified with `verify_grit.py`; equality
with local delivered rows alone does not prove original-source fidelity. Complete
selected schemas, metadata, values, nulls and WKB are compared outside the timed
HTTP phases. First and repeated selections must also match completely.

The report separates preparation, first selection and repeated selection. Each
phase records elapsed time, requests and received body bytes. Preparation includes
manifest, fingerprints, full directory and IPC metadata. Repeated selection retains
those buffers and metadata but adds no selected-batch cache. It is **not** a warm
consumer-cache benchmark. Row receipt hashing is included in selection time.

Selected batches are logical requests. `touched_*_batches` are actual network
response overlaps with record-batch metadata/body extents from the IPC footer;
even partial overlap counts. Preparation can touch unselected batches, and a
selected batch already inside a fingerprint buffer needs no further request.
These counts do not claim entire batches were fetched. `fully_fetched_*_batches`
separately counts extents entirely covered by the union of responses in that
phase. `batch_spans` records half-open byte extents. Raw request ranges remain
in the report. Schema/footer bytes and non-IPC files contribute to body bytes but
not record-batch counts. Dictionary dependencies, if supplied, are included in
request bytes, not counted as record batches.

Strong ETags pin each object's transport version; the report retains manifest
SHA-256 and ETag. Head/tail checks and directory full hashing do not establish
full interior artifact integrity. Full producer/upload verification and a trusted
manifest on immutable objects remain necessary. No HTTP latency threshold applies.

## Local original-source sample, 2026-10-12

The independently verified GRIT component sample from the producer/verifier work
was served by a loopback HTTP server honoring identity byte ranges and strong
SHA-256 ETags. IDs 1 and 513 selected batches 0 and 2 of five data batches. All
selected rows matched their local IPC source completely.

| Artifact | Preparation requests / body bytes | First requests / body bytes | Repeated requests / body bytes |
| --- | ---: | ---: | ---: |
| Catchments | 5 / 159100 | 2 / 663280 | 2 / 663280 |
| Rivers | 5 / 159028 | 2 / 295320 | 2 / 295320 |
| River nodes | 5 / 158740 | 0 / 0 | 0 / 0 |

Preparation touched catchment batches 0,4; river batches 0,3,4; and all five node
batches. Preparation fully fetched no catchment batches, river batch 4 and all
node batches. First/repeated network reads fully fetched catchment and river
batches 0,2.
The small node artifact was already covered by preparation buffers, so zero later
requests is not evidence of a selected-batch cache. All lookup batches were also
inside preparation buffers. Approximate preparation/first/repeated times were
10.6/21.9/7.2 ms for catchments, 4.3/3.1/2.9 ms for rivers and 3.5/0.7/0.5 ms for
nodes; these are one local run, not network-service or delineation performance.

Receipts and the loopback reproduction script are retained in the implementation
session's evidence directory. Tests use a separate synthetic HTTP fixture with a
large unselected batch, corrupted transports, path escapes and incorrect bindings.
No remote prefix was written. Isolated remote and public R2 measurements remain
required after exact destination approval; this small run cannot prove global
performance or complete GRIT delivery.
