"""Build and fully verify the spatial layout from pinned normalized inputs.

No network access, original-source normalization, raster reads or publication.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import shutil
from pathlib import Path
from time import perf_counter
from typing import Any

from hfx.candidates import fingerprint

REPRESENTATION = "spatial-geoparquet-adjacency"
ADDRESSING = {"block": "zero-based Parquet row group", "row": "zero-based row within group"}
# Superseded physical declarations, not source semantics.
PHYSICAL = {
    "artifacts",
    "catchments",
    "graph",
    "lookup",
    "directory",
    "index_batch_rows",
    "catchment_batch_bytes",
    "rivers",
    "river_nodes",
    "categorical_columns",
    "source_manifest",
    "local_associations",
}


def _progress(phase: str, started: float, output: Path) -> None:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(
        json.dumps(
            {
                "phase": phase,
                "elapsed_s": perf_counter() - started,
                "process_lifetime_peak_rss_bytes": int(peak if platform.system() == "Darwin" else peak * 1024),
                "free_disk_bytes": shutil.disk_usage(output).free,
            }
        ),
        flush=True,
    )


def _source(source: Path, digest: str) -> tuple[bytes, dict[str, Any]]:
    raw = (source / "manifest.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("source manifest differs from trusted digest")
    manifest = json.loads(raw)
    if manifest["format_version"] != "0.4.0" or manifest["crs"] != "EPSG:4326":
        raise ValueError("requires normalized 0.4.0 EPSG:4326 input")
    return raw, manifest


def _local(root: Path, name: str) -> Path:
    path = root / name
    if Path(name).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"artifact escapes bundle: {name}")
    return path


def _families(manifest: dict[str, Any]) -> dict[str, str]:
    result = {"catchments": manifest["catchments"]}
    for domain in ("rivers", "river_nodes"):
        if domain in manifest:
            result[domain] = manifest[domain]["data"]
    if "river_nodes" in result and "rivers" not in result:
        raise ValueError("river nodes require rivers")
    return result


def _check_inputs(source: Path, manifest: dict[str, Any]) -> None:
    names = list(_families(manifest).values())
    if "graph" in manifest:
        names.append(manifest["graph"])
    elif any(entry["status"] != "not_supplied" for entry in manifest["catchment_connectivity"]):
        raise ValueError("supplied catchment connectivity requires graph")
    if "rivers" in manifest:
        names.append(manifest["rivers"]["graph"])
    if "local_associations" in manifest:
        names.append(manifest["local_associations"]["data"])
    for name in names:
        if fingerprint(_local(source, name)) != manifest["artifacts"][name]:
            raise ValueError(f"source artifact differs: {name}")


def _provenance(original: dict[str, Any]) -> dict[str, Any]:
    return {
        name: identity
        for name, identity in original["artifacts"].items()
        if Path(name).suffix.lower() not in {".arrow", ".parquet", ".tif", ".tiff"} and "directory" not in name
    }


def _semantics(original: dict[str, Any], families: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in original.items() if key not in PHYSICAL}
    remap = {_families(original)[family]: declaration["data"] for family, declaration in families.items()}
    physical_domain_keys = {"data", "lookup", "directory", "graph", "count", "batch_bytes", "index_batch_rows"}
    result["source_domain_metadata"] = {
        domain: {key: value for key, value in original.get(domain, {}).items() if key not in physical_domain_keys}
        for domain in ("rivers", "river_nodes")
        if domain in families
    }
    result["categorical_columns"] = [
        {**entry, "artifact": remap.get(entry["artifact"], entry["artifact"])}
        for entry in original.get("categorical_columns", [])
    ]
    return result


def build(
    source: Path, output: Path, *, source_manifest_sha256: str, rows: int = 8192, budget: int = 8388608
) -> dict[str, Any]:
    from hfx.relationships import build_relationships
    from hfx.spatial_features import build_features

    if rows <= 0 or budget <= 0:
        raise ValueError("group limits must be positive")
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError("output must be outside source bundle")
    raw, original = _source(source, source_manifest_sha256)
    _check_inputs(source, original)
    output.mkdir(parents=True, exist_ok=False)
    families = {}
    for family, name in _families(original).items():
        started = perf_counter()
        families[family] = build_features(source / name, output, family, rows=rows, budget=budget)
        _progress(f"build {family}", started, output)
    started = perf_counter()
    relationships = build_relationships(source, output, families, batch_rows=rows)
    _progress("build relationships", started, output)
    # Keep every non-vector provenance file, never a second full feature representation.
    # Original artifact identities remain discoverable in the exact source manifest.
    for name, identity in _provenance(original).items():
        src = _local(source, name)
        if fingerprint(src) != identity:
            raise ValueError(f"source provenance differs: {name}")
        destination = _local(output, name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or name in {"manifest.json", "source-manifest.json"}:
            raise ValueError(f"provenance name conflicts: {name}")
        shutil.copyfile(src, destination)
    (output / "source-manifest.json").write_bytes(raw)
    manifest = {
        **_semantics(original, families),
        "representation": REPRESENTATION,
        "representation_version": 1,
        "families": families,
        "relationships": relationships,
        "source_manifest": "source-manifest.json",
        "input_manifest_sha256": source_manifest_sha256,
        "addressing": ADDRESSING,
        "artifacts": {
            p.relative_to(output).as_posix(): fingerprint(p) for p in sorted(output.rglob("*")) if p.is_file()
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def verify(source: Path, output: Path, *, source_manifest_sha256: str) -> dict[str, Any]:
    from hfx.relationships import verify_relationships
    from hfx.spatial_features import verify_features

    raw, original = _source(source, source_manifest_sha256)
    _check_inputs(source, original)
    manifest = json.loads((output / "manifest.json").read_bytes())
    if manifest["representation"] != REPRESENTATION or manifest["representation_version"] != 1:
        raise ValueError("stored representation differs")
    if manifest.get("addressing") != ADDRESSING:
        raise ValueError("address conventions differ")
    if set(manifest["families"]) != set(_families(original)) or set(manifest["relationships"]) != set(
        _families(original)
    ):
        raise ValueError("feature/relationship domain coverage differs")
    if (
        manifest["input_manifest_sha256"] != source_manifest_sha256
        or manifest["source_manifest"] != "source-manifest.json"
        or (output / "source-manifest.json").read_bytes() != raw
    ):
        raise ValueError("source manifest binding differs")
    if any(manifest.get(key) != value for key, value in _semantics(original, manifest["families"]).items()):
        raise ValueError("source declarations differ")
    expected_files = {"source-manifest.json", *_provenance(original)}
    for declaration in [*manifest["families"].values(), *manifest["relationships"].values()]:
        expected_files.update(str(declaration[key]) for key in ("data", "directory"))
    expected_files.update(str(declaration["lookup"]) for declaration in manifest["families"].values())
    if set(manifest["artifacts"]) != expected_files:
        raise ValueError("artifact inventory differs")
    for name, identity in _provenance(original).items():
        if manifest["artifacts"].get(name) != identity:
            raise ValueError(f"source provenance differs: {name}")
    for name, identity in manifest["artifacts"].items():
        if fingerprint(_local(output, name)) != identity:
            raise ValueError(f"output artifact differs: {name}")
    features = {}
    for family, name in _families(original).items():
        started = perf_counter()
        features[family] = verify_features(source / name, output, manifest["families"][family])
        _progress(f"verify {family}", started, output)
    started = perf_counter()
    relationships = verify_relationships(source, output, manifest["families"], manifest["relationships"])
    _progress("verify relationships", started, output)
    return {
        "status": "passed",
        "input_manifest_sha256": source_manifest_sha256,
        "manifest_sha256": hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest(),
        "features": features,
        "relationships": relationships,
        "scope": "Complete normalized-input comparison; original-source fidelity is inherited, not rerun. Raster access and public delivery are not checked.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "verify"])
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-manifest-sha256", required=True)
    parser.add_argument("--rows", type=int, default=8192)
    parser.add_argument("--budget", type=int, default=8388608)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists() or any(
        args.report.resolve().is_relative_to(path.resolve()) for path in (args.source, args.output)
    ):
        raise ValueError("report must be a new path outside input/output bundles")
    if args.action == "build":
        build(
            args.source,
            args.output,
            source_manifest_sha256=args.source_manifest_sha256,
            rows=args.rows,
            budget=args.budget,
        )
    result = verify(args.source, args.output, source_manifest_sha256=args.source_manifest_sha256)
    with args.report.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
