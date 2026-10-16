"""Independent source-only catchment flow oracle, not a performance benchmark.

No candidate or Pourpoint runtime imports. A sorted ID index addresses original
Arrow incoming lists; optional reverse access sorts flattened original edge IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.parquet as pq

type IDs = npt.NDArray[np.int64]


class OriginalFlow:
    def __init__(self, table: pa.Table, reverse: bool = False) -> None:
        self.ids = table["id"].combine_chunks().to_numpy()
        self.levels = table["level"].combine_chunks().to_numpy()
        self.order = np.argsort(self.ids)
        self.sorted_ids = self.ids[self.order]
        original = cast(pa.ListArray, table["upstream_ids"].combine_chunks())
        self.offsets = original.offsets.to_numpy()
        self.edges = original.values.to_numpy()
        self.reverse_keys: IDs | None = None
        self.reverse_targets: npt.NDArray[np.int64] | None = None
        if reverse:
            edge_order = np.argsort(self.edges, kind="stable")
            self.reverse_keys = self.edges[edge_order]
            targets = np.repeat(np.arange(len(self.ids), dtype=np.int64), np.diff(self.offsets))
            self.reverse_targets = targets[edge_order]

    def row(self, seed: int) -> int:
        slot = np.searchsorted(self.sorted_ids, seed)
        if slot == len(self.sorted_ids) or self.sorted_ids[slot] != seed:
            raise KeyError(seed)
        return int(self.order[slot])

    def walk(self, seed: int, availability: dict[int, str], reverse: bool = False) -> IDs | None:
        start = self.row(seed)
        tier = int(self.levels[start])
        if availability.get(tier) != "supplied":
            return None
        seen = np.zeros(len(self.ids), dtype=np.bool_)
        stack = [start]
        selected: list[int] = []
        while stack:
            row = stack.pop()
            if seen[row]:
                continue
            seen[row] = True
            selected.append(row)
            if reverse:
                assert self.reverse_keys is not None and self.reverse_targets is not None
                low, high = (
                    np.searchsorted(self.reverse_keys, self.ids[row], side="left"),
                    np.searchsorted(self.reverse_keys, self.ids[row], side="right"),
                )
                neighbors = self.reverse_targets[low:high]
            else:
                references = self.edges[self.offsets[row] : self.offsets[row + 1]]
                slots = np.searchsorted(self.sorted_ids, references)
                if np.any(slots >= len(self.ids)) or np.any(self.sorted_ids[slots] != references):
                    raise ValueError("Unresolved consumed edge")
                neighbors = self.order[slots]
            if np.any(self.levels[neighbors] != tier):
                raise ValueError("cross-tier consumed edge")
            stack.extend(int(value) for value in neighbors if not seen[value])
        return np.sort(self.ids[selected])


def membership(table: pa.Table, seed: int, availability: dict[int, str], reverse: bool = False) -> IDs | None:
    return OriginalFlow(table, reverse).walk(seed, availability, reverse)


def supplied_union(memberships: dict[int, IDs | None]) -> tuple[IDs, list[int]]:
    combined = np.array([], dtype=np.int64)
    unknown: list[int] = []
    for seed, selected in memberships.items():
        if selected is None:
            unknown.append(seed)
        else:
            combined = np.union1d(combined, selected)
    return combined, unknown


def summarize(
    original: OriginalFlow, selected: IDs, bounds: npt.NDArray[np.float32], bbox: list[float]
) -> dict[str, Any]:
    slots = np.searchsorted(original.sorted_ids, selected)
    envelopes = bounds[original.order[slots]]
    excursions = np.maximum(
        0.0,
        np.column_stack(
            [bbox[0] - envelopes[:, 0], bbox[1] - envelopes[:, 1], envelopes[:, 2] - bbox[2], envelopes[:, 3] - bbox[3]]
        ),
    )
    return {
        "inclusive_count": len(selected),
        "sorted_ids_sha256_le_i64": hashlib.sha256(np.asarray(selected, dtype="<i8").tobytes()).hexdigest(),
        "first_ids": selected[:8].tolist(),
        "last_ids": selected[-8:].tolist(),
        "bbox_envelope": [
            float(envelopes[:, 0].min()),
            float(envelopes[:, 1].min()),
            float(envelopes[:, 2].max()),
            float(envelopes[:, 3].max()),
        ]
        if len(selected)
        else None,
        "members_with_bounds_outside_small_window": int(np.count_nonzero(np.any(excursions > 0, axis=1))),
        "maximum_bbox_excursion_degrees": float(excursions.max()) if len(selected) else 0.0,
    }


def window_seeds(
    ids: IDs, levels: npt.NDArray[np.int16], bounds: npt.NDArray[np.float32], bbox: list[float], tier: int
) -> IDs:
    mask = (
        (bounds[:, 0] <= bbox[2])
        & (bounds[:, 1] <= bbox[3])
        & (bounds[:, 2] >= bbox[0])
        & (bounds[:, 3] >= bbox[1])
        & (levels == tier)
    )
    return ids[mask]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--family", choices=("catchments", "rivers"), default="catchments")
    parser.add_argument("--seeds", type=int, nargs="+")
    parser.add_argument("--tier", type=int, help="seed tier, independent per domain")
    parser.add_argument("--windows", nargs="+", default=["small", "elongated"])
    parser.add_argument("--reverse", action="store_true")
    parser.add_argument("--workloads", type=Path, default=Path(__file__).with_name("workloads.json"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    if args.report.resolve().is_relative_to(args.source.resolve()):
        raise ValueError("report must be outside input bundle")
    manifest_bytes = (args.source / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    windows = json.loads(args.workloads.read_text())[f"{args.family}_graph"]["windows"]
    tier = args.tier if args.tier is not None else (1 if args.family == "catchments" else 0)
    graph_name = manifest["graph"] if args.family == "catchments" else manifest["rivers"]["graph"]
    table = pq.read_table(
        args.source / graph_name,
        columns=["id", "level", "upstream_ids", "bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"],
    )
    connectivity = (
        manifest["catchment_connectivity"]
        if args.family == "catchments"
        else [{"level": int(level), "status": "supplied"} for level in np.unique(table["level"].to_numpy())]
    )
    availability: dict[int, str] = {int(entry["level"]): str(entry["status"]) for entry in connectivity}
    original = OriginalFlow(table, args.reverse)
    bounds = np.column_stack(
        [table[name].combine_chunks().to_numpy() for name in ["bbox_minx", "bbox_miny", "bbox_maxx", "bbox_maxy"]]
    )
    workflows: list[dict[str, Any]] = []
    for name in args.windows:
        window = windows[name]
        bbox = window["expanded_float32_bounds"]
        source_seeds = window_seeds(original.ids, original.levels, bounds, bbox, tier)
        expected = window["by_independent_domain_tier"][str(tier)]
        assert len(source_seeds) == expected["count"]
        assert (
            hashlib.sha256(np.sort(source_seeds).astype("<i8").tobytes()).hexdigest()
            == expected["sorted_ids_sha256_le_i64"]
        )
        seeds = args.seeds if args.seeds is not None else source_seeds.tolist()
        memberships = {seed: original.walk(seed, availability, args.reverse) for seed in seeds}
        per_seed: dict[str, Any] = {}
        for seed, selected in memberships.items():
            level = int(original.levels[original.row(seed)])
            per_seed[str(seed)] = {
                "tier": level,
                "connectivity": availability.get(level),
                **(
                    summarize(original, selected, bounds, bbox)
                    if selected is not None
                    else {
                        "membership": None,
                        "interpretation": "unknown connectivity; not known terminal or natural outlet",
                    }
                ),
            }
        union, unknown = supplied_union(memberships)
        seed_array = np.asarray(seeds, dtype=np.int64)
        closure = summarize(original, union, bounds, bbox)
        closure["count"] = closure["inclusive_count"]
        workflows.append(
            {
                "family": args.family,
                "window": name,
                "level": tier,
                "direction": "downstream" if args.reverse else "upstream",
                "expanded_window": bbox,
                "seeds": {
                    "count": len(seeds),
                    "sorted_ids_sha256_le_i64": hashlib.sha256(np.sort(seed_array).astype("<i8").tobytes()).hexdigest(),
                    "explicit_ids": seeds,
                },
                "closure": closure,
                "per_seed": per_seed,
                "unknown_seeds": unknown,
            }
        )
    result = {
        "scope": "source-only correctness oracle; no timing, geometry policy or full producer verification",
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "family": args.family,
        "graph": graph_name,
        "graph_fingerprint": manifest["artifacts"][graph_name],
        "connectivity": connectivity,
        "workflows": workflows,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "pyarrow_version": pa.__version__,
    }
    if args.family == "catchments":
        assert original.walk(1, availability, args.reverse) is None
        result["component_seed_1"] = {
            "connectivity": "not_supplied",
            "membership": None,
            "interpretation": "unknown connectivity; not known terminal or natural outlet",
        }
    with args.report.open("x") as output:
        output.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
