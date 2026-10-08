# GRIT overview removal trial

Small trial for the [published vision](../../planning/visions/2026-10-08-grit-raster-overview-removal-trial.md),
measured on 2026-10-08. No global rewrite, production object, manifest or raster
contract changed. This returns evidence to [#6](https://github.com/pourpoint-tools/hfx/issues/6),
not approval to run the full job.

## Recommendation

**Raw compressed-tile copying works on these fixtures.** Use `gdaladdo -clean`
on a disposable local input, then **cogger v0.1.1** to make a new cloud-friendly
native-only TIFF. Cogger preserved all 16 native compressed payloads exactly.
Keep the GDAL COG lossless-recompression path as the simpler maintained fallback.
Both methods preserved every native value bit, separate validity mask, grid,
CRS and nodata, and passed explicit layout checks.

Do not infer global readiness from four-tile crops. Cogger's >4 GB BigTIFF output,
global tile-index memory and full-source metadata coverage remain untested. Its
fixed metadata whitelist omits unknown TIFF tags and ImageDescription. Its CLI
reads local files, so the practical stock-tool path acquires complete input files
on the VM; **that acquisition is not authorized by this trial**. Confirm global
metadata and memory requirements before choosing it for the full job. The native
payload test is relative to the source-derived fixtures, not raw global tiles:
fixture acquisition decoded and encoded the selected native cells once.

GDAL's COG writer decodes and recompresses; `COPY_SRC_OVERVIEWS` is not a raw-copy
switch. `LIBERTIFF` is a read-only driver, not a tile-copy writer. A GDAL rewrite
can read native `/vsicurl/` ranges without acquiring overview payloads, but visits
all native tiles in a full job. Request count, tile-index cost, throughput and
runtime are not established by this experiment. No custom converter is proposed.
See [GDAL #8449](https://github.com/OSGeo/gdal/issues/8449), the
[COG driver](https://gdal.org/en/stable/drivers/raster/cog.html), and pinned cogger
[CLI](https://github.com/airbusgeo/cogger/blob/v0.1.1/cmd/cogger/main.go),
[loader](https://github.com/airbusgeo/cogger/blob/v0.1.1/loader.go) and
[writer](https://github.com/airbusgeo/cogger/blob/v0.1.1/cog.go).

## Inputs and checks

Acquisition read **2,776,459 HTTP body bytes** against a pre-set 256 MiB budget.
Each source-derived crop is 1024 × 1024 native cells, 30 m, EPSG:8857:

| Crop | Source column,row | Valid cells per band |
| --- | --- | ---: |
| Greenland | 391168,49152 | 7,444 |
| Madagascar | 654848,345600 | 951,002 |

Both direction (uint8/nodata255) and accumulation (float32/nodataNaN) include valid
and nodata cells. Each input is little-endian BigTIFF, 512 × 512 tiles,
DEFLATE level 6/no predictor, with **synthetic nearest-neighbour overview levels
2 and 4**. The source reports levels 2 through 1024; its resampling algorithm and
compression level were not established. Crops do not reproduce its huge tile
index or pyramid. Native cells were never resampled or hydrology rederived.

`verify_output` compares direction values, float32 byte patterns (including NaN
and signed zero), masks, dimensions, transform, CRS, dtype and nodata. It also
checks no overviews, 512 tiles, DEFLATE/no predictor and no sidecars. Both
rio-cogeo 7.0.3 and GDAL's validator with `--full-check=yes` accepted every output.
Both warn that files larger than 512 should have overviews. That recommendation
is deliberately not followed; this is a validated native-only cloud layout,
not a claim of strict overview-bearing conformance. Cogger additionally passed
byte-for-byte comparison of all native compressed tiles, including tile geometry,
compression, predictor and byte order. The tests reject retained overviews,
changed float bits and changed tile payloads.

## Size and resources

| Raster | Input bytes | Cogger bytes | GDAL bytes |
| --- | ---: | ---: | ---: |
| greenland-acc | 22,671 | 14,406 | 14,584 |
| greenland-dir | 7,406 | 4,231 | 4,409 |
| madagascar-acc | 1,198,075 | 891,341 | 891,519 |
| madagascar-dir | 388,777 | 278,540 | 278,718 |

All input fixtures together occupy 1,616,929 bytes. Cogger emits classic TIFF for
these small outputs despite BigTIFF inputs; its stock CLI automatically chooses
BigTIFF above 4 GB but cannot force it here. GDAL outputs are explicitly BigTIFF.
Do not interpret the small header-size difference as a compression advantage.

Each `gdaladdo -clean` took 0.03 s, with peak RSS 38,632–42,348 KiB. Each cogger
copy was below GNU time's 0.01 s reporting resolution, with peak RSS
2,816–3,072 KiB. These numbers exclude the preliminary file copy and later
validation. They do not establish a meaningful speedup. GDAL per-file creation
was 0.0068–0.1319 s; the complete Python rewrite/verification process took 1.21 s
and peaked at 151,168 KiB. Acquisition took 21.57 s and peaked at 190,600 KiB.
All measurements are single runs with warm local files; no fsync or cold-disk
benchmark was performed. RSS units here are Linux KiB. No tiny timing is scaled
to a global runtime estimate.

Post-run trial files occupied 5,642,564 logical bytes / 5,763,072 allocated bytes.
This is an inventory, not a measured peak. The run retained original inputs,
separate same-size cogger working copies (overview IFDs unlinked) and both outputs.
No high-frequency scratch-file monitoring was done. Source inspection, rather
than this inventory, informs global temporary-file needs. The COG CreateCopy
path used here is not GDAL's newer Create API with extra full-TIFF staging.
Four cogger pipelines overlapped each other and the fallback; timings are not a
matched benchmark.

Both methods passed eight selected R2 reads (16 total), including values and
separate masks. Cogger received 2,374,497 response-body bytes in 26 requests;
GDAL received 2,392,305 in 26 requests. These tiny layout differences do not
establish a remote-performance winner. Eleven temporary objects (eight TIFFs
and three attribution files), 2,381,993 PUT-body bytes, were conditionally
uploaded to a new disjoint prefix. Sizes, SHA metadata and ETags matched.
All eleven were deleted with matching ETags, each HEAD returned 404, and the
prefix listed empty. Production objects and bucket policy were unchanged.
PUT sizes are payload accounting, not measured socket traffic.

The reused HTTP bridge counts received response bodies, including metadata and
read-ahead, not headers/TLS/TCP or end-to-end wire bytes. It serializes requests
and uses urllib connections; timing is not direct engine latency. GDAL block
cache is disabled but OS/CDN caches are not. Unique paths give fresh readers,
not proof of cold caches. Acquisition and remote receipts retain request ranges,
actual received bytes, ETags and cache headers. SCP, tool installs and cloud API
traffic are outside those measurements; no full raster was downloaded.

## Reproduce

Execution revision: `5078ad5` (scripts and locked dependencies). From the repo
root, use a **new external** `$RUN` directory. Bulk data must stay outside Git.
These commands only operate on trial fixtures; do not substitute global inputs
without separate approval.

```bash
uv sync --group raster-experiment
uv run --group raster-experiment python -m experiments.raster_overviews.trial acquire "$RUN"
# Fallback: COG OVERVIEWS=NONE BIGTIFF=YES BLOCKSIZE=512 COMPRESS=DEFLATE PREDICTOR=NO LEVEL=6
uv run --group raster-experiment python -m experiments.raster_overviews.trial rewrite "$RUN"
# Raw-copy example; repeat for each of the four small inputs:
cp "$RUN/bulk/greenland-acc-input.tif" work.tif
gdaladdo -clean work.tif
cogger -output output.tif work.tif
uv run --group raster-experiment python -m experiments.raster_overviews.trial verify-raw "$RUN/bulk/greenland-acc-input.tif" output.tif
/usr/bin/python3 -m osgeo_utils.samples.validate_cloud_optimized_geotiff --full-check=yes output.tif
# After conditional publication to a new trial-owned prefix:
uv run --group raster-experiment python -m experiments.raster_overviews.trial verify-remote "$RUN" "$PUBLIC_BASE"
```

The remote command expects four `*-output.tif` files and their `*-input.tif`
references in `bulk/`. The run used separate `cogger/bulk/` and `bulk/` output
sets. Native reads cover a mixed-validity window plus a four-tile boundary window
per raster; Greenland's boundary window is all nodata. Parent-managed publication
and cleanup use the exact ownership ledger, not recursive deletion by prefix.

Environment: Ubuntu 24.04 x86_64, Linux 6.8.0-138-generic; Python 3.13.16,
Rasterio 1.5.2/GDAL 3.12.2, NumPy 2.5.3, rio-cogeo 7.0.3 and tifffile 2026.9.20.
System GDAL 3.8.4 supplied `gdaladdo` and the full-check validator.
Cogger v0.1.1 Linux amd64 release ZIP SHA256:
`79f6e9885cf11bcb7df00ec2246ea5bde633068bd4df164ed1f316723165a7a4`.
Local validation: 66 tests; Ruff lint/format, repository and experiment ty, and
`uv build` passed. The two small new tests reuse established raster checks.

## Global proposal and retained resources

If separately approved, start with CCX23 (4 dedicated cores, 16 GB RAM) and a
500 GB volume, processing one raster at a time. Preserve production originals
remotely; use one disposable local source plus output, not two full local source
copies. Raw cogger uses random-access local input but writes sequentially; the
stock CLI writes a local file. Compressed GDAL output should be local and
seekable. Neither tested command streams a final compressed object directly to R2.
`gdaladdo -clean` only unlinks overview IFDs; it does not shrink the working input.

Earlier source evidence estimates ~256 GB input pair and ~69 GB overviews; these
are not new global measurements. A 500 GB volume gives room for sequential
input/output processing, but reserve headroom and monitor actual free disk.
The 160 GB trial root disk alone is insufficient for the proposed full job.
16 GB memory is a starting configuration, not a proven bound for global indexes.

Prices checked 2026-10-08: CCX23 + IPv4 €0.1498266/hour including 8.1% VAT.
A 500 GB volume is €30.9166/month; using 730 hours/month gives an estimated
combined **€0.1922/hour (~US$0.2148/hour)**. FX: 1 EUR = 1.1177 USD, observation
date 2026-10-07. This is a configuration price, **not a job-cost estimate**;
global duration is unknown. Recheck prices and grant a separate budget first.

**The trial VM remains running and billing continues, including while idle.**
Server `169381744` / `hfx-overview-trial-20261008-1246`, CCX23 in `hel1`,
160 GB root disk, no volumes. Access: `root@89.167.2.16` with the existing
`nicolas-workstation` SSH key; no credentials were copied. Primary IP IDs:
IPv4 `154299103`, IPv6 `154299104`. Source checkout `/root/hfx` at execution
revision above; tools `/root/overview-tools`; inputs, outputs and receipts
`/root/grit-overview-run`. The receipt inventory lists retained files.
No conversion jobs remained at 2026-10-08 12:55:12 UTC.

Ongoing estimate: **€0.1498266 / US$0.1674612 per hour**. Since creation at
2026-10-08 12:46:32 UTC, estimated spend was **US$0.0223 at 12:54:31 UTC**;
this is elapsed-time accounting, not an invoice. The US$5 cap is projected at
**2026-10-09 18:37:59 UTC / Friday 2:37:59 p.m. Maryland EDT**. Allow one billing
hour of reserve: act by **17:37:59 UTC / 1:37:59 p.m. EDT**. Maintainer check-in:
**October 9, 12:46 UTC / 8:46 a.m. EDT**. An agent-internal hourly reminder
(`506d2a16-fefc-413d-b28d-dfb3d1394d6a`) is active, with warnings around 20 and
24 elapsed hours and before the cap. It is an alert, not automatic deletion or a
provider billing cap; warning delivery is not an exact-time guarantee. Rounding,
FX and payment fees are not measured. Cleanup still needs maintainer authority.
Retention does not authorize extra spending or a global run. Arrange removal
of the VM and both trial-owned IPs before the cap unless a new budget is agreed;
power-off alone does not stop all charges.

## Evidence and attribution

[Acquisition](acquisition.json) retains source ETags and measured request bodies.
[Measurements](measurements.json) retains validation, payload hashes and time/RSS
logs; [commands](commands.json) records the exact VM commands. [Cogger remote reads](cogger-remote.json) and
[GDAL remote reads](fallback-remote.json) retain bounded read evidence.
[Object ledger](objects.json) proves conditional writes and verified cleanup.
[Operations](operations.json) records resource IDs, costs, versions, exact code
revision, disk inventory and measurement gaps. Bulk files and sensitive setup
logs are not in Git. [Local cleanup](local-bulk-cleanup.json) records removal
of all 16 laptop TIFF copies after upload/verification; the VM inputs and outputs
remain for review.

Dataset-derived samples and evidence remain **CC BY-NC 4.0**. Credit Michel
Wortmann, Louise Slater, Laurence Hawker, Yinxue Liu and Jeffrey Neal (2025),
*Global River Topology (GRIT) raster datasets*,
[doi:10.5281/zenodo.15715535](https://doi.org/10.5281/zenodo.15715535).
See the existing [NOTICE](../raster_compression/NOTICE),
[CITATION.txt](../raster_compression/CITATION.txt) and
[source provenance](../raster_compression/source.json). Attribution and a README
explaining added/removed overviews accompanied the temporary objects. HFX's code
license does not replace the dataset license.
