from __future__ import annotations

import numpy as np
import pyarrow as pa
import pytest

from experiments.data_interface.oracles.catchment_flow_oracle import membership


def test_supplied_split_reconvergence_sparse_and_separate_tiers() -> None:
    # Flow 41 -> 7/90 -> 800, independent tier1 isolated 105; component ID1 unknown.
    table = pa.table(
        {
            "id": pa.array([41, 7, 90, 800, 105, 1], type=pa.int64()),
            "level": pa.array([1, 1, 1, 1, 1, 0], type=pa.int16()),
            "upstream_ids": pa.array([[], [41], [41], [7, 90], [], []], type=pa.list_(pa.int64())),
        }
    )
    availability = {0: "not_supplied", 1: "supplied"}
    np.testing.assert_array_equal(membership(table, 800, availability), [7, 41, 90, 800])
    np.testing.assert_array_equal(membership(table, 41, availability, reverse=True), [7, 41, 90, 800])
    np.testing.assert_array_equal(membership(table, 105, availability), [105])
    assert membership(table, 1, availability) is None
    with pytest.raises(KeyError):
        membership(table, 2, availability)


def test_cross_tier_consumed_edge_rejected() -> None:
    table = pa.table(
        {
            "id": pa.array([41, 1], type=pa.int64()),
            "level": pa.array([1, 0], type=pa.int16()),
            "upstream_ids": pa.array([[1], []], type=pa.list_(pa.int64())),
        }
    )
    with pytest.raises(ValueError, match="cross-tier"):
        membership(table, 41, {0: "not_supplied", 1: "supplied"})


def test_multi_seed_union_keeps_reconvergence_once_and_unknown_separate() -> None:
    from experiments.data_interface.oracles.catchment_flow_oracle import supplied_union

    table = pa.table(
        {
            "id": pa.array([41, 7, 90, 800, 1], type=pa.int64()),
            "level": pa.array([1, 1, 1, 1, 0], type=pa.int16()),
            "upstream_ids": pa.array([[], [41], [41], [7, 90], []], type=pa.list_(pa.int64())),
        }
    )
    availability = {0: "not_supplied", 1: "supplied"}
    selected, unknown = supplied_union({seed: membership(table, seed, availability) for seed in [7, 90, 1]})
    np.testing.assert_array_equal(selected, [7, 41, 90])
    assert unknown == [1]


def test_window_seeds_are_bbox_overlap_not_containment() -> None:
    from experiments.data_interface.oracles.catchment_flow_oracle import window_seeds

    ids = np.array([41, 7, 90], dtype=np.int64)
    tiers = np.array([0, 0, 1], dtype=np.int16)
    bounds = np.array([[-2.0, 0.0, 2.0, 2.0], [1.0, 1.0, 1.0, 1.0], [0.0, 0.0, 1.0, 1.0]], dtype=np.float32)
    np.testing.assert_array_equal(window_seeds(ids, tiers, bounds, [1.0, 1.0, 1.0, 1.0], 0), [41, 7])
