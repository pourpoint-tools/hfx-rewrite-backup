# Reproduce

Use the committed `uv.lock`. `$SOURCE` is a complete, read-only copy of the pinned
GRIT publication. Bundles and receipts stay outside Git. `$REPORT` must exist;
choose new receipt names and output directories for every run. Fixed oracle JSON
in `results/` comes from independent original-source reads.

```sh
export SOURCE=/path/to/verified-original
export CANDIDATE=/path/to/unused-candidate
export REPORT=/path/to/receipts
export WORKLOADS=experiments/data_interface/results/workloads.json
export ORACLES=experiments/data_interface/results/archived-oracles.json
uv sync --locked --group data-interface
uv run --group data-interface python -m experiments.data_interface.build "$SOURCE" "$CANDIDATE" --report "$REPORT/build.json"
uv run --group data-interface python -m experiments.data_interface.verify "$SOURCE" "$CANDIDATE" --report "$REPORT/verify.json"
# Isolate block granularity without rebuilding nodes or relationships.
uv run --group data-interface python -m experiments.data_interface.build "$SOURCE" /path/to/unused-candidate-256 --rows 256 --family catchments --family rivers --no-relationships --report "$REPORT/build-256.json"
```

Run benchmarks in fresh processes, serially. Same-instance repeats are diagnostic,
not independent opening trials. Filesystem cache is uncontrolled. WKB decode needs
`--group vector-production` (Shapely); ordinary probes do not.

```sh
uv run --group data-interface python -m experiments.data_interface.record_probe "$CANDIDATE" --source "$SOURCE" --family rivers --workloads "$WORKLOADS" --selection scattered --columns id level bbox --report "$REPORT/records.json"
uv run --group data-interface --group vector-production python -m experiments.data_interface.record_probe "$CANDIDATE" --source "$SOURCE" --family catchments --workloads "$WORKLOADS" --selection clustered --columns id geometry --report "$REPORT/polygons.json"
uv run --group data-interface python -m experiments.data_interface.record_probe "$CANDIDATE" --source "$SOURCE" --family rivers --workloads "$WORKLOADS" --operation spatial --spatial-window small --level 0 --report "$REPORT/spatial.json"
uv run --group data-interface python -m experiments.data_interface.baseline_graph_spatial "$SOURCE" --family rivers --window small --workloads "$WORKLOADS" --report "$REPORT/isolated-graph.json"
uv run --group data-interface python -m experiments.data_interface.probe "$CANDIDATE" --family catchments --ids 8720 --relation component_river_ids --report "$REPORT/association.json"
uv run --group data-interface python -m experiments.data_interface.traversal_probe --bundle "$CANDIDATE" --seed 4 --direction downstream --strategy batch-cache --report "$REPORT/traversal.json"
uv run --group data-interface python -m experiments.data_interface.traversal_probe --bundle "$SOURCE" --seed 4 --direction downstream --strategy consumer --report "$REPORT/original-traversal.json"
uv run --group data-interface python -m experiments.data_interface.baseline_column_scan "$SOURCE/rivers.arrow" "$REPORT/scan.json" --columns source_length source_is_mainstem --mode projected --expected-rows 22337300
uv run --group data-interface python -m experiments.data_interface.association_probe --bundle "$CANDIDATE" --source "$SOURCE" --workloads "$WORKLOADS" --oracles "$ORACLES" --catchment 8720 --association component_river_ids --window small --report "$REPORT/association-workflow.json"
```

For node spatial reads use `--family river_nodes --operation spatial` and
`--node-spatial-oracle experiments/data_interface/results/source-node-spatial.json`.
That source-only inventory supplies the first-source-node window and exact tier
ID census; every fetched record is checked independently against original lookup.

Compare original and candidate using the same record command. Change family,
projection, `--selection clustered|scattered|overlap|absent`,
`--spatial-window small|elongated|large_amazon|empty|source_batch_boundary`, and
`--level` for retained cases. Use `--full` for every original field. Reopen by
repeating a CLI with a new receipt. Add the optional group only for geometry.

The retained combined river/catchment workflows use these exact shapes. Switch
`--window small` to `elongated`; repeat with `--strategy bulk`, or with
`--bundle "$SOURCE" --strategy consumer`, and always choose new receipt names:

```sh
export WORKFLOW_ORACLES=experiments/data_interface/results/workflow-oracles.json
uv run --group data-interface --group vector-production python -m experiments.data_interface.traversal_probe --bundle "$CANDIDATE" --family rivers --direction downstream --strategy batch-cache --workloads "$WORKLOADS" --window small --level 0 --record-columns id bbox geometry --decode-geometry --workflow-oracles "$WORKFLOW_ORACLES" --repeats 2 --report "$REPORT/workflow-rivers-small-batch-cache.json"
uv run --group data-interface --group vector-production python -m experiments.data_interface.traversal_probe --bundle "$CANDIDATE" --family catchments --direction upstream --strategy batch-cache --workloads "$WORKLOADS" --window small --level 1 --record-columns id bbox geometry --decode-geometry --workflow-oracles "$WORKFLOW_ORACLES" --repeats 2 --report "$REPORT/workflow-catchments-small-batch-cache.json"
uv run --group data-interface python -m experiments.data_interface.relation_baseline "$SOURCE/rivers.arrow" --column component_catchment_id --targets 8720 --repeats 3 --report "$REPORT/original-reverse-rivers-component_catchment_id-isolated.json"
```

For the remaining isolated reverse rows use the same command shape and this
artifact / scalar field / target list; each scans only ID plus that field before
building the numeric index:

| Artifact | Scalar field | Target IDs |
| --- | --- | --- |
| rivers.arrow | parent_id | 1 3 |
| rivers.arrow | upstream_node_id | 2 200 |
| rivers.arrow | downstream_node_id | 2 200 |
| river-nodes.arrow | coarser_node_id | 1 |
| rivers.arrow | local_catchment_id | 82558 |
| catchments.arrow | parent_id | 1 |

For the retained local association composition change the association command to
`--catchment 82558 --association local_river_ids --window small --geometry` and
add the optional geometry dependency group. The retained component composition
uses `--catchment 8720 --association component_river_ids --window large_amazon`
without geometry and yields no records. This is explicit association∩bbox, not
basin delineation.

Traversal strategies are `selective`, query-owned `batch-cache`, projected `bulk`,
whole-artifact `bulk-file`, original projected `consumer` and original whole-graph
`consumer-file`; upstream seed `1233924` is the large case. Workflow options
in `traversal_probe --help` combine independent spatial seeds, supplied membership,
and requested records. The isolated `baseline_graph_spatial` command keeps one Parquet reader from timed
opening through selection, separately from complete-record fetch; the as-used
record path reopens graph metadata. Both share the same projected graph selection
helper, not duplicated pruning algorithms. `relation_baseline --help` measures original scalar-column
projection, reverse-index preparation and association query separately. These are
bounded composition experiments, not delineation. The report explains when graph
footer reuse changes the fair original comparison.

Oracle regeneration is source-only and can scan globally. Never overlap it with
measurements:

```sh
uv run --group data-interface --group vector-production python -m experiments.data_interface.oracles.establish_workloads "$SOURCE" --report "$REPORT/workloads.json"
uv run --group data-interface python -m experiments.data_interface.oracles.catchment_flow_oracle "$SOURCE" --workloads "$WORKLOADS" --report "$REPORT/catchment-workflows.json"
uv run --group data-interface python -m experiments.data_interface.oracles.source_node_spatial "$SOURCE" --report "$REPORT/node-spatial.json"
uv run --group data-interface pytest -q experiments/data_interface tests/test_data_interface_relationships.py
uv run --group data-interface ruff check experiments/data_interface tests/test_data_interface_relationships.py
uv run --group data-interface ty check -c 'src.include=["experiments/data_interface", "tests/test_data_interface_relationships.py"]' experiments/data_interface tests/test_data_interface_relationships.py
```

`results/measurement-source-hashes.json` preserves preintegration source hashes.
Packaging changed imports, paths, formatting and optional geometry imports. The
isolated comparator's row-group selection is now shared with as-used Access and
adds logical materialization accounting; authoritative result IDs are unchanged.
The original comparator had the same projection and retained-reader timer boundary.
The existing report timings belong to the preserved preintegration hashes, not
new performance claims for refactored code. Source-preservation verification added
independent categorical/schema checks in commit `1f3a2ce`; the same commit coarsened
future scratch census instrumentation. Source meaning/schema audits passed both
unchanged measured manifests. Workflow receipts now bind the exact workload/oracle file hashes and source
manifest; source mismatches reject. Scan/reverse/comparator CLI reports cannot be
written into an input bundle. Standalone scan/reverse provenance reads the exact
parent manifest and artifact declaration outside timing; this is not a hidden
full-file hash. Legacy raw receipts remain pre-repair evidence.
The final integration commit binds the packaged code
and results through Git; do not relabel old receipts with new code hashes. Source-only witness helpers now also include catchment
records instead of a second machine-specific script. The duplicate generic
record/bbox CLI was removed from `probe`; its relationship CLI and `Access` API
remain. Legacy selective-relationship receipts wrongly label an adjacency block
as both lookup and data; current code classifies it only as data. Actual serialized
bytes were never doubled. Retain legacy evidence rather than rewriting receipts.

## Actual HTTP reproduction

The measured temporary candidate prefix is **deleted**. To repeat HTTP work, obtain
approval for a new empty experiment-only prefix and retention/cleanup plan. Publish
the verified bundle without byte changes, artifacts first and manifest last. Record
local SHA-256/length, uploaded object identity/HEAD and public readback before running
probes. Keep the exact owned-key/ETag ledger outside Git. The private upload helper
is not part of this experiment; use approved object-storage tooling, not production
prefixes. Delete only owned matching-ETag keys afterward, verify their absence and
an empty prefix/no pending multipart uploads, and compare the original manifest.
The [historical lifecycle receipt](results/remote-lifecycle.json) documents what ran.
Never place credentials, profiles, datasets or full request logs in Git.

Use a local verified `$SOURCE` for independent record validation and an HTTP root
as the target. Actual remote counts cover returned successful response bodies, not
wire bytes, headers, failed requests or lower-layer retries. No local/loopback result
substitutes for remote evidence; cache/CDN/network state is uncontrolled.

```sh
export SOURCE_HTTP=https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0-rivers-2026-10-12
export CANDIDATE_HTTP=https://your-approved-host/new-empty-experiment-prefix
export SOURCE_SHA=b9a38083131dcf1a4c7c4e73ebe9a97dff2a4b7ef91a8df53f8bc38cadfa48db
uv run --group data-interface python -m experiments.data_interface.record_probe "$CANDIDATE_HTTP" --source "$SOURCE" --family catchments --workloads "$WORKLOADS" --selection clustered --columns id level bbox --repeats 2 --report "$REPORT/remote-catchments-projected.json"
uv run --group data-interface python -m experiments.data_interface.traversal_probe --bundle "$SOURCE_HTTP" --seed 1233924 --direction upstream --strategy consumer-file --repeats 2 --source-manifest-sha256 "$SOURCE_SHA" --oracles "$ORACLES" --report "$REPORT/remote-original-flow.json"
uv run --group data-interface python -m experiments.data_interface.traversal_probe --bundle "$CANDIDATE_HTTP" --seed 1233924 --direction upstream --strategy bulk-file --repeats 10 --source-manifest-sha256 "$SOURCE_SHA" --oracles "$ORACLES" --report "$REPORT/remote-bulk-10.json"
uv run --group data-interface python -m experiments.data_interface.traversal_probe --bundle "$CANDIDATE_HTTP" --seed 1233924 --direction upstream --strategy batch-cache --repeats 10 --source-manifest-sha256 "$SOURCE_SHA" --oracles "$ORACLES" --report "$REPORT/remote-cached-10.json"
```

The two ten-query commands ran bulk-file first, then batch-cache, in separate
processes. Sum opening+preparation+actual query phase prefixes for cumulative
comparison, not receipt wall time. Query-owned batch reuse clears adjacency each
query; whole-file keeps the projected global graph resident. `bulk-file` acquires
all relationships, not only requested fields; `consumer-file` acquires the original
graph. Both pin identity and verify full SHA-256/length before local projection and
numeric preparation, all inside preparation time. Temporary downloaded files are
owned and removed by the probe. Existing opening GETs are counted, not optimized away.
For small flow use seed `4`, downstream, two repeats. Repeat the earlier combined
workflow commands with HTTP roots and original `consumer-file`; add
`--source-manifest-sha256 "$SOURCE_SHA"`. Record comparisons use the same columns,
source witness and optional geometry dependency group on both layouts.

### Reproduce partial diagnostics only

The exact measured one-off wrapper is archived as
`results/remote-bounded-diagnostic.py.txt`; it is not a reader API. Copy it outside
the repository, beside fresh output receipts. It caps **successful HTTP.get calls
across all instances**, serializes transport and stops before call 129. Exit 3 is
an expected resource stop, not a completed query or a performance test failure.
The cap is a resource budget, never a completion-time estimate. The unchanged
wrapper records its SHA-256, actual successful response bodies and failure status.

```sh
cp experiments/data_interface/results/remote-bounded-diagnostic.py.txt "$REPORT/run_bounded_remote.py"
PYTHONPATH=. uv run --group data-interface python "$REPORT/run_bounded_remote.py" experiments.data_interface.traversal_probe --diagnostic-report "$REPORT/remote-selective-partial.json" --max-requests 128 -- --bundle "$CANDIDATE_HTTP" --seed 4 --direction downstream --strategy selective --repeats 2 --source-manifest-sha256 "$SOURCE_SHA" --oracles "$ORACLES" --report "$REPORT/unfinished-driver.json"
```

Use `bulk` for projected candidate preparation or `$SOURCE_HTTP`/`consumer` for
original projected preparation; repeat large upstream seed `1233924`. The two
original Amazon partials wrap `experiments.data_interface.record_probe` with
`"$SOURCE_HTTP" --source "$SOURCE" --family rivers` (then catchments),
`--workloads "$WORKLOADS" --operation spatial --spatial-window large_amazon
--columns id level bbox --repeats 1 --report "$REPORT/unfinished-records.json"`.
Always choose fresh wrapper and driver report names. Keep capped receipts separate
from completed results; partial response bodies do not imply equal progress.

## Current workload and workflow probes

See the [current physical-layout findings](PHYSICAL_LAYOUT.md) and
[local receipt summary](results/physical-layout-local.json). Remote conclusions
and the final recommendation are still pending.

These commands use the current reader, not the historical receipt revision.
Generate the new witness file outside the source bundle and repository; the
original witness entries remain unchanged. The medium square has radius 0.1°;
the two many-record selections use 4,096 actual source row ordinals. These are
investigation settings, not production layout constants.

```sh
uv run --group data-interface python -m experiments.data_interface.oracles.extend_workloads "$SOURCE" --workloads "$WORKLOADS" --catchment-records experiments/data_interface/results/catchments-records.json --report "$REPORT/extended-workloads.json"
uv run --group data-interface python -m experiments.data_interface.record_probe "$CANDIDATE" --source "$SOURCE" --family rivers --workloads "$REPORT/extended-workloads.json" --operation spatial --spatial-window medium --columns id source_global_id --report "$REPORT/medium-records.json"
uv run --group data-interface python -m experiments.data_interface.record_probe "$CANDIDATE" --source "$SOURCE" --family rivers --workloads "$REPORT/extended-workloads.json" --selection many-scattered --columns id source_global_id --report "$REPORT/many-records.json"
uv run --group data-interface --group vector-production python -m experiments.data_interface.traversal_probe --bundle "$CANDIDATE" --source "$SOURCE" --strategy batch-cache --window small --level 0 --workloads "$WORKLOADS" --workflow-oracles experiments/data_interface/results/workflow-oracles.json --record-columns id source_global_id geometry --decode-geometry --repeats 2 --report "$REPORT/workflow-records.json"
```

Workflow `--source` is required for independent exact projected-record equality.
Validation runs after timed fetch/decode, can warm local source files before
repeats, and contributes to lifetime peak RSS. Each phase's `total_transport`
includes all distinct adjacency, feature and connectivity-check Access instances:
first-use counters include opening/preparation; repeats report deltas. The final
`total_transport` is cumulative. Existing namespaced phase metrics remain separate.
Use the same optional `--read-ahead-bytes N` on compared workflow commands; the
default is zero. Original `consumer` now enables Parquet pre-buffering, with all
projected graph acquisition and numeric preparation still inside first use.
These drivers do not establish a remote performance or physical-layout result.
