# GRIT 0.4.0 raster delivery

Published and verified on 2026-10-08 (UTC):
<https://basin-delineations-public.upstream.tech/grit/hfx-v0.4.0/>.
The root manifest now declares both rasters alongside the existing vectors.
The bundle is self-contained: no 0.3.0 object is needed to discover or read it.
The [raster contract](raster-data.md) and [historical vector contract](https://github.com/pourpoint-tools/hfx/blob/b5b116440b89a604e12dcc26f09b21ef9e8276a9/docs/v0.4.0/vector-data.md)
describe interpretation and selected access. Pourpoint reader implementation
remains separate work.

## Delivered identities

| Artifact | Bytes | Full SHA-256 |
| --- | ---: | --- |
| `aux/d8/flow_dir.tif` | 35,460,747,402 | `6d03ccdc092b914be0ae41975fbafebb2b02334ff481a1589897539228ab7c65` |
| `aux/d8/flow_acc.tif` | 150,995,308,307 | `01e8b76570a8d98026fdad77107ed5fe719490433d0351c43b62aca32ff0c15d` |
| `manifest.json` | 6,776 | `3f8e6bb95e08063fff773096a6b949d3925527f15e748f66589b6d8ba73993fb` |

The native-only pair is **186,456,055,709 bytes**, down from 255,756,386,559:
**69,300,330,850 bytes removed**, with no native values or masks changed.
The complete bundle now contains 15 objects totaling 217,033,597,205 bytes.
The [machine-readable receipt](receipts/grit-raster-delivery.json) includes source
identities, head/tail fingerprints, native tile aggregates, upload ETags, public
comparisons, resource measurements and cleanup. The public manifest binds all
14 artifacts, including the new `raster-delivery.md` note.

## Preservation proof

Both rasters retain 1,070,000 × 500,000 cells, EPSG:8857 and affine
`(30, 0, -15000000, 0, -30, 8400000)`. Direction remains GRASS uint8/nodata255;
accumulation remains width-partitioned drainage area in km², float32/nodataNaN.
Both retain 512-square tiles, DEFLATE without a predictor, and every native
sample bit. No native resampling, warp or hydrologic recalculation occurred.

The producer ran the [native-copy verifier](../../scripts/README.md) at commit
`50ad64ef85d53a560062f3e574f50dbe19225dd6`. Each full source SHA-256 matched the
published source README before any local mutation. That same sequential pass
recorded the ordered lengths and hashes of all **2,041,930 native tiles per
raster**, exact native TIFF tags, byte order, grid and mask interpretation.
The saved source receipt remained the reference after overview directories
were removed from the disposable local copy.

Every output tile aggregate and interpretation field matched the original
receipt. Identical compressed bytes and decoding metadata prove exact native
bits, including float32 NaN payloads and signed zero. Identical values and
nodata interpretation separately prove the nodata-derived masks. This is a
complete raw-copy equivalence proof, not a claim that every pixel was decoded
again. Neither source has sparse native tiles, internal masks or unknown tags
omitted by cogger. The source `OVERVIEW_RESAMPLING=NEAREST` metadata is retained
as history; it does not imply that the outputs have overviews.

The outputs are BigTIFF with one IFD and no overviews. Complete checks covered
ordered, nonoverlapping tile ranges, metadata before data, every declared GDAL
tile-size leader and repeated-byte trailer, and no unused trailing storage.
The COG validator returned no errors; its only warning recommended overviews
for large images. Native-only layout is intentional, not a claim of strict
overview-bearing conformance. Source hydrology was preserved, not newly certified.

## Tool and operational checks

The supplied cogger checkout was clean at v0.1.1,
`57f50c6c0234b3702d416cb1eaaab864eb18e52d`. Actual global source headers and complete
byte-count arrays were inspected before acquisition. All meaningful native tags
were supported. A bounded stock-CLI preflight exercised the global 2,041,930-tile
index and a valid tile offset beyond 4 GB, using about 210 MiB peak RSS. A second
realistic DEFLATE pre-clean → clean → copy → verify run produced a 4.51 GB
BigTIFF, with independent decoded boundary/last-window checks.

Production used the retained CCX23 VM and a 500 GB scratch volume, one raster at
a time. Source hashing took 3:18.83 / 14:47.01; copying took 2:40.97 / 11:40.14;
output verification took 2:36.42 / 11:41.22 (direction / accumulation).
Peak verifier RSS was about 320 MiB. About 144 GB remained free with the complete
accumulation source/output pair present. These are this run's measurements,
not throughput promises or a high-frequency peak-disk trace.

The initial direction HTTP/2 download failed after a partial transfer. Standard
aria2 resumed with pinned source ETags; the complete source hash then passed.
The accumulation upload completed and its remote ledger/HEAD passed, but the
local SSH connection did not report exit. Public checks independently confirmed
success before only that stale local connection was terminated. No upload was
retried and no artifact was replaced.

The essential producer commands, with receipts outside bulk storage, were:

```sh
uv run --group raster-experiment python scripts/verify_raster_copy.py capture-source INPUT.tif TRUSTED_SOURCE_SHA256 source.json
gdaladdo -oo IGNORE_COG_LAYOUT_BREAK=YES -clean INPUT.tif
cogger -output OUTPUT.tif INPUT.tif
uv run --group raster-experiment python scripts/verify_raster_copy.py verify-output OUTPUT.tif source.json output.json
```

`INPUT.tif` above is exclusively a verified disposable VM-local copy. The
`IGNORE_COG_LAYOUT_BREAK` option permits that local overview-directory edit;
it is never applied to a production cloud object. Cogger writes a new file.

## Publication and public access

Both new raster uploads used the configured `upstream-r2` profile, exclusive
ownership journals, per-part MD5, verified part/composite ETags, a streamed full
SHA-256 check before conditional multipart completion, and matching HEAD size,
ETag and SHA metadata. No bucket policy changed. Credentials stayed out of
files, arguments, repository content and handoff; the VM upload received them
only through encrypted SSH stdin into process memory.

Public GDAL reads matched independently decoded source references from
tifffile/imagecodecs. Two 1024-square windows per raster cover Greenland and
Madagascar, crossing four tiles and including valid cells and nodata. All
4,194,304 sampled values across both bands matched exact bytes, with separate
mask equality. The paired probe used 38 HTTP requests and 2,727,339 response-body
bytes, with exact ranges and pinned ETags. This is not a latency benchmark;
headers/TLS are outside that byte count. A Rasterio `is_tiled` deprecation
warning was recorded separately from layout validation.

After those checks, the new delivery note was conditionally uploaded and the
root manifest was published **last**, conditional on the old manifest ETag.
Origin, ordinary public URL and cache-busted public URL returned the exact new
manifest. New responses use `public,max-age=0,must-revalidate`.
The [previous manifest bytes](receipts/grit-vector-manifest-before-rasters.json)
are preserved for recovery (SHA-256 `fb6f93472cffe5868fb6595de725936c9fd881caa7534700fd6bc8d1fde286a6`).
Old client caches may retain that vector-only snapshot under its former one-year
immutable policy. It remains valid because all referenced artifacts, including
the original README, are unchanged. Upgrading readers should explicitly obtain
a fresh manifest, then retain one consistent snapshot during selected reads.

All 10 objects in the 0.3.0 inventory retained their keys, sizes, ETags,
LastModified and storage class. All 11 existing 0.4.0 artifacts retained their
size, ETag and SHA metadata. These checks passed before and after publication.
Post-publication vector reads selected IDs 1, 4097 and 22337300 and rejected
22337301 as absent; complete selected-row IPC and geometry hashes matched the
prior independently source-verified publication receipt.

Repository validation passed: 73 tests (including both raster experiments),
Ruff lint/format, ty over source/scripts/tests/experiments, and `uv build`. Six
non-georeferenced warnings came from synthetic test fixtures, not production
rasters. Operational upload/check/publisher tests passed separately.

## Attribution, cleanup and handoff

The derivative retains **CC BY-NC 4.0**, original `NOTICE`, `CITATION.txt`, source
README/manifest provenance and source caveats. The new delivery note explains
overview removal and credits the GRIT raster authors and
[doi:10.5281/zenodo.15715535](https://doi.org/10.5281/zenodo.15715535).
New publication provenance is separate from unchanged source normalization fields.

Cleanup was verified at **2026-10-08 16:24 UTC**. Both source/output bulk pairs
were removed; server `169381744`, volume `107079699`, IPv4 `154299103` and IPv6
`154299104` all returned not found. The old US$5 trial reminder and this run's
budget reminder are cancelled. No delivered artifact or 0.3.0 object was deleted.

The US$20 job cap included retention from 12:46:32 UTC. Rounding conservatively
to four server/IPv4 hours and three volume hours, with 8.1% VAT, EUR/USD 1.20 and
a 720-hour volume-month estimate, compute/storage cost is about **US$0.88**.
The observed ECB rate was 1.1177. This is not an invoice; a US$2 reserve covers
small job-duration R2 charges, rounding and fees. Transfer stayed well within
the 20 TiB server allowance. Delivered raster storage persists under the existing
bucket; its list-rate cost is about US$2.80/month before account allowances.

Small source/output receipts, upload journals, original/updated small objects,
public probes, preflight records, command/timing logs and cleanup evidence remain
outside bulk data in session `01a11bbf-b447-748f-94eb-7859908643c1/raster-delivery`
under `.prime/agent/sessions/`; independent review/reference evidence is under
the matching `.prime/agent/session-artifacts/` directory. Useful trial evidence
was saved before VM deletion. No bulk raster is in Git or on the laptop.

The handoff is for [HFX #6](https://github.com/pourpoint-tools/hfx/issues/6) and
[Pourpoint #4](https://github.com/pourpoint-tools/pourpoint/issues/4): use the fresh
root declaration and preserved native semantics. This delivery does not change
Pourpoint's current reader or implement delineation, caching or batching.
