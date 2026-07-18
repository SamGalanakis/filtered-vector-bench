"""Deterministic clustered synthetic data stored as memory-mapped NumPy arrays."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
from numpy.typing import NDArray

from fvb.config import BenchmarkConfig


@dataclass(frozen=True)
class DataArtifacts:
    """Paths to one generated workload cell."""

    directory: Path
    vectors: Path
    tenants: Path
    queries: Path
    query_clusters: Path


def tenant_name(selectivity: float) -> str | None:
    """Map selectivity to its stable tenant label; 1.0 means no filter."""
    if selectivity == 1.0:
        return None
    return f"tenant_s{format(selectivity, '.8g').replace('.', '_')}"


def _unit_rows(values: NDArray[np.float32]) -> NDArray[np.float32]:
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return np.asarray(values / np.maximum(norms, np.finfo(np.float32).tiny), dtype=np.float32)


def generate_data(config: BenchmarkConfig, dimensions: int, n_docs: int, root: Path) -> DataArtifacts:
    """Generate or reuse vectors, tenant labels, and queries for a matrix cell."""
    expected = {
        "seed": config.seed, "dimensions": dimensions, "n_docs": n_docs,
        "clusters": config.clusters, "cluster_sigma": config.cluster_sigma,
        "selectivities": list(config.selectivities), "n_queries": config.n_queries,
    }
    data_hash = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()[:12]
    directory = root / f"d{dimensions}-n{n_docs}-s{config.seed}-{data_hash}"
    directory.mkdir(parents=True, exist_ok=True)
    paths = DataArtifacts(directory, directory / "vectors.npy", directory / "tenants.npy",
                          directory / "queries.npy", directory / "query_clusters.npy")
    manifest_path = directory / "manifest.json"
    if manifest_path.exists() and all(p.exists() for p in (
        paths.vectors, paths.tenants, paths.queries, paths.query_clusters
    )):
        if json.loads(manifest_path.read_text(encoding="utf-8")) == expected:
            return paths
        raise RuntimeError(f"data manifest mismatch in {directory}; remove that directory")

    rng = np.random.default_rng(config.seed + dimensions * 1_000_003 + n_docs)
    centers = _unit_rows(rng.normal(size=(config.clusters, dimensions)).astype(np.float32))
    vectors = np.lib.format.open_memmap(paths.vectors, mode="w+", dtype=np.float32,
                                        shape=(n_docs, dimensions))
    for begin in range(0, n_docs, config.data_chunk_rows):
        end = min(n_docs, begin + config.data_chunk_rows)
        cluster_ids = rng.integers(0, config.clusters, size=end - begin)
        noise = rng.normal(0, config.cluster_sigma, size=(end - begin, dimensions)).astype(np.float32)
        vectors[begin:end] = _unit_rows(centers[cluster_ids] + noise)
    vectors.flush()

    max_label = max(len(tenant_name(s) or "") for s in config.selectivities)
    max_label = max(max_label, len("tenant_background"))
    tenants = np.lib.format.open_memmap(paths.tenants, mode="w+", dtype=f"U{max_label}",
                                        shape=(n_docs,))
    tenants[:] = "tenant_background"
    order = rng.permutation(n_docs)
    cursor = 0
    for selectivity in sorted((s for s in config.selectivities if s < 1), reverse=True):
        count = max(1, round(n_docs * selectivity))
        count = min(count, n_docs - cursor)
        tenants[order[cursor:cursor + count]] = tenant_name(selectivity)
        cursor += count
    tenants.flush()

    query_clusters = rng.integers(0, config.clusters, size=config.n_queries, dtype=np.int32)
    query_noise = rng.normal(0, config.cluster_sigma, size=(config.n_queries, dimensions)).astype(np.float32)
    queries = _unit_rows(centers[query_clusters] + query_noise)
    np.save(paths.queries, queries, allow_pickle=False)
    np.save(paths.query_clusters, query_clusters, allow_pickle=False)
    manifest_path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return paths


def iter_rows(artifacts: DataArtifacts, batch_size: int) -> Iterator[
    list[tuple[int, str, NDArray[np.float32]]]
]:
    """Yield batches of `(source_id, tenant, vector)` rows without loading the corpus into RAM."""
    vectors = np.load(artifacts.vectors, mmap_mode="r")
    tenants = np.load(artifacts.tenants, mmap_mode="r")
    for begin in range(0, len(vectors), batch_size):
        end = min(len(vectors), begin + batch_size)
        yield [(row_id, str(tenants[row_id]), vectors[row_id]) for row_id in range(begin, end)]
