"""Deterministic clustered synthetic data stored as memory-mapped NumPy arrays."""

from __future__ import annotations

import hashlib
import json
import math
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
    texts: Path | None = None
    document_clusters: Path | None = None
    query_texts: Path | None = None
    tier_queries: Path | None = None
    tier_query_clusters: Path | None = None
    tier_query_texts: Path | None = None


def tenant_name(selectivity: float) -> str | None:
    """Map selectivity to its stable tenant label; 1.0 means no filter."""
    if selectivity == 1.0:
        return None
    return f"tenant_s{format(selectivity, '.8g').replace('.', '_')}"


def _unit_rows(values: NDArray[np.float32]) -> NDArray[np.float32]:
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return np.asarray(values / np.maximum(norms, np.finfo(np.float32).tiny), dtype=np.float32)


def _vocabularies(config: BenchmarkConfig) -> tuple[list[list[str]], list[str]]:
    """Build seeded, cluster-distinct topic terms and one shared background vocabulary."""
    def alpha_code(value: int, width: int) -> str:
        letters = []
        for _ in range(width):
            letters.append(chr(ord("a") + value % 26))
            value //= 26
        return "".join(reversed(letters))

    rng = np.random.default_rng(config.seed + 0xF7A5)
    topic_width = max(2, math.ceil(math.log(max(config.text.topic_vocabulary_size, 2), 26)))
    cluster_width = max(2, math.ceil(math.log(max(config.clusters, 2), 26)))
    topics: list[list[str]] = []
    for cluster in range(config.clusters):
        order = rng.permutation(config.text.topic_vocabulary_size)
        topics.append([
            f"t{alpha_code(cluster, cluster_width)}{alpha_code(int(term), topic_width)}"
            for term in order
        ])
    background_width = max(
        3, math.ceil(math.log(max(config.text.background_vocabulary_size, 2), 26))
    )
    order = rng.permutation(config.text.background_vocabulary_size)
    background = [f"b{alpha_code(int(term), background_width)}" for term in order]
    return topics, background


def _zipf_probabilities(size: int) -> NDArray[np.float64]:
    ranks = np.arange(1, size + 1, dtype=np.float64)
    weights = 1.0 / ranks
    return np.asarray(weights / weights.sum(), dtype=np.float64)


def _generate_text_artifacts(config: BenchmarkConfig, paths: DataArtifacts, n_docs: int) -> None:
    """Generate fixed-width byte documents in chunks and query text aligned to clusters."""
    assert paths.texts is not None
    assert paths.document_clusters is not None
    assert paths.query_texts is not None
    document_clusters = np.load(paths.document_clusters, mmap_mode="r")
    topics, background = _vocabularies(config)
    longest_term = max(max(map(len, background)), max(len(term) for vocab in topics for term in vocab))
    max_document_bytes = 200 * longest_term + 199
    texts = np.lib.format.open_memmap(
        paths.texts, mode="w+", dtype=f"S{max_document_bytes}", shape=(n_docs,)
    )
    topic_probabilities = _zipf_probabilities(config.text.topic_vocabulary_size)
    background_probabilities = _zipf_probabilities(config.text.background_vocabulary_size)
    for begin in range(0, n_docs, config.data_chunk_rows):
        end = min(n_docs, begin + config.data_chunk_rows)
        for row_id in range(begin, end):
            # Per-row seeding makes text independent of chunk and adapter batching choices.
            row_seed = (config.seed + 0xD0C5 + row_id * 0x9E3779B1) & ((1 << 64) - 1)
            rng = np.random.default_rng(row_seed)
            token_count = int(rng.integers(80, 201))
            topic_count = int(rng.binomial(token_count, 0.35))
            topic = topics[int(document_clusters[row_id])]
            tokens = [
                topic[index] for index in rng.choice(
                    len(topic), size=topic_count, p=topic_probabilities
                )
            ]
            tokens.extend(
                background[index] for index in rng.choice(
                    len(background), size=token_count - topic_count,
                    p=background_probabilities,
                )
            )
            rng.shuffle(tokens)
            texts[row_id] = " ".join(tokens).encode("ascii")
    texts.flush()

    query_files = [(paths.query_clusters, paths.query_texts)]
    if paths.tier_query_clusters is not None:
        assert paths.tier_query_texts is not None
        query_files.append((paths.tier_query_clusters, paths.tier_query_texts))
    for query_clusters_path, query_texts_path in query_files:
        assert query_texts_path is not None
        query_clusters = np.load(query_clusters_path, mmap_mode="r")
        query_rng = np.random.default_rng(config.seed + 0x0A11CE)
        query_values: list[str] = []
        for cluster in np.asarray(query_clusters).flat:
            count = int(query_rng.integers(3, 7))
            indices = query_rng.choice(
                config.text.topic_vocabulary_size, size=count, replace=False,
                p=topic_probabilities,
            )
            query_values.append(" ".join(topics[int(cluster)][index] for index in indices))
        max_query_bytes = max(map(len, query_values), default=1)
        query_texts = np.lib.format.open_memmap(
            query_texts_path, mode="w+", dtype=f"S{max_query_bytes}", shape=query_clusters.shape
        )
        query_texts[:] = np.asarray(
            [value.encode("ascii") for value in query_values], dtype=f"S{max_query_bytes}"
        ).reshape(query_clusters.shape)
        query_texts.flush()


def _ensure_tenant_present_pools(
    config: BenchmarkConfig,
    tenants: NDArray[np.str_],
    document_clusters: NDArray[np.int32],
) -> None:
    """Minimally repair random tenants so every filtered tier has one viable topic."""
    minimum = math.ceil(3 * config.k)
    repair_rng = np.random.default_rng(config.seed + 0x71E2A17)
    for selectivity in (value for value in config.selectivities if value < 1.0):
        tenant = tenant_name(selectivity)
        assert tenant is not None
        tenant_ids = np.flatnonzero(tenants == tenant)
        if len(tenant_ids) < minimum:
            raise ValueError(
                f"tenant_present requires at least {minimum} rows in {tenant}; "
                f"configured tier has {len(tenant_ids)}"
            )
        counts = np.bincount(
            np.asarray(document_clusters[tenant_ids], dtype=np.int64),
            minlength=config.clusters,
        )
        if int(counts.max()) >= minimum:
            continue
        target_cluster = int(np.argmax(counts))
        needed = minimum - int(counts[target_cluster])
        incoming = np.flatnonzero(
            (tenants == "tenant_background") & (document_clusters == target_cluster)
        )
        outgoing = tenant_ids[document_clusters[tenant_ids] != target_cluster]
        if len(incoming) < needed or len(outgoing) < needed:
            raise ValueError(
                f"cannot construct a {minimum}-row relevant pool for {tenant}"
            )
        incoming = repair_rng.choice(incoming, size=needed, replace=False)
        outgoing = repair_rng.choice(outgoing, size=needed, replace=False)
        tenants[incoming] = tenant
        tenants[outgoing] = "tenant_background"


def _generate_tier_queries(
    config: BenchmarkConfig,
    paths: DataArtifacts,
    centers: NDArray[np.float32],
    dimensions: int,
    n_docs: int,
) -> None:
    """Generate per-tier vectors from query clusters with a guaranteed relevant pool."""
    assert paths.document_clusters is not None
    assert paths.tier_queries is not None
    assert paths.tier_query_clusters is not None
    document_clusters = np.load(paths.document_clusters, mmap_mode="r")
    tenants = np.load(paths.tenants, mmap_mode="r")
    minimum = math.ceil(3 * config.k)
    rng = np.random.default_rng(
        config.seed + 0x7E17 + dimensions * 1_000_003 + n_docs
    )
    cluster_rows = np.lib.format.open_memmap(
        paths.tier_query_clusters, mode="w+", dtype=np.int32,
        shape=(len(config.selectivities), config.n_queries),
    )
    vector_rows = np.lib.format.open_memmap(
        paths.tier_queries, mode="w+", dtype=np.float32,
        shape=(len(config.selectivities), config.n_queries, dimensions),
    )
    for tier_index, selectivity in enumerate(config.selectivities):
        tenant = tenant_name(selectivity)
        eligible = (np.ones(len(document_clusters), dtype=np.bool_) if tenant is None else
                    np.asarray(tenants == tenant, dtype=np.bool_))
        counts = np.bincount(
            np.asarray(document_clusters[eligible], dtype=np.int64),
            minlength=config.clusters,
        )
        eligible_clusters = np.flatnonzero(counts >= minimum)
        if not len(eligible_clusters):
            raise ValueError(
                f"tenant_present found no cluster with at least {minimum} relevant rows "
                f"for selectivity {selectivity}"
            )
        selected = rng.choice(eligible_clusters, size=config.n_queries, replace=True)
        noise = rng.normal(
            0, config.cluster_sigma, size=(config.n_queries, dimensions)
        ).astype(np.float32)
        cluster_rows[tier_index] = selected
        vector_rows[tier_index] = _unit_rows(centers[selected] + noise)
    cluster_rows.flush()
    vector_rows.flush()


def text_queries_for_tier(
    artifacts: DataArtifacts,
    selectivities: tuple[float, ...],
    selectivity: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load the text, vector, and cluster query rows for one selectivity tier."""
    assert artifacts.query_texts is not None
    if artifacts.tier_queries is None:
        return (
            np.load(artifacts.query_texts, mmap_mode="r"),
            np.load(artifacts.queries, mmap_mode="r"),
            np.load(artifacts.query_clusters, mmap_mode="r"),
        )
    assert artifacts.tier_query_texts is not None
    assert artifacts.tier_query_clusters is not None
    tier_index = selectivities.index(selectivity)
    return (
        np.load(artifacts.tier_query_texts, mmap_mode="r")[tier_index],
        np.load(artifacts.tier_queries, mmap_mode="r")[tier_index],
        np.load(artifacts.tier_query_clusters, mmap_mode="r")[tier_index],
    )


def generate_data(config: BenchmarkConfig, dimensions: int, n_docs: int, root: Path) -> DataArtifacts:
    """Generate or reuse vectors, tenant labels, and queries for a matrix cell."""
    expected = {
        "seed": config.seed, "dimensions": dimensions, "n_docs": n_docs,
        "clusters": config.clusters, "cluster_sigma": config.cluster_sigma,
        "selectivities": list(config.selectivities), "n_queries": config.n_queries,
        "generator_version": 3,
        "text": config.normalized()["text"],
    }
    if config.query_topics == "tenant_present":
        expected["generator_version"] = 4
        expected["query_topics"] = config.query_topics
    data_hash = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()[:12]
    directory = root / f"d{dimensions}-n{n_docs}-s{config.seed}-{data_hash}"
    directory.mkdir(parents=True, exist_ok=True)
    paths = DataArtifacts(
        directory, directory / "vectors.npy", directory / "tenants.npy",
        directory / "queries.npy", directory / "query_clusters.npy",
        directory / "texts.npy" if config.text.enabled else None,
        directory / "document_clusters.npy" if config.text.enabled else None,
        directory / "query_texts.npy" if config.text.enabled else None,
        directory / "tier_queries.npy"
        if config.text.enabled and config.query_topics == "tenant_present" else None,
        directory / "tier_query_clusters.npy"
        if config.text.enabled and config.query_topics == "tenant_present" else None,
        directory / "tier_query_texts.npy"
        if config.text.enabled and config.query_topics == "tenant_present" else None,
    )
    manifest_path = directory / "manifest.json"
    required_paths = [paths.vectors, paths.tenants, paths.queries, paths.query_clusters]
    required_paths.extend(
        path for path in (
            paths.texts, paths.document_clusters, paths.query_texts, paths.tier_queries,
            paths.tier_query_clusters, paths.tier_query_texts,
        )
        if path is not None
    )
    if manifest_path.exists() and all(p.exists() for p in required_paths):
        if json.loads(manifest_path.read_text(encoding="utf-8")) == expected:
            return paths
        raise RuntimeError(f"data manifest mismatch in {directory}; remove that directory")

    rng = np.random.default_rng(config.seed + dimensions * 1_000_003 + n_docs)
    centers = _unit_rows(rng.normal(size=(config.clusters, dimensions)).astype(np.float32))
    vectors = np.lib.format.open_memmap(paths.vectors, mode="w+", dtype=np.float32,
                                        shape=(n_docs, dimensions))
    document_clusters = (
        np.lib.format.open_memmap(paths.document_clusters, mode="w+", dtype=np.int32,
                                  shape=(n_docs,))
        if paths.document_clusters is not None else None
    )
    for begin in range(0, n_docs, config.data_chunk_rows):
        end = min(n_docs, begin + config.data_chunk_rows)
        cluster_ids = rng.integers(0, config.clusters, size=end - begin)
        if document_clusters is not None:
            document_clusters[begin:end] = cluster_ids
        noise = rng.normal(0, config.cluster_sigma, size=(end - begin, dimensions)).astype(np.float32)
        vectors[begin:end] = _unit_rows(centers[cluster_ids] + noise)
    vectors.flush()
    if document_clusters is not None:
        document_clusters.flush()

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
    if config.text.enabled and config.query_topics == "tenant_present":
        assert document_clusters is not None
        _ensure_tenant_present_pools(config, tenants, document_clusters)
    tenants.flush()

    query_clusters = rng.integers(0, config.clusters, size=config.n_queries, dtype=np.int32)
    query_noise = rng.normal(0, config.cluster_sigma, size=(config.n_queries, dimensions)).astype(np.float32)
    queries = _unit_rows(centers[query_clusters] + query_noise)
    np.save(paths.queries, queries, allow_pickle=False)
    np.save(paths.query_clusters, query_clusters, allow_pickle=False)
    if config.text.enabled:
        if config.query_topics == "tenant_present":
            _generate_tier_queries(config, paths, centers, dimensions, n_docs)
        _generate_text_artifacts(config, paths, n_docs)
    manifest_path.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return paths


def iter_rows(artifacts: DataArtifacts, batch_size: int) -> Iterator[
    list[tuple[int, str, NDArray[np.float32], str | None]]
]:
    """Yield row batches without loading the vector or text corpus into RAM."""
    vectors = np.load(artifacts.vectors, mmap_mode="r")
    tenants = np.load(artifacts.tenants, mmap_mode="r")
    texts = np.load(artifacts.texts, mmap_mode="r") if artifacts.texts is not None else None
    for begin in range(0, len(vectors), batch_size):
        end = min(len(vectors), begin + batch_size)
        yield [
            (
                row_id, str(tenants[row_id]), vectors[row_id],
                bytes(texts[row_id]).decode("ascii") if texts is not None else None,
            )
            for row_id in range(begin, end)
        ]
