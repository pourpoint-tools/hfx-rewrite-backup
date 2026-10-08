# GRIT 0.4.0 vector verification

Published and verified on 2026-10-07 (UTC):
<https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0/>.
The [vector contract](vector-data.md) describes the files. Source:
<https://basin-delineations-public.upstream.tech/grit/hfx-v0.3.0/>.

Production used commit `5d2cc83d077772e2633a1545d214d975761aa01b`, Python
3.13.14, PyArrow 25.0.1 and the committed uv lock. The publication contains
12 objects totaling **30,577,536,134 bytes**, including the manifest.
All **22,337,300** catchments and lookup addresses passed full verification:
**6,657** catchment batches and **341** lookup batches.

## Identities

SHA-256 values below identify complete files. Graph and both snap artifacts have
the same source and published identities. The public manifest also records every
attribution/provenance artifact and bounded head/tail hashes.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Source `catchments.parquet` | 32,508,030,908 | `50c987343181af8a848170cf121571e7ae815ac491b93bcf9cc07a04a9e12c59` |
| Source manifest / `source-manifest.json` | 1,426 | `02339ff92cbfd1d2ea57bb5332cb843b98115cd7a7395f64c14fac78d2ed643c` |
| `catchments.arrow` | 19,366,525,978 | `a3210898c54180da509d93566b9b4c45f93994edac51fd8bd675925982e51068` |
| `lookup.arrow` | 357,487,690 | `681d612eded3b64cae23f65dc31e9827a22a9918193e800290bf3605907952e6` |
| `lookup-directory.json` | 35,390 | `7b3bd3f66cea8ef422deae2f58c9fb15df7b1c26cd7be29459312150acc36d70` |
| `graph.parquet` | 699,720,490 | `8f61a64fb6746213638655053118eb47c939a4f89796f4a1ef017ab0fd923e81` |
| `aux/snap_segments.parquet` | 3,674,757,248 | `cab39a2be4333cdd8e9a02b78186fa6f6ff3d55c761e670e7104605eeab4dda3` |
| `aux/snap_reaches.parquet` | 6,478,991,001 | `afd994adb2fbfdf25e09dc51b4e1441eb74e34ed5647a6a5b3b4e2a67dc9dfc3` |
| Published `manifest.json` | 4,943 | `fb6f93472cffe5868fb6595de725936c9fd881caa7534700fd6bc8d1fde286a6` |

## Checks

- Source vectors and manifest matched the full hashes published in the source
  README. The complete source cloud inventory retained its original sizes and
  ETags after publication. The 0.3.0 objects and raster files were unchanged.
- Independent Parquet reads matched every converted catchment value, null, field,
  schema metadata item and exact WKB byte sequence. Checks covered source order,
  maximal source-slice byte budgets, oversized rows and 4096-row boundaries.
- Every lookup address resolved to its stated ID. IDs were positive, unique and
  sorted; coverage and directory ranges were complete. IPC message metadata
  confirmed Zstandard catchments and uncompressed lookup batches.
- Graph, both snap files, source manifest and attribution copies matched source
  hashes. Graph and snap files used local hardlinks during production.
- The destination prefix was empty before publication. Conditional
  `If-None-Match: *` PUT and multipart completion prevented object replacement.
  The uploader recomputed full SHA-256 over all sent bytes, sent `Content-MD5`
  for each object or part, checked returned part and composite multipart ETags,
  and checked HEAD sizes, ETags and stored SHA-256 metadata. A second HEAD pass
  checked all artifacts before the manifest was uploaded last. ETags served as
  transport identities, not SHA-256 digests. Objects were published with immutable
  cache policy. Data corrections require a new prefix. The later approved
  [raster extension](raster-data.md) permits a manifest/documentation amendment,
  with cache handling recorded by that delivery; it does not alter these vector
  identities or this original publication receipt.
- Public selective reads passed with real HTTP 206 ranges, exact Content-Range,
  identity encoding, strong ETags pinned by If-Match, bounded artifact checks,
  directory digest and lookup binding. Nine present IDs matched independent
  source schema and complete rows; two absent IDs were correctly absent.
  The probe made **18 requests**, receiving **23,362,253 bytes**. It read lookup
  batches `[0, 1, 170, 340]` and catchment batches
  `[0, 3, 4, 61, 62, 3903, 6656]`, without a worldwide catchment locator or ID scan
  over HTTP. Its separate local source comparison scanned source rows.

## Commands and retained receipts

`RUN` below names this run's external `vector-delivery` artifact directory.
`SOURCE` and `OUTPUT` were its `source` and `bundle` children. These bulk paths
were removed after verification. Commands ran from the repository root.

```bash
uv run python scripts/convert_vector.py "$SOURCE" "$OUTPUT"
uv run python scripts/verify_vector.py "$SOURCE" "$OUTPUT" --report "$RUN/full-verification.json"
uv run --with boto3 --with "boto3-stubs[s3]" python "$RUN/publish_vector.py" "$OUTPUT" "$RUN/full-verification.json" "$RUN/publication.jsonl"
uv run python scripts/check_vector_access.py https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0/ --ids 1 2 4096 4097 4098 65536 65537 11167509 22337300 22337301 9223372036854775807 --source "$SOURCE" --report "$RUN/public-access.json"
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run ty check src scripts tests
uv build
```

Repository validation passed: 56 tests, Ruff, type checking and package build.
The reviewed one-off publisher remains outside the repository with its tests
and operational receipts; its SHA-256 is
`43e3fcb33d1920ff3ad413e91beb5034cf7acd3240209c326bc993b861d97a35`.
Small receipts are retained under session
`01a1185f-4b37-776e-baed-82ba296b06cb/vector-delivery`: `full-verification.json`,
`publication.jsonl`, `destination-published.json`, `public-access.json`,
`published-manifest.json`, source inventories, `snap-wkb-types.json` and
`bulk-cleanup.json`.

Cleanup passed at 2026-10-07 23:56 UTC. This run's downloaded source, generated
bundle and partial-download directories were removed after all checks passed.
Pre-existing datasets and unrelated work were untouched.

## Source caveats and scope

The derivative retains **CC BY-NC 4.0**, source author attribution, `NOTICE` and
`CITATION.txt`. The published README identifies the representation change.
GRIT DAG upstream areas retain partitioned-area semantics and the source's
44 null reach upstream-area values. Source hydrology and geometric topology were
preserved, not newly certified.

Source snap `geo` metadata lists LineString and MultiLineString. A complete WKB
header count found only LineString: 1,767,065 segment features and 20,570,235 reach
features. The metadata overdeclaration was preserved byte-for-byte. This check
classified WKB headers; it was not geometry validation.

This verifies publication and selective access after IDs are known. Pourpoint
reader integration, cold start, graph preparation, snapping and end-to-end
benchmarking remain separate work.
