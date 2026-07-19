from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import yaml
from numpy.typing import NDArray

from fvb.config import load_config
from fvb.data import DataArtifacts, generate_data, tenant_name, text_queries_for_tier
from fvb.engines.base import Engine
from fvb.engines.surrealdb import MAX_LOAD_PAYLOAD_BYTES, _insert_bodies
from fvb.ground_truth import ndcg_at_k
from fvb.memsample import MemorySampler
from fvb.report import generate_report
from fvb.runner import BenchmarkRunner, CellContext, _classify_failure, _failure_phase


class _FakeEngine:
    def explain(self, vector: NDArray[np.float32], tenant: str | None, k: int, ef: int,
                mode: str = "default") -> str:
        return "Index Scan using test_hnsw"

    def plan_uses_index(self, plan: str) -> bool:
        return True

    def query(self, vector: NDArray[np.float32], tenant: str | None, k: int, ef: int,
              mode: str = "default") -> tuple[list[int], float]:
        return list(range(k)), 0.001


class _FakeSampler:
    def sample_now(self) -> None:
        pass


def test_ndcg_at_10_matches_hand_calculation() -> None:
    # Relevant documents at ranks 1 and 3: DCG = 1/log2(2) + 1/log2(4).
    # The ideal ordering puts both at ranks 1 and 2.
    expected = (1.0 + 0.5) / (1.0 + 1.0 / np.log2(3.0))

    actual = ndcg_at_k([1.0, 0.0, 1.0, 0.0], [1.0, 1.0], 10)

    assert actual == pytest.approx(expected)


def test_legacy_config_without_text_remains_vector_only(tmp_path: Path) -> None:
    raw = yaml.safe_load(Path("configs/smoke.yaml").read_text(encoding="utf-8"))
    del raw["text"]
    path = tmp_path / "vector-only.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    config = load_config(path)

    assert config.text.enabled is False
    assert config.text.fts_candidates == 40
    assert config.text.rrf_k == 60
    assert config.suites.vector is True
    assert config.suites.fts is True
    assert config.suites.hybrid is True
    assert config.query_topics == "global"


def test_tenant_present_builds_per_tier_queries_with_large_relevant_pools(
    tmp_path: Path,
) -> None:
    raw = yaml.safe_load(Path("configs/smoke.yaml").read_text(encoding="utf-8"))
    raw.update({
        "dimensions": [8],
        "scales": [3000],
        "selectivities": [1.0, 0.1, 0.01],
        "clusters": 4,
        "query_topics": "tenant_present",
        "suites": {"vector": False, "fts": True, "hybrid": True},
    })
    path = tmp_path / "tenant-present.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    config = load_config(path)

    artifacts = generate_data(config, 8, 3000, tmp_path / "data")

    assert artifacts.tier_queries is not None
    assert artifacts.tier_query_clusters is not None
    assert artifacts.tier_query_texts is not None
    document_clusters = np.load(cast(Path, artifacts.document_clusters), mmap_mode="r")
    tenants = np.load(artifacts.tenants, mmap_mode="r")
    for selectivity in config.selectivities:
        texts, vectors, query_clusters = text_queries_for_tier(
            artifacts, config.selectivities, selectivity
        )
        tenant = tenant_name(selectivity)
        eligible = (np.ones(len(tenants), dtype=np.bool_) if tenant is None else
                    np.asarray(tenants == tenant, dtype=np.bool_))
        counts = np.bincount(document_clusters[eligible], minlength=config.clusters)
        assert len(texts) == config.n_queries
        assert vectors.shape == (config.n_queries, 8)
        assert all(int(counts[int(cluster)]) >= 3 * config.k for cluster in query_clusters)
        assert int(eligible.sum()) == round(3000 * selectivity)


def test_disappeared_engine_near_cap_is_classified_with_load_phase() -> None:
    cap = 48 * 1024**3

    assert _classify_failure(
        oom_detected=False,
        engine_alive=False,
        peak_rss_bytes=int(cap * 0.96),
        memory_cap_bytes=cap,
    ) == "exceeded_memory_cap"
    assert _failure_phase("load:834000") == "load"


def test_disappeared_engine_well_below_cap_remains_an_error() -> None:
    cap = 48 * 1024**3

    assert _classify_failure(
        oom_detected=False,
        engine_alive=False,
        peak_rss_bytes=int(cap * 0.50),
        memory_cap_bytes=cap,
    ) == "error"
    assert _classify_failure(
        oom_detected=False,
        engine_alive=False,
        peak_rss_bytes=int(cap * 1.20),
        memory_cap_bytes=cap,
    ) == "error"


def test_surreal_insert_bodies_respect_row_and_payload_bounds() -> None:
    vector = np.linspace(-1, 1, 1024, dtype=np.float32)
    rows = [(row_id, "tenant_s0_1", vector) for row_id in range(500)]

    bodies = list(_insert_bodies(rows, max_rows=200))

    assert sum(count for _, count in bodies) == 500
    assert max(count for _, count in bodies) <= 200
    assert max(len(body) for body, _ in bodies) < MAX_LOAD_PAYLOAD_BYTES
    assert all(body.startswith(b"INSERT INTO item [") for body, _ in bodies)
    assert all(body.endswith(b"] RETURN NONE;") for body, _ in bodies)


def test_suite_complete_is_self_describing(tmp_path: Path) -> None:
    config = load_config(Path("configs/smoke.yaml").resolve())
    runner = BenchmarkRunner(config, tmp_path, ())
    artifacts = DataArtifacts(tmp_path, tmp_path / "vectors.npy", tmp_path / "tenants.npy",
                              tmp_path / "queries.npy", tmp_path / "query_clusters.npy")
    np.save(artifacts.queries, np.zeros((config.n_queries, 64), dtype=np.float32))
    truth = tmp_path / "truth.npz"
    truth_rows = {f"s_{value:.8g}": np.tile(np.arange(10), (config.n_queries, 1))
                  for value in config.selectivities}
    np.savez(truth, **cast(dict[str, Any], truth_rows))

    runner._suite(
        CellContext("postgres", 64, 5000, tmp_path / "cell"),
        cast(Engine, _FakeEngine()), artifacts, truth, "pre_churn",
        cast(MemorySampler, _FakeSampler()),
    )

    event = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()[0])
    required = {
        "cell_id", "tier", "ef", "mode", "p50_ms", "p95_ms", "mean_recall_at_10",
        "underfill", "mean_result_count", "plan", "plan_uses_index",
    }
    assert required <= event.keys()
    assert event["tier"] == "unfiltered"
    assert event["plan"] == "Index Scan using test_hnsw"


def test_failed_scale_is_annotated_and_not_rendered_as_zero(tmp_path: Path) -> None:
    metadata = {
        "config_sha256": "test",
        "hostname": "test",
        "platform": "test",
        "python": "3.13",
        "config": {},
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    events = [
        {
            "event": "suite_complete",
            "cell_id": "postgres-d64-n5000",
            "tier": "unfiltered",
            "selectivity": 1.0,
            "ef": 40,
            "mode": "default",
            "p50_ms": 1.0,
            "p95_ms": 2.0,
            "mean_recall_at_10": 0.8,
            "underfill": 0,
            "underfill_percent": 0.0,
            "mean_result_count": 10.0,
            "plan": "Index Scan",
            "plan_uses_index": True,
            "label": "pre_churn",
        },
        {
            "event": "fts_suite_complete",
            "cell_id": "surrealdb-d64-n5000",
            "tier": "unfiltered",
            "selectivity": 1.0,
            "n_queries": 8,
            "p50_ms": 3.0,
            "p95_ms": 4.0,
            "mean_ndcg_at_10": 0.9,
            "underfill": 0,
            "underfill_percent": 0.0,
            "mean_result_count": 10.0,
            "plan_uses_text_index": True,
            "min_eligible_relevant_pool_size": 30,
            "mean_eligible_relevant_pool_size": 30.0,
            "max_eligible_relevant_pool_size": 30,
        },
        {
            "event": "cell_complete",
            "cell_id": "postgres-d64-n5000",
            "outcome": "ok",
        },
        {
            "event": "cell_complete",
            "cell_id": "surrealdb-d64-n5000",
            "outcome": "exceeded_memory_cap",
            "failure_phase": "load",
            "memory_cap_bytes": 4 * 1024**3,
        },
    ]
    (tmp_path / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )

    generate_report(tmp_path)

    memory_svg = (tmp_path / "charts" / "memory-vs-scale-d64.svg").read_text(
        encoding="utf-8"
    )
    recall_svg = (tmp_path / "charts" / "recall-vs-selectivity-d64.svg").read_text(
        encoding="utf-8"
    )
    assert "exceeded cap during load" in memory_svg
    assert "SurrealDB: no data — exceeded memory cap during load at this scale" in recall_svg
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "30/30.0/30" in summary
    assert "0.9000" in summary
