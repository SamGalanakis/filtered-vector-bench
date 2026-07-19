"""Exact cosine ground truth over each eligible filtered subset."""

from __future__ import annotations

from pathlib import Path
import math
from collections.abc import Sequence
from typing import Any, cast

import numpy as np

from fvb.data import DataArtifacts, tenant_name


def compute_ground_truth(artifacts: DataArtifacts, selectivities: tuple[float, ...], k: int,
                         batch_rows: int) -> Path:
    """Compute exact top-K IDs for every query and selectivity using batched matrix products."""
    output = artifacts.directory / f"ground-truth-k{k}.npz"
    if output.exists():
        return output
    vectors = np.load(artifacts.vectors, mmap_mode="r")
    tenants = np.load(artifacts.tenants, mmap_mode="r")
    queries = np.load(artifacts.queries, mmap_mode="r")
    results: dict[str, np.ndarray] = {}
    for selectivity in selectivities:
        eligible = (np.arange(len(vectors), dtype=np.int64) if selectivity == 1.0 else
                    np.flatnonzero(tenants == tenant_name(selectivity)))
        best_scores = np.full((len(queries), k), -np.inf, dtype=np.float32)
        best_ids = np.full((len(queries), k), -1, dtype=np.int64)
        for begin in range(0, len(eligible), batch_rows):
            ids = eligible[begin:begin + batch_rows]
            scores = np.asarray(queries) @ np.asarray(vectors[ids]).T
            candidate_scores = np.concatenate((best_scores, scores), axis=1)
            candidate_ids = np.concatenate((best_ids, np.broadcast_to(ids, scores.shape)), axis=1)
            take = np.argpartition(candidate_scores, -k, axis=1)[:, -k:]
            best_scores = np.take_along_axis(candidate_scores, take, axis=1)
            best_ids = np.take_along_axis(candidate_ids, take, axis=1)
        ordering = np.argsort(best_scores, axis=1)[:, ::-1]
        results[f"s_{selectivity:.8g}"] = np.take_along_axis(best_ids, ordering, axis=1)
    np.savez_compressed(output, **cast(dict[str, Any], results))
    return output


def load_truth(path: Path, selectivity: float) -> np.ndarray:
    """Load exact IDs for one selectivity tier."""
    with np.load(path, allow_pickle=False) as archive:
        return np.asarray(archive[f"s_{selectivity:.8g}"], dtype=np.int64)


def recall_at_k(actual: list[int], expected: np.ndarray, k: int) -> float:
    """Compute set recall against an exact top-K row."""
    wanted = {int(value) for value in expected[:k] if value >= 0}
    if not wanted:
        return 1.0 if not actual else 0.0
    return len(set(actual[:k]) & wanted) / len(wanted)


def ndcg_at_k(relevances: Sequence[float], ideal_relevances: Sequence[float], k: int) -> float:
    """Compute nDCG@K from observed and ideal graded relevance sequences."""
    def dcg(values: Sequence[float]) -> float:
        return float(sum(
            (2.0 ** float(relevance) - 1.0) / math.log2(rank + 2)
            for rank, relevance in enumerate(values[:k])
        ))

    ideal = dcg(sorted(ideal_relevances, reverse=True))
    if ideal == 0:
        return 0.0
    return dcg(relevances) / ideal
