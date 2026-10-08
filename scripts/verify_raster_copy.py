"""Producer-only proof for native DEFLATE tile copies, not a general TIFF verifier."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import BinaryIO, TypedDict, cast

import rasterio
import tifffile
from rio_cogeo.cogeo import cog_validate


class Identity(TypedDict):
    size_bytes: int
    sha256: str
    head_sha256: str
    tail_sha256: str


class TagEvidence(TypedDict):
    code: int
    dtype: int
    count: int
    hex: str


class Grid(TypedDict):
    width: int
    height: int
    transform: list[float]
    crs: str


class Metadata(TypedDict):
    byteorder: str
    tags: list[TagEvidence]
    mask_flags: list[list[str]]
    grid: Grid


class Scan(TypedDict):
    identity: Identity
    native_payload_sha256: str
    tiles: int


class SourceReceipt(Scan):
    receipt_version: int
    source: str
    metadata: Metadata


class OutputReceipt(Scan):
    receipt_version: int
    output: str
    source_identity: Identity
    status: str
    metadata_equal: bool
    native_payloads_equal: bool
    native_bits_equal: bool
    masks_equal: bool
    mask_proof: str
    bigtiff: bool
    overviews: list[int]
    cog_errors: list[str]
    cog_warnings: list[str]


CHUNK = 1024 * 1024
MAX_TILES = 3_000_000  # Bounds tifffile's in-memory index tuples; payloads stream separately.
LAYOUT_TAGS = {324, 325}  # TileOffsets and TileByteCounts; lengths are bound in payload digest.
OVERVIEW_WARNING = "The file is greater than 512xH or 512xW, it is recommended to include internal overviews"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    require(len(data) == size, "truncated TIFF")
    return data


def framed_tiles(path: Path) -> bool:
    """Recognize GDAL's declared little-endian size leader / repeated-byte trailer."""
    with path.open("rb") as stream:
        header = read_exact(stream, 16)
        endian = "<" if header[:2] == b"II" else ">"
        big = struct.unpack(endian + "H", header[2:4])[0] == 43
        offset = struct.unpack(endian + ("Q" if big else "I"), header[8:16] if big else header[4:8])[0]
        stream.seek(16 if big else 8)
        prefix = stream.read(min(max(0, offset - stream.tell()), 65536))
    leader = b"BLOCK_LEADER=SIZE_AS_UINT4\n" in prefix
    trailer = b"BLOCK_TRAILER=LAST_4_BYTES_REPEATED\n" in prefix
    require(leader == trailer, "unsupported partial GDAL tile framing")
    return leader


def inspect(path: Path, *, output: bool) -> tuple[Metadata, tuple[int, ...], tuple[int, ...]]:
    """Fail closed on non-GRIT storage or omitted metadata, including unknown tags."""
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        require(isinstance(page, tifffile.TiffPage), "missing native IFD")
        if not isinstance(page, tifffile.TiffPage):
            raise ValueError("missing native IFD")
        require(page.is_tiled and page.tilewidth == page.tilelength == 512, "expected 512-square tiles")
        require(page.compression in (8, 32946) and page.predictor == 1, "expected DEFLATE without predictor")
        require(page.samplesperpixel == 1, "expected one sample")
        require(not page.subifds, "SubIFDs are unsupported")
        count = page.tags[324].count
        require(0 < count <= MAX_TILES, "tile index exceeds memory bound")
        offsets, lengths = page.dataoffsets, page.databytecounts
        require(len(offsets) == len(lengths) == count, "tile index length mismatch")
        require(
            count == ((page.imagewidth + 511) // 512) * ((page.imagelength + 511) // 512),
            "tile index does not cover native grid",
        )
        end = 0
        size = path.stat().st_size
        for offset, length in zip(offsets, lengths, strict=True):
            require(
                length > 0 and offset >= end and offset + length <= size,
                "sparse, overlapping, unordered or out-of-bounds tile",
            )
            end = offset + length
        tags: list[TagEvidence] = []
        with path.open("rb") as stream:
            for tag in page.tags.values():
                if tag.code in LAYOUT_TAGS:
                    continue
                require(tag.valuebytecount <= CHUNK, "metadata exceeds bounded tag size")
                stream.seek(tag.valueoffset)
                tags.append(
                    {
                        "code": tag.code,
                        "dtype": int(tag.dtype),
                        "count": tag.count,
                        "hex": read_exact(stream, tag.valuebytecount).hex(),
                    }
                )
        pages = list(tif.pages)
        require(
            all(isinstance(p, tifffile.TiffPage) and not p.is_mask for p in pages),
            "internal masks require a separate complete proof",
        )
        require(
            all(isinstance(p, tifffile.TiffPage) and p.is_reduced for p in pages[1:]),
            "unexpected extra native IFD",
        )
        if output:
            require(tif.is_bigtiff, "output must be BigTIFF")
            require(len(pages) == 1, "output contains overviews or extra IFDs")
            require(end + (4 if framed_tiles(path) else 0) == size, "output contains trailing unused bytes")
            # Both directory and out-of-line tag payloads must precede native data.
            require(page.offset < offsets[0], "IFD follows tile data")
            require(page.offset + 8 + len(page.tags) * 20 + 8 <= offsets[0], "IFD overlaps tile data")
            for tag in page.tags.values():
                require(tag.valueoffset + tag.valuebytecount <= offsets[0], "metadata follows tile data")
        byteorder = tif.byteorder
    with rasterio.open(path) as src:
        require(src.files == [str(path)], "external files/masks are unsupported")
        flags = [[flag.name for flag in band] for band in src.mask_flag_enums]
        require(
            all(band in (["nodata"], ["all_valid"]) for band in flags),
            "only nodata-derived or all-valid masks are supported",
        )
        grid: Grid = {
            "width": src.width,
            "height": src.height,
            "transform": list(src.transform),
            "crs": str(src.crs),
        }
    return {"byteorder": byteorder, "tags": tags, "mask_flags": flags, "grid": grid}, offsets, lengths


def scan(path: Path, offsets: tuple[int, ...], lengths: tuple[int, ...], *, framed: bool = False) -> Scan:
    """One sequential file pass binds whole bytes and each ordered tile's length and hash."""
    whole = hashlib.sha256()
    native = hashlib.sha256(b"hfx-native-compressed-tiles-v1\0")
    size = path.stat().st_size
    with path.open("rb") as stream:
        position = 0
        for offset, length in zip(offsets, lengths, strict=True):
            gap_tail = b""
            while position < offset:
                data = read_exact(stream, min(CHUNK, offset - position))
                whole.update(data)
                gap_tail = (gap_tail + data)[-4:]
                position += len(data)
            if framed:
                require(gap_tail == struct.pack("<I", length), "invalid GDAL tile size leader")
            tile = hashlib.sha256()
            tile_tail = b""
            remaining = length
            while remaining:
                data = read_exact(stream, min(CHUNK, remaining))
                whole.update(data)
                tile.update(data)
                tile_tail = (tile_tail + data)[-4:]
                remaining -= len(data)
                position += len(data)
            if framed:
                trailer = read_exact(stream, 4)
                require(trailer == tile_tail, "invalid GDAL tile trailer")
                whole.update(trailer)
                position += 4
            native.update(struct.pack("<Q", length))
            native.update(tile.digest())
        while position < size:
            data = read_exact(stream, min(CHUNK, size - position))
            whole.update(data)
            position += len(data)
        stream.seek(0)
        head = hashlib.sha256(read_exact(stream, min(65536, size))).hexdigest()
        stream.seek(max(0, size - 65536))
        tail = hashlib.sha256(read_exact(stream, min(65536, size))).hexdigest()
    return {
        "identity": {"size_bytes": size, "sha256": whole.hexdigest(), "head_sha256": head, "tail_sha256": tail},
        "native_payload_sha256": native.hexdigest(),
        "tiles": len(offsets),
    }


def capture_source(path: Path, trusted_sha256: str) -> SourceReceipt:
    path = path.resolve()
    metadata, offsets, lengths = inspect(path, output=False)
    result = scan(path, offsets, lengths, framed=framed_tiles(path))
    require(result["identity"]["sha256"] == trusted_sha256, "source does not match trusted SHA-256")
    return {"receipt_version": 1, "source": str(path), "metadata": metadata, **result}


def verify_output(path: Path, source: SourceReceipt) -> OutputReceipt:
    """Original receipt, not mutated local source, is the raw-copy reference."""
    require(source.get("receipt_version") == 1, "unsupported source receipt")
    path = path.resolve()
    metadata, offsets, lengths = inspect(path, output=True)
    require(metadata == source["metadata"], "native metadata changed (including mask/grid/unknown tags)")
    result = scan(path, offsets, lengths, framed=framed_tiles(path))
    require(
        result["tiles"] == source["tiles"] and result["native_payload_sha256"] == source["native_payload_sha256"],
        "native compressed tile payloads changed",
    )
    valid, errors, warnings = cog_validate(str(path), strict=False)
    require(
        valid and not errors and all(w == OVERVIEW_WARNING for w in warnings),
        f"unexpected layout validation result: {errors}, {warnings}",
    )
    return {
        "receipt_version": 1,
        "output": str(path),
        **result,
        "source_identity": source["identity"],
        "status": "passed",
        "metadata_equal": True,
        "native_payloads_equal": True,
        "native_bits_equal": True,
        "masks_equal": True,
        "mask_proof": "identical compressed values and nodata/all-valid interpretation",
        "bigtiff": True,
        "overviews": [],
        "cog_errors": errors,
        "cog_warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture-source")
    capture.add_argument("path", type=Path)
    capture.add_argument("trusted_sha256")
    verify = commands.add_parser("verify-output")
    verify.add_argument("path", type=Path)
    verify.add_argument("source_receipt", type=Path)
    for command in (capture, verify):
        command.add_argument("receipt", type=Path)
    args = parser.parse_args()
    require(not args.receipt.exists(), "refusing to overwrite receipt")
    result: SourceReceipt | OutputReceipt
    if args.command == "capture-source":
        result = capture_source(args.path, args.trusted_sha256)
    else:
        result = verify_output(args.path, cast(SourceReceipt, json.loads(args.source_receipt.read_text())))
    with args.receipt.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
