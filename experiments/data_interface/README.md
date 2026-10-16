# Data interface experiment

Proposed contract sketch, not a normative HFX revision or supported reader.
See [measured findings](REPORT.md) and [portable reproduction commands](REPRODUCE.md).
Input is the immutable GRIT river delivery pinned by manifest SHA256
`b9a38083131dcf1a4c7c4e73ebe9a97dff2a4b7ef91a8df53f8bc38cadfa48db`.

Each catchment, river and source-node domain has one feature IPC file containing
all original authoritative fields, exact WKB, native types, nulls and metadata.
Projection makes bounds, structural fields, source attributes and geometry
independently readable; complete records need no attribute/geometry join.
IDs and tiers remain separate per domain. New row order does not change IDs.

Physical feature order is `(level, Morton(bounds center), id)`. Morton coordinates
use 16 bits per axis over longitude [-180,180] and latitude [-90,90]. It is a
locality heuristic, not geographic selection. Maximum feature batches are 8,192
rows and 8 MiB logical Arrow bytes; oversized single rows remain intact. IPC
buffers use Zstandard. A published conservative union envelope per batch supports
first-stage geographic discovery; projected per-feature bounds refine candidates.
A sorted `(id,block,row)` IPC lookup supports sparse known-ID access. An ID range
directory permits selective lookup-batch reads. Bounds overlap is inclusive and
returns candidates, never exact geometry selection.

Separate ID-sorted Arrow adjacency tables publish immediate neighbors as typed
`list<int64>` columns, not Python snapshots or transitive closure. Catchments have
parent/children, supplied upstream/downstream, and separately local/component
associated rivers. Rivers have parent/children, supplied upstream/downstream,
directed upstream/downstream nodes and local/component catchments. Source nodes
have coarser/finer correspondence and incoming/outgoing rivers. Each column declares
its target domain and authoritative source column. Shared nodes do not imply
additional flow edges. Catchment component connectivity remains `not_supplied`.
Forward scalar references and source graph lists remain authoritative; reverse
adjacency is a derived, verified access structure. Empty lists do not classify
natural termination or erase null/unknown source semantics.

The experiment manifest binds exact input manifest/artifact SHA256 identities and
all derived artifacts. Address directories bind their addressed file, spatial
bounds bind physical feature batches, and adjacency declarations identify source
artifacts. Schema metadata and categorical meanings retain their original roles.
Full producer verification is separate from ordinary selected ID/address checks.
HTTP probes use identity encoding, 206 range validation and pinned strong ETags;
bounded fingerprints are not full interior authentication.

Baseline comparisons must include both original full-batch use and top-level IPC
projection. `IpcReadOptions(included_fields=...)` can avoid WKB buffer reads even
in the original combined layout. Report request counts and overread, not just
retained values. The new batch caps and Morton quantization are experimental
constants, not selected production requirements. No public uploads or production
reader changes are authorized here.

## Commands

Run from the repository root with the committed lock:

```sh
uv run --group data-interface python -m experiments.data_interface.build   /path/to/verified-input /path/to/unused-candidate --report /path/outside-candidate/build.json
uv run --group data-interface python -m experiments.data_interface.verify   /path/to/verified-input /path/to/candidate --report /path/outside-candidate/verification.json
uv run --group data-interface python -m experiments.data_interface.record_probe   "$CANDIDATE" --source "$SOURCE" --family rivers --workloads "$WORKLOADS"   --columns id source_global_id --report "$REPORT/records.json"
uv run --group data-interface python -m experiments.data_interface.probe   /path/to/candidate --family rivers --ids 4 --relation downstream_ids   --report /path/outside-candidate/neighbors.json
```

The record probe also accepts a public immutable HTTP bundle URL and
`--operation spatial --spatial-window small` with optional `--level`.
Immediate relationships use the smaller `probe --relation` command. HTTP requires explicit approval for any experimental
upload destination; building locally does not grant that approval. The full
producer build hashes needed source files against the pinned manifest before
reading them. It refuses an existing output directory. Failures remain visible;
never silently resume or overwrite them.

The build uses DuckDB 8 GB memory limit/one thread (insertion-order preservation disabled) and external spill beside the
candidate. This is not a bound on total process memory. Scratch bytes sampled
before output, every 1,024 emitted batches and after output are an observed maximum, not a precise
peak trace. The verifier uses the same bounds and temporary directories beside
the candidate, never repository build directories. Full row sorting compares
original/candidate Arrow rows after restoring the original schema.

By default, access probes retain Arrow metadata and bounded HTTP fingerprint
buffers, not selected feature batches. Original graph reads enable Parquet
`pre_buffer=True`; `record_probe --no-graph-pre-buffer` disables it. The default gives Arrow all selected groups together and streams projected
batches with `iter_batches`, allowing coalescing across row groups without
materializing the entire selected projection at once. `--no-graph-grouped` instead
reads one projected row group at a time. `graph_max_buffer_bytes` reports the
largest materialized batch, not the serialized Parquet pre-buffer cache.
Arrow's default lazy cache options apply; this does not promise parallel HTTP reads.
`--read-ahead-bytes N` opts into a standard seekable IPC buffer of N bytes per open
IPC file. It can reduce round trips at the cost of extra transfer (including WKB
between requested fields) and same-instance serialized-data reuse. The default is
zero. These are reader comparisons, not changes to artifact layout or batch caps. Their local byte/call counters count serialized reads,
not physical disk traffic; filesystem cache is uncontrolled. Remote counts are
actual response bodies/ranges, not wire bytes. The current reader discovers schema from the leading IPC schema message, opens
one projected data reader, and reuses spatial and original Parquet readers within
an instance. Historical receipts in `results/` and REPORT.md measured the earlier
reader, which opened the data footer twice and reopened spatial readers; reproduce
those exact reader policies from the receipt's Git revision. Geometry receipt
is separate from optional Shapely decode (add `--group vector-production`). Full
producer checks are separate from ordinary reader address/digest-binding checks.
The fixed experiment input supplies all three domains; this probe is not a general
optional-node reader. Native source columns/nulls stay authoritative regardless of
which derived relationship columns a particular operation projects.


For comparable current-reader trials, use the same options on original and
candidate bundles. For example, add `--graph-grouped --read-ahead-bytes 65536`
to a spatial `record_probe` command, then compare with `--no-graph-pre-buffer --no-graph-grouped`
and without read-ahead. This 64 KiB value is an explicit trial setting, not a
selected production constant. Opening and first discovery remain counted.

### Resource adjustment

The first global catchment sort exhausted DuckDB's 2 GB pool before emitting any
feature file. The failed output directory is retained with its failure receipt.
The next build uses an 8 GB DuckDB pool, one thread and
`preserve_insertion_order=false`. Explicit total sorting makes source insertion
order irrelevant. These are build settings, not an 8 GB total-process promise;
whole-process RSS and actual spill observations are reported separately.

Feature buffers use Zstandard; relationship IPC is uncompressed. The initial
measured candidate manifest used the ambiguous field `compression: "zstd"` for
features. Its immutable bytes are retained; future builds name both compression
choices explicitly. Per-artifact decoding determines the actual encoding.
