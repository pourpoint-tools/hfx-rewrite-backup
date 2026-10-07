# Local candidate delivery

Produced and fully verified on 2026-10-07 with Python 3.13.14, PyArrow 25.0.1 and
the committed dependency lock. These are internal-use experimental datasets, not
a public HFX release. Reproduction and interpretation are in the
[candidate contract](selective-access-candidates.md).

## Outputs

Under `/Users/nicolaslazaro/.prime/agent/session-artifacts/hfx-candidates/hydrobasins/`:

| Bundle | Units / lookup records | Index batches | Data blocks | Total bytes |
| --- | ---: | ---: | ---: | ---: |
| `candidate-a-index/` | 3,786,228 | 58 | 924 Parquet row groups | 4,390,849,958 |
| `candidate-b-arrow/` | 3,786,228 | 58 | 1,085 IPC batches | 3,523,782,330 |

Each index is 60,595,826 bytes; each directory is 6,292 bytes. Candidate A
catchments remain 3,703,151,810 bytes. Candidate B catchments are 2,836,084,186
bytes. Total bytes include source validation reports and attribution. File sizes
are observations of these artifacts, not compression or performance promises.

## Identity (SHA-256)

| Artifact | SHA-256 |
| --- | --- |
| Source / A catchments | `b182cc56d761e2ab4064aa6aaf0883c4a64f5e2951b7ee9982a2e261f52f5bb9` |
| B catchments | `8f2433d54b6137063066ba332e86237004db37481314cf8be44188dd11b68379` |
| Source manifest / both `source-manifest.json` | `81da3c17b070b80933dfd1d4e90fc9166f7f6fefedde109c1f43fe0aad1bd954` |
| Graph (source and both copies) | `13a41abe69ff212343cf7aba8631a4bfd79a328d8be595990652e89321a05bd7` |
| Snap (source and both copies) | `96163fe69efd7ba3dc8bc299680f48545aa0ca3d71ebf350545962084d9953ff` |
| Attribution (source and both copies) | `4ea6f03655f61d94d7185c05df9a0b2c60c52354841017a8186f99bf7d77474f` |
| A wrapper manifest | `3bdb85ed4b159f82b4f909f4e4984fa06ca3a00872ae5739464f8603d633f21f` |
| B wrapper manifest | `3dbf2054dcc90378efacea4664ed8b2e41aba77c84906ce8c63ae2560535579f` |

The wrapper manifests contain full hashes of every included artifact. The external
`verification.json` beside the two output directories records all seven source
hashes, output manifest identities, row/block counts and successful checks.

## Checks performed

- Every unit appears once in each sorted lookup. Every physical address matches
  independently read source IDs. Every directory range matches its index batch.
- All B records match source schema metadata and ordered values, including nulls,
  relationship columns and exact WKB bytes. No sample-only comparison was used.
- A catchments and both bundles' graph, snap, attribution, source manifest and
  source validation files match source hashes.
- All seven source hashes match an independent pre-production baseline, as well
  as the producer's before/after and verifier's before/after checks.
- Small tests cover shuffled non-contiguous IDs, invalid IDs, multiple index
  batches, an oversized polygon, optional strings, nulls, altered artifacts,
  wrong addresses/ranges, configurable budgets and safe destination refusal.

Producer development used three small red/green increments: lookup schema and
sorting; byte-budgeted Arrow conversion; complete bundles and preservation.
Verifier tests used independent manually constructed expectations and deliberate
corruptions, then producer integration. Local logs and the independent source
baseline are under
`/Users/nicolaslazaro/.prime/agent/session-artifacts/hfx-candidate-implementation/`.

Repository checks:

```bash
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run ty check src
uv build
```

No remote data was changed or uploaded. No readers, delineation changes, benchmark
harnesses or speed measurements were added. The source's graph topology and
geometry validity were not re-certified; existing source reports remain source
evidence only.
