# GRIT worldwide production

The producer accepts all seven original regions in one inventory. It does not
repair edges or guess cross-region identities. Complete GRIT publication remains
conditional on all original fidelity checks and public verification passing.

## Acquire originals on the production server

The [pinned inventory](receipts/grit-original-inventory.json) describes Zenodo
record 17435232: four regional products × seven regions plus global component
catchments, original README and CC BY-NC 4.0 license. ZIP checksums are published
MD5s; expanded sizes/CRC32 came from bounded central-directory reads. Acquisition
must verify complete archives before these become delivered-source evidence.

```sh
uv run python scripts/acquire_grit.py docs/v0.4.0/receipts/grit-original-inventory.json /data/grit-originals
```

Only run this on approved compute, never the maintainer laptop. Downloads and
extraction are sequential. Every archive is size/MD5 checked, its sole member
name/size checked, CRC checked during extraction, and its extracted SHA-256
recorded. Existing archives/outputs are not replaced or deleted. A failed transfer
or extraction remains for diagnosis. There is no automatic retry/resume engine;
inspect failures before choosing a fresh destination. `--region SP` (or another
release region) allows staged acquisition; `GLOBAL` supplies component polygons.
Each invocation writes a separate producer-inputs JSON. Combining region receipts
requires collecting their `sources` into one inventory and retaining the same
README/license declarations; do not duplicate GLOBAL components.

The complete invocation writes `producer-inputs-GLOBAL-ALL.json`. To opt into the
approved unchanged raster references, set `external_rasters: true` in that input.
This requires all 29 original products, no component selection, matching pinned
release MD5s/member names, and the original README/license. The raw source documents
are included and fingerprinted in the bundle. The flag carries the publisher's
commitment to retain those exact old raster objects for this bundle's lifetime.

```sh
uv run --group vector-production python scripts/produce_grit.py INPUT.json NEW_OUTPUT
uv run --group vector-production python -m scripts.verify_grit INPUT.json NEW_OUTPUT NEW_RECEIPT.json NEW_AUDIT.sqlite --worked-example --external-raster-receipt docs/v0.4.0/receipts/grit-raster-delivery.json
```

The verifier's default still rejects external declarations. Its explicit receipt
option checks exact old raster identities/URLs/meaning and records the supplied
receipt identity; it does **not** freshly hash rasters or establish public access.
The publisher must additionally retain actual consistent-identity public range
and decoded-window evidence. No rasters are copied, downloaded or reprocessed.
Upload verified artifacts first and the root manifest last at a new immutable
prefix. Preserve existing publications and verify their continued valid reads.

## Capacity and stop conditions

The 29 archives occupy **21,319,552,599 bytes** and expand to
**73,681,620,992 bytes**. Retaining both needs **95,001,173,591 bytes**, before
filesystem overhead. These exact directory sizes are not a processing peak bound.
Plan approximately 95 GB originals + 100 GB outputs + 150 GB verifier/index
scratch + 100 GB free headroom = 445 GB decimal on the approved 640 GB server.
Output/scratch allowances are estimates, not upper bounds. Acquisition refuses a
new archive if its compressed+expanded size would leave less than 100 GB free.
That guard is operational headroom, not assurance later verification will fit.
Monitor free disk and RSS during every stage, and stop before exhausting either.

The sample verifier uses 8,650,752 bytes for 3,567 records (about 2.4 KB/row),
including copied geometry and JSON attributes; producer identity scratch is
1,134,592 bytes. Extrapolation to tens of millions of records is uncertain:
polygon sizes and attributes vary. After acquiring originals, count actual rows
and native geometry bytes per region before committing to full conversion.
Source groups remain 256 rows, IPC budget 8 MiB; a singleton geometry may exceed
that budget. Producer SQLite cache is 8 MiB; verifier cache is 16 MiB. ID maps,
joins, sorted lookup addresses and verification geometry staging are on disk.
Node endpoint queries and verifier incoming-edge queries use indexes. Read-only
node connections are reused rather than opened once per polygon.

Fresh complete original component production took 32.02 seconds with peak RSS
177,799,168 bytes locally, including full original archive/member verification
and source hashing. This does not establish global throughput or server duration.
At 10–50 MB/s, 21.32 GB source transfer alone takes about 36–7 minutes; full
conversion/verification can dominate. Use first-region measurements and monitor
elapsed spend against the approved operational budget; it is not a provider cap.

## Fidelity and meanings

Namespaces keep release, region, product and layer distinct. Components are one
GLOBAL source, not seven regional copies. Whole SP references have been checked;
other regions' actual cross-region links and physical schemas remain unverified
until server inspection. Unresolved references or an actual directed cycle stop
production with retained evidence. Do not redirect/drop edges or downgrade a cycle
to an anomaly note. Escalate any contract contradiction before publication.

Native Arrow types come from original SQLite declarations, not README table type
labels. All original attributes/nulls remain under `source_`. Dictionaries describe
node types and available source flags without reclassifying hydrology. Plain
`outlet` has an explicitly unknown precise termination meaning. Original worldwide
segment nodes also contain 19 `interbasin` labels (AS 2, EU 3, NA 6, SA 2, SI 6),
including AS node 170120166. The original README does not define this label; its
precise hydrological meaning remains unknown. Preserve it without inventing
inter-region edges or classifying it as an inlet or outlet. Undeclared codes
fail independent categorical verification. Cycle values remain source diagnostics,
not booleans or proof of graph acyclicity. Original README acknowledges unresolved
cycle/continuity diagnostics and incomplete cross-catchment divergent-flow area
contributions; preserve those caveats and separate area definitions.

Keep receipts, original inventories, commands, final full artifact hashes and
public request logs before cleanup. The producer and verifier create new outputs
and preserve failed artifacts. Delete only this effort's approved disposable bulk
and server after complete successful public verification; root owns those actions.
