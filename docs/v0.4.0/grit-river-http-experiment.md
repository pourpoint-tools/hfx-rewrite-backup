# GRIT selective HTTP experiment

On 2026-10-12, the independently verified GRIT component sample passed selective
public HTTP reads on Hetzner Object Storage. This establishes small-sample remote
addressing and row fidelity, not worldwide GRIT delivery or delineation performance.

Historical sample URL (removed after final delivery): <https://pourpoint-hfx.fsn1.your-objectstorage.com/experiments/hfx-0.4.0-rivers-2026-10-12/>

[Receipt](receipts/grit-river-http-experiment.json) retains object identities,
manifest binding, request ranges and phase measurements. Manifest SHA-256:
`ea15082eaddc7bd043fba4e84581a48875ab78a2f6c2ed91b6d37c42b34215fd`.

The maintainer authorized proceeding with the isolated experiment. The destination
was empty; each new object used `If-None-Match: *`. Fifteen artifacts plus the
manifest total **1,896,207 bytes**. Every uploaded object passed a public full GET
with identity encoding, its PUT ETag pinned by `If-Match`, and byte-for-byte
comparison with the independently verified local sample. Artifacts were uploaded
and checked first; the manifest was uploaded last. Public-read ACLs were applied
only to these new objects. No bucket ACL/policy or existing bundle was changed.
No rasters were copied or processed.

## Selective reads

The probe at commit `1c3bb5d7ffa072f15b34eddacf8db8c51d203125` requested IDs
`1`, `513` and absent ID `9223372036854775807` in each artifact. IDs 1 and 513
matched complete local IPC rows, including schema metadata, attributes, nulls and
WKB. The absent ID was correctly reported missing. Local comparison was outside
timed remote access and used the already independently verified sample, not a
fresh native-source scan during startup.

| Artifact | Phase | Requests | Body bytes | Seconds | Selected data batches | Touched / fully fetched data batches |
| --- | --- | ---: | ---: | ---: | --- | --- |
| catchments | preparation | 5 | 159100 | 2.895033 | none | 0,4 / none |
| catchments | first_access | 2 | 663280 | 1.835667 | 0,2 | 0,2 / 0,2 |
| catchments | repeated_access | 2 | 663280 | 1.884678 | 0,2 | 0,2 / 0,2 |
| rivers | preparation | 5 | 159028 | 2.992612 | none | 0,3,4 / 4 |
| rivers | first_access | 2 | 295320 | 1.738275 | 0,2 | 0,2 / 0,2 |
| rivers | repeated_access | 2 | 295320 | 1.575518 | 0,2 | 0,2 / 0,2 |
| river_nodes | preparation | 5 | 158740 | 3.150516 | none | 0,1,2,3,4 / 0,1,2,3,4 |
| river_nodes | first_access | 0 | 0 | 0.047142 | 0,2 | none / none |
| river_nodes | repeated_access | 0 | 0 | 0.000717 | 0,2 | none / none |

Every preparation fetched the single lookup batch completely. Both selections
used that lookup batch with no further lookup request. Data batch numbers are
zero-based; each artifact has five batches. A touch means any received byte
overlaps record-batch metadata/body. Fully fetched means the union of that phase's
responses covers the complete extent. These counts include preparation overlaps,
not just requested data batches.

Repeated access retains preparation buffers and IPC metadata but adds no selected
batch cache. **All node bytes were already received during preparation.** Zero
later node requests is not evidence of instant remote retrieval. Reported bytes
are response bodies, not wire overhead. Times include probe selection/receipt
work and are single observations, with no latency target or global-scale claim.
See [probe semantics](selective-http-probe.md).

Historical read command (the experimental prefix was removed on 2026-10-16):

```sh
uv run python scripts/check_vector_access.py \
  https://pourpoint-hfx.fsn1.your-objectstorage.com/experiments/hfx-0.4.0-rivers-2026-10-12/ \
  --artifact rivers --ids 1 513 9223372036854775807 \
  --source /path/to/independently-verified-sample --report /path/outside-sample/river-http.json
```

Repeat with `--artifact catchments` and `--artifact river_nodes`. Full upload
identity verification is separate from this bounded selective read command.
Original upload logs, script and probe receipts remain in the session evidence;
the committed receipt records their hashes and compact results.

After [full GRIT delivery](grit-river-delivery.md) passed, the isolated prefix was
removed on 2026-10-16. All 16 keys, sizes and ETags matched this receipt before
deletion; all deletes succeeded and the prefix listing was empty afterward.
No bucket or other objects were removed. The receipt preserves the experiment
and its GRIT v1.0 attribution/CC BY-NC 4.0 evidence; this URL is not a permanent
production endpoint.
