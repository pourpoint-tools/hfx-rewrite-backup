# Native raster copy verification

`verify_raster_copy.py` is a producer check for the GRIT native-only raw-copy
path. It performs no download, conversion, upload or hydrologic validation.
Use the repository environment with `uv sync --group raster-experiment`.

Before any `gdaladdo -clean` mutation of the disposable local input:

```sh
uv run --group raster-experiment python scripts/verify_raster_copy.py capture-source INPUT.tif TRUSTED_SHA256 source.json
```

Obtain `TRUSTED_SHA256` from the retained production source manifest, not from
an unverified download. Preserve `source.json` outside bulk scratch storage.
The command only writes a receipt after the complete file matches that hash.
Do not modify inputs while verification runs. After raw copying:

```sh
uv run --group raster-experiment python scripts/verify_raster_copy.py verify-output OUTPUT.tif source.json output.json
```

The original receipt is the reference, not the locally mutated source. Its
ordered native tile identity binds each tile's byte length and SHA-256, with a
domain-separated aggregate. Equal aggregates prove every compressed native tile
matches under the same cryptographic assumption as the whole-file identities.
Exact native TIFF tags (including unknown tags, ImageDescription, GDAL metadata,
nodata, grid and decoding fields) and byte order must match. Only the tile offset
and byte-count index tags are excluded from that metadata comparison; lengths
are bound by the aggregate. Loss of source metadata is an error, not a warning.

Identical compressed payloads and decoding metadata establish exact native
sample bits, including float32 NaN payloads and signed zero, without decoding
trillions of redundant cells. A separate mask check accepts only nodata-derived
or all-valid masks. Identical values and nodata interpretation establish their
complete mask equality. Internal masks, external files and SubIFDs fail closed;
this is not a verifier for arbitrary fabrics or a GDAL re-encoding path.
Independent decoded public-window checks remain part of publication verification.

Both phases hash the whole file and native payloads in one sequential pass,
then read at most 128 KiB for the existing 65,536-byte head/tail fingerprints.
Payload buffers are at most 1 MiB. Tifffile retains tile index tuples in memory;
the supported index is limited to 3,000,000 tiles (GRIT has 2,041,930). Memory is
bounded by that index, not by raster dimensions or a full native pixel array.
There is no per-tile hash list in receipts. Source overviews are read for the
whole-file hash but are excluded from the native aggregate.

Outputs must be BigTIFF with one IFD, 512-square tiles, lossless DEFLATE and no
predictor. Native tile ranges must be nonempty, ordered, nonoverlapping and
inside the file. The IFD and metadata must precede tile data, with no trailing
unused bytes other than the declared four-byte GDAL tile trailer. Declared
GDAL size leaders and repeated-last-four-byte trailers are checked for every
native tile during the same scan. Neither GRIT source has sparse native tiles;
sparse tiles fail closed. The COG validator must pass with no warning except its expected
recommendation to include overviews. This is native-only layout support, not a
claim of strict overview-bearing conformance.

Successful output receipts include `status: "passed"`, source identity, complete
output SHA-256/size/head/tail fingerprints, native payload identity, metadata
and mask proof flags, and validator warnings. Receipts are not signatures: keep
them with the trusted source manifest and operational evidence. Existing receipt
paths are never overwritten. A failed check raises an error and writes no receipt.
