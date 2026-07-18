"""Benchmark phase orchestration and append-only result recording."""

from __future__ import annotations

import json
import platform
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence, cast

import numpy as np

from fvb.config import BenchmarkConfig
from fvb.data import DataArtifacts, generate_data, iter_rows, tenant_name
from fvb.engines.base import Engine, Row
from fvb.engines.postgres import PostgresEngine
from fvb.engines.surrealdb import SurrealDBEngine
from fvb.ground_truth import compute_ground_truth, load_truth, recall_at_k
from fvb.memsample import MemorySampler


class JsonlWriter:
    """Thread-safe append-only JSONL writer."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def write(self, event: str, **fields: Any) -> None:
        """Append one timestamped event and flush it to disk."""
        record = {"event": event, "unix_time": time.time(), **fields}
        with self.lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")


@dataclass
class CellContext:
    """Mutable labels and files associated with a running cell."""

    engine_name: str
    dimensions: int
    n_docs: int
    directory: Path
    phase: str = "prepare"

    @property
    def cell_id(self) -> str:
        return f"{self.engine_name}-d{self.dimensions}-n{self.n_docs}"


def _command_output(command: list[str]) -> str:
    try:
        return subprocess.run(command, text=True, capture_output=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return "unavailable\n"


def write_metadata(config: BenchmarkConfig, output: Path) -> None:
    """Capture normalized configuration, hash, and host evidence."""
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "started_at_unix": time.time(), "config": config.normalized(),
        "config_sha256": config.sha256(), "platform": platform.platform(),
        "python": platform.python_version(), "hostname": platform.node(),
    }
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8")
    (output / "lscpu.txt").write_text(_command_output(["lscpu"]), encoding="utf-8")
    meminfo = Path("/proc/meminfo")
    (output / "meminfo.txt").write_text(
        meminfo.read_text(encoding="utf-8") if meminfo.exists() else "unavailable\n", encoding="utf-8"
    )


class BenchmarkRunner:
    """Run a deterministic matrix serially and preserve every completed event."""

    def __init__(self, config: BenchmarkConfig, output: Path, engines: Sequence[str]) -> None:
        self.config = config
        self.output = output
        self.engine_names = engines
        self.events = JsonlWriter(output / "events.jsonl")
        self.queries = JsonlWriter(output / "queries.jsonl")
        self.plans = JsonlWriter(output / "plans.jsonl")
        repository = Path(__file__).resolve().parents[1]
        self.data_root = repository / "data"
        self.cache_root = repository / ".cache"
        self.engine_root = (self.cache_root / "runs" /
                            f"{output.name}-{config.sha256()[:12]}")

    def run(self) -> None:
        """Run all configured cells, continuing after cell-level failure."""
        write_metadata(self.config, self.output)
        for dimensions in self.config.dimensions:
            for n_docs in self.config.scales:
                artifacts = generate_data(self.config, dimensions, n_docs, self.data_root)
                truth = compute_ground_truth(artifacts, self.config.selectivities, self.config.k,
                                              self.config.ground_truth_batch_rows)
                for engine_name in self.engine_names:
                    context = CellContext(engine_name, dimensions, n_docs,
                                          self.output / "cells" / f"{engine_name}-d{dimensions}-n{n_docs}")
                    self._run_cell(context, artifacts, truth)
        self.events.write("run_complete")

    def _engine(self, context: CellContext) -> Engine:
        settings = self.config.engines[context.engine_name]
        workdir = self.engine_root / context.cell_id
        if context.engine_name == "surrealdb":
            return SurrealDBEngine(workdir, context.dimensions,
                                   self.config.client_timeout_seconds, self.config.memory_cap_bytes,
                                   settings, self.cache_root)
        return PostgresEngine(workdir, context.dimensions,
                              self.config.client_timeout_seconds, self.config.memory_cap_bytes, settings)

    def _oom_detected(self, engine: Engine) -> bool:
        container = getattr(engine, "container", None)
        settings = getattr(engine, "settings", None)
        if container and settings and settings.mode == "docker":
            result = subprocess.run(["docker", "inspect", "-f", "{{.State.OOMKilled}}", container],
                                    text=True, capture_output=True)
            return result.stdout.strip().lower() == "true"
        process = getattr(engine, "process", None)
        return bool(process and process.poll() in (-9, 137))

    def _run_cell(self, context: CellContext, artifacts: DataArtifacts, truth_path: Path) -> None:
        context.directory.mkdir(parents=True, exist_ok=True)
        engine = self._engine(context)
        sampler = MemorySampler(context.directory / "memory.csv", engine.process_roots,
                                lambda: context.phase)
        self.events.write("cell_start", cell_id=context.cell_id, engine=context.engine_name,
                          dimensions=context.dimensions, n_docs=context.n_docs,
                          memory_cap_bytes=self.config.memory_cap_bytes)
        try:
            engine.prepare()
            ready = engine.start()
            sampler.start()
            context.phase = "load:0"
            loaded = 0
            milestones = [max(1, round(context.n_docs * fraction))
                          for fraction in (0.25, 0.5, 0.75, 1.0)]
            milestone_index = 0

            def tracked_rows() -> Iterable[Sequence[Row]]:
                nonlocal loaded, milestone_index
                for batch in iter_rows(artifacts, self.config.batch_size):
                    yield batch
                    loaded += len(batch)
                    context.phase = f"load:{loaded}"
                    if milestone_index < len(milestones) and loaded >= milestones[milestone_index]:
                        sampler.sample_now()
                        milestone_index += 1

            load_stats = engine.load(tracked_rows())
            context.phase = "index_build"
            index_stats = engine.build_index()
            total_queryable = load_stats.seconds + index_stats.seconds
            self.events.write("load_complete", cell_id=context.cell_id,
                              ready_seconds=ready, load_seconds=load_stats.seconds,
                              rows=load_stats.rows, rows_per_second=(
                                  load_stats.rows / load_stats.seconds if load_stats.seconds else None),
                              index_seconds=index_stats.seconds,
                              time_to_queryable_seconds=total_queryable,
                              disk_bytes=engine.disk_bytes(), load_details=load_stats.details,
                              index_details=index_stats.details)
            self.events.write("engine_versions", cell_id=context.cell_id, versions=engine.version())

            context.phase = "settle"
            sampler.sample_now()
            settle_started = time.monotonic()
            while time.monotonic() - settle_started < self.config.settle_seconds:
                if not engine.alive():
                    raise RuntimeError("engine exited during settle")
                time.sleep(min(1.0, self.config.settle_seconds))
            self.events.write("settle_complete", cell_id=context.cell_id,
                              seconds=time.monotonic() - settle_started)
            sampler.sample_now()

            queries = np.load(artifacts.queries, mmap_mode="r")
            for repeat in (1, 2):
                context.phase = f"cold_{repeat}:stop"
                engine.stop()
                context.phase = f"cold_{repeat}:start"
                restart_ready = engine.start()
                context.phase = f"cold_{repeat}:first_query"
                sampler.sample_now()
                ids, query_seconds = engine.query(queries[0], None, self.config.k,
                                                  self.config.ef_values[0])
                sampler.sample_now()
                self.events.write("cold_open", cell_id=context.cell_id, repeat=repeat,
                                  ready_seconds=restart_ready, first_query_seconds=query_seconds,
                                  time_to_first_query_seconds=restart_ready + query_seconds,
                                  result_count=len(ids), source_ids=ids)

            self._suite(context, engine, artifacts, truth_path, "pre_churn", sampler)
            if self.config.churn.enabled:
                changes = self._churn(context, engine, artifacts, sampler)
                post_truth = self._post_churn_truth(artifacts, truth_path, changes)
                self._suite(context, engine, artifacts, post_truth, "post_churn", sampler)
            context.phase = "collect"
            self.events.write("cell_complete", cell_id=context.cell_id, outcome="ok",
                              disk_bytes=engine.disk_bytes())
        except Exception as error:
            outcome = "exceeded_memory_cap" if self._oom_detected(engine) else "error"
            self.events.write("cell_complete", cell_id=context.cell_id, outcome=outcome,
                              error=repr(error), traceback=traceback.format_exc(),
                              memory_cap_bytes=self.config.memory_cap_bytes)
        finally:
            sampler.stop()
            try:
                engine.stop()
            finally:
                cleanup = getattr(engine, "cleanup", None)
                if cleanup:
                    cleanup()

    def _suite(self, context: CellContext, engine: Engine, artifacts: DataArtifacts,
               truth_path: Path, label: str, sampler: MemorySampler) -> None:
        queries = np.load(artifacts.queries, mmap_mode="r")
        modes = self.config.postgres_modes if context.engine_name == "postgres" else ("default",)
        for selectivity in self.config.selectivities:
            exact = load_truth(truth_path, selectivity)
            tenant = tenant_name(selectivity)
            for ef in self.config.ef_values:
                for mode in modes:
                    suite_id = f"{context.cell_id}:{label}:s{selectivity}:ef{ef}:{mode}"
                    context.phase = f"{label}:s{selectivity}:ef{ef}:{mode}:explain"
                    plan = engine.explain(queries[0], tenant, self.config.k, ef, mode)
                    uses_index = engine.plan_uses_index(plan)
                    self.plans.write("plan", cell_id=context.cell_id, suite_id=suite_id,
                                     selectivity=selectivity, ef=ef, mode=mode, label=label,
                                     uses_vector_index=uses_index, plan=plan)
                    latencies: list[float] = []
                    recalls: list[float] = []
                    underfills = 0
                    context.phase = f"{label}:s{selectivity}:ef{ef}:{mode}:queries"
                    sampler.sample_now()
                    for query_index, vector in enumerate(queries):
                        ids, wall = engine.query(vector, tenant, self.config.k, ef, mode)
                        recall = recall_at_k(ids, exact[query_index], self.config.k)
                        underfill = len(ids) < self.config.k
                        latencies.append(wall)
                        recalls.append(recall)
                        underfills += int(underfill)
                        self.queries.write("query", cell_id=context.cell_id, suite_id=suite_id,
                                           label=label, selectivity=selectivity, ef=ef, mode=mode,
                                           query_index=query_index, latency_seconds=wall,
                                           recall_at_10=recall, result_count=len(ids),
                                           underfill=underfill, source_ids=ids)
                    sampler.sample_now()
                    self.events.write("suite_complete", cell_id=context.cell_id, suite_id=suite_id,
                                      label=label, selectivity=selectivity, ef=ef, mode=mode,
                                      n_queries=len(latencies), p50_seconds=float(np.percentile(latencies, 50)),
                                      p95_seconds=float(np.percentile(latencies, 95)),
                                      mean_recall_at_10=float(np.mean(recalls)),
                                      underfill_percent=100 * underfills / len(latencies),
                                      uses_vector_index=uses_index)

    def _churn(self, context: CellContext, engine: Engine,
               artifacts: DataArtifacts,
               sampler: MemorySampler) -> dict[int, tuple[str, np.ndarray] | None]:
        vectors = np.load(artifacts.vectors, mmap_mode="r")
        tenants = np.load(artifacts.tenants, mmap_mode="r")
        queries = np.load(artifacts.queries, mmap_mode="r")
        background = np.flatnonzero(tenants == "tenant_background")
        rng = np.random.default_rng(self.config.seed + 97)
        changes: dict[int, tuple[str, np.ndarray] | None] = {}
        changes_lock = threading.Lock()
        deadline = time.monotonic() + self.config.churn.seconds
        interval = 1 / self.config.churn.target_ops_per_second
        operation_count = 0
        context.phase = "churn"
        sampler.sample_now()
        mutation_error: list[BaseException] = []

        def mutate() -> None:
            nonlocal operation_count
            try:
                while time.monotonic() < deadline:
                    tick = time.monotonic()
                    operation_index = operation_count
                    operation = ("insert", "overwrite", "delete")[operation_index % 3]
                    if operation == "insert":
                        source_id = len(vectors) + operation_index
                        value = rng.normal(size=vectors.shape[1]).astype(np.float32)
                        value /= max(np.linalg.norm(value), np.finfo(np.float32).tiny)
                        engine.churn_once(operation, source_id, "tenant_background", value)
                        with changes_lock:
                            changes[source_id] = ("tenant_background", value)
                    else:
                        source_id = int(background[operation_index % len(background)])
                        if operation == "delete":
                            engine.churn_once(operation, source_id, "tenant_background", vectors[source_id])
                            with changes_lock:
                                changes[source_id] = None
                        else:
                            value = rng.normal(size=vectors.shape[1]).astype(np.float32)
                            value /= max(np.linalg.norm(value), np.finfo(np.float32).tiny)
                            engine.churn_once(operation, source_id, "tenant_background", value)
                            with changes_lock:
                                changes[source_id] = ("tenant_background", value)
                    operation_count += 1
                    delay = interval - (time.monotonic() - tick)
                    if delay > 0:
                        time.sleep(delay)
            except BaseException as error:
                mutation_error.append(error)

        worker = threading.Thread(target=mutate, name=f"{context.cell_id}-churn", daemon=True)
        worker.start()
        query_index = 0
        query_count = 0
        while time.monotonic() < deadline and not mutation_error:
            ids, wall = engine.query(queries[query_index], None, self.config.k,
                                     self.config.ef_values[0])
            self.queries.write("churn_query", cell_id=context.cell_id, label="churn",
                               query_index=query_index, latency_seconds=wall,
                               result_count=len(ids), underfill=len(ids) < self.config.k,
                               source_ids=ids)
            query_count += 1
            query_index = (query_index + 1) % len(queries)
        worker.join(timeout=self.config.client_timeout_seconds + 1)
        sampler.sample_now()
        if mutation_error:
            raise RuntimeError("churn mutation worker failed") from mutation_error[0]
        self.events.write("churn_complete", cell_id=context.cell_id, operations=operation_count,
                          queries=query_count,
                          seconds=self.config.churn.seconds,
                          achieved_ops_per_second=operation_count / self.config.churn.seconds)
        return changes

    def _post_churn_truth(self, artifacts: DataArtifacts, pre_truth: Path,
                          changes: dict[int, tuple[str, np.ndarray] | None]) -> Path:
        # Filtered tenants are deliberately untouched. Recompute unfiltered exact truth while
        # reusing pre-churn filtered truth; this keeps optional churn exact without copying corpus.
        output = artifacts.directory / f"ground-truth-post-churn-k{self.config.k}.npz"
        vectors = np.load(artifacts.vectors, mmap_mode="r")
        queries = np.load(artifacts.queries, mmap_mode="r")
        deleted = {source_id for source_id, value in changes.items() if value is None}
        changed_existing = {source_id: value[1] for source_id, value in changes.items()
                            if value is not None and source_id < len(vectors)}
        inserted = {source_id: value[1] for source_id, value in changes.items()
                    if value is not None and source_id >= len(vectors)}
        best_scores = np.full((len(queries), self.config.k), -np.inf, dtype=np.float32)
        best_ids = np.full((len(queries), self.config.k), -1, dtype=np.int64)
        for begin in range(0, len(vectors), self.config.ground_truth_batch_rows):
            end = min(len(vectors), begin + self.config.ground_truth_batch_rows)
            ids = np.arange(begin, end, dtype=np.int64)
            keep = np.array([int(item) not in deleted and int(item) not in changed_existing for item in ids])
            ids = ids[keep]
            if not len(ids):
                continue
            scores = np.asarray(queries) @ np.asarray(vectors[ids]).T
            best_scores, best_ids = self._merge_exact(best_scores, best_ids, scores, ids)
        overlay = {**changed_existing, **inserted}
        if overlay:
            ids = np.fromiter(overlay, dtype=np.int64)
            matrix = np.stack([overlay[int(item)] for item in ids])
            best_scores, best_ids = self._merge_exact(best_scores, best_ids,
                                                      np.asarray(queries) @ matrix.T, ids)
        ordering = np.argsort(best_scores, axis=1)[:, ::-1]
        payload = {f"s_{selectivity:.8g}": load_truth(pre_truth, selectivity)
                   for selectivity in self.config.selectivities if selectivity != 1.0}
        payload["s_1"] = np.take_along_axis(best_ids, ordering, axis=1)
        np.savez_compressed(output, **cast(dict[str, Any], payload))
        return output

    def _merge_exact(self, best_scores: np.ndarray, best_ids: np.ndarray,
                     scores: np.ndarray, ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        candidate_scores = np.concatenate((best_scores, scores), axis=1)
        candidate_ids = np.concatenate((best_ids, np.broadcast_to(ids, scores.shape)), axis=1)
        take = np.argpartition(candidate_scores, -self.config.k, axis=1)[:, -self.config.k:]
        return (np.take_along_axis(candidate_scores, take, axis=1),
                np.take_along_axis(candidate_ids, take, axis=1))


def run_benchmark(config: BenchmarkConfig, output: Path, engines: Sequence[str]) -> None:
    """Public entry point for CLI and tests."""
    BenchmarkRunner(config, output, engines).run()
