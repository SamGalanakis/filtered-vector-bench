"""Benchmark phase orchestration and append-only result recording."""

from __future__ import annotations

import json
import platform
import subprocess
import threading
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence, cast

import numpy as np

from fvb.config import BenchmarkConfig, EngineConfig
from fvb.data import (
    DataArtifacts,
    generate_data,
    iter_rows,
    tenant_name,
    text_queries_for_tier,
)
from fvb.engines.base import Engine, Row
from fvb.engines.postgres import PostgresEngine
from fvb.engines.surrealdb import SurrealDBEngine
from fvb.ground_truth import compute_ground_truth, load_truth, ndcg_at_k, recall_at_k
from fvb.memsample import MemorySampler, process_tree_memory_bytes


QUIESCENCE_CADENCE_SECONDS = 10.0
QUIESCENCE_STABLE_SAMPLES = 12
QUIESCENCE_RELATIVE_THRESHOLD = 0.01
QUIESCENCE_CAP_SECONDS = 45 * 60.0


@dataclass(frozen=True)
class QuiescenceResult:
    """Outcome of evaluating or observing a quiescence sample stream."""

    quiescent: bool
    cap_hit: bool
    sample_count: int
    stable_samples: int


class QuiescenceDetector:
    """Detect consecutive low-change RSS and disk observations."""

    def __init__(self, stable_samples: int = QUIESCENCE_STABLE_SAMPLES,
                 relative_threshold: float = QUIESCENCE_RELATIVE_THRESHOLD) -> None:
        self.required = stable_samples
        self.threshold = relative_threshold
        self.previous: tuple[int, int] | None = None
        self.sample_count = 0
        self.stable_samples = 0

    @staticmethod
    def _relative_change(previous: int, current: int) -> float:
        return abs(current - previous) / max(abs(previous), 1)

    def observe(self, rss_bytes: int, disk_bytes: int) -> bool:
        """Add one observation and return whether the stream is now quiescent."""
        current = (rss_bytes, disk_bytes)
        self.sample_count += 1
        if self.previous is not None:
            stable = all(
                self._relative_change(old, new) < self.threshold
                for old, new in zip(self.previous, current)
            )
            self.stable_samples = self.stable_samples + 1 if stable else 0
        self.previous = current
        return self.stable_samples >= self.required


def detect_quiescence(samples: Iterable[tuple[int, int]], *, stable_samples: int = 12,
                      relative_threshold: float = 0.01,
                      max_samples: int | None = None) -> QuiescenceResult:
    """Evaluate synthetic observations with an optional sample-count cap."""
    detector = QuiescenceDetector(stable_samples, relative_threshold)
    for rss_bytes, disk_bytes in samples:
        if max_samples is not None and detector.sample_count >= max_samples:
            break
        if detector.observe(rss_bytes, disk_bytes):
            return QuiescenceResult(True, False, detector.sample_count, detector.stable_samples)
    cap_hit = max_samples is not None and detector.sample_count >= max_samples
    return QuiescenceResult(False, cap_hit, detector.sample_count, detector.stable_samples)


class JsonlWriter:
    """Thread-safe append-only JSONL writer."""

    def __init__(self, path: Path, **default_fields: Any) -> None:
        self.path = path
        self.default_fields = default_fields
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def write(self, event: str, **fields: Any) -> None:
        """Append one timestamped event and flush it to disk."""
        record = {"event": event, "unix_time": time.time(), **self.default_fields, **fields}
        with self.lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")


@dataclass
class CellContext:
    """Mutable labels and files associated with a running cell."""

    engine_name: str
    dimensions: int
    n_docs: int
    directory: Path
    settings: EngineConfig | None = None
    variant_label: str | None = None
    phase: str = "prepare"

    @property
    def cell_id(self) -> str:
        prefix = self.engine_name
        if self.variant_label:
            prefix += f"-{self.variant_label}"
        return f"{prefix}-d{self.dimensions}-n{self.n_docs}"


def _failure_phase(phase: str) -> str:
    """Collapse detailed sampler phases into stable failure-phase labels."""
    if phase.startswith("load"):
        return "load"
    if phase.startswith("index_build"):
        return "index_build"
    if phase.startswith(("pre_churn", "post_churn")):
        return "filtered_suite"
    if phase.startswith("churn"):
        return "churn"
    if phase.startswith("cold_"):
        return "cold_open"
    if phase.startswith("steady_cold_open"):
        return "steady_cold_open"
    if phase.startswith("warmup:"):
        parts = phase.split(":", 2)
        return f"{parts[1]}_warmup"
    return phase.split(":", 1)[0]


def _classify_failure(*, oom_detected: bool, engine_alive: bool, peak_rss_bytes: int,
                      memory_cap_bytes: int) -> str:
    """Classify explicit OOMs and any near-cap request failure as cap exceedance."""
    near_cap = abs(peak_rss_bytes - memory_cap_bytes) <= int(memory_cap_bytes * 0.05)
    return "exceeded_memory_cap" if oom_detected or near_cap else "error"


def _command_output(command: list[str]) -> str:
    try:
        return subprocess.run(command, text=True, capture_output=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return "unavailable\n"


def _available_memory_bytes() -> int:
    """Read Linux MemAvailable for the run-start cap safety check."""
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def safe_memory_cap(requested_bytes: int, available_bytes: int) -> int:
    """Limit a requested cap to the largest whole GiB no greater than half available."""
    if not available_bytes or requested_bytes <= available_bytes // 2:
        return requested_bytes
    gib = 1024**3
    return max(gib, (available_bytes // 2 // gib) * gib)


def write_metadata(config: BenchmarkConfig, output: Path, *, available_memory_bytes: int,
                   effective_memory_cap_bytes: int) -> None:
    """Capture normalized configuration, hash, and host evidence."""
    output.mkdir(parents=True, exist_ok=True)
    metadata = {
        "started_at_unix": time.time(), "config": config.normalized(),
        "config_sha256": config.sha256(), "platform": platform.platform(),
        "python": platform.python_version(), "hostname": platform.node(),
        "memory_preflight": {
            "available_memory_bytes": available_memory_bytes,
            "requested_memory_cap_bytes": config.memory_cap_bytes,
            "effective_memory_cap_bytes": effective_memory_cap_bytes,
            "half_available_rule_applied": effective_memory_cap_bytes < config.memory_cap_bytes,
        },
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
        missing_engines = set(engines) - set(config.engines)
        if missing_engines:
            raise ValueError(f"requested engines are not configured: {sorted(missing_engines)}")
        self.available_memory_bytes = _available_memory_bytes()
        self.memory_cap_bytes = safe_memory_cap(
            config.memory_cap_bytes, self.available_memory_bytes
        )
        state = {"measurement_state": config.measurement_state}
        self.events = JsonlWriter(output / "events.jsonl", **state)
        self.queries = JsonlWriter(output / "queries.jsonl", **state)
        self.plans = JsonlWriter(output / "plans.jsonl", **state)
        repository = Path(__file__).resolve().parents[1]
        self.data_root = repository / "data"
        self.cache_root = repository / ".cache"
        self.engine_root = (self.cache_root / "runs" /
                            f"{output.name}-{config.sha256()[:12]}")

    def run(self) -> None:
        """Run all configured cells, continuing after cell-level failure."""
        write_metadata(
            self.config, self.output, available_memory_bytes=self.available_memory_bytes,
            effective_memory_cap_bytes=self.memory_cap_bytes,
        )
        for dimensions in self.config.dimensions:
            for n_docs in self.config.scales:
                artifacts = generate_data(self.config, dimensions, n_docs, self.data_root)
                truth = (
                    compute_ground_truth(
                        artifacts, self.config.selectivities, self.config.k,
                        self.config.ground_truth_batch_rows,
                    )
                    if self.config.suites.vector else None
                )
                for engine_name in self.engine_names:
                    settings_variants = self.config.engines[engine_name]
                    explicit_variants = len(settings_variants) > 1
                    for settings in settings_variants:
                        variant_label = None
                        if engine_name == "surrealdb" and explicit_variants:
                            variant_label = f"{settings.storage}-{settings.transport}"
                        context = CellContext(
                            engine_name, dimensions, n_docs, self.output / "cells",
                            settings=settings, variant_label=variant_label,
                        )
                        context.directory = self.output / "cells" / context.cell_id
                        self._run_cell(context, artifacts, truth)
        self.events.write("run_complete")

    def _engine(self, context: CellContext) -> Engine:
        if context.settings is None:
            settings = self.config.engines[context.engine_name][0]
        else:
            settings = context.settings
        workdir = self.engine_root / context.cell_id
        if context.engine_name == "surrealdb":
            return SurrealDBEngine(workdir, context.dimensions,
                                   self.config.client_timeout_seconds, self.memory_cap_bytes,
                                   settings, self.cache_root, self.config.text)
        return PostgresEngine(workdir, context.dimensions,
                              self.config.client_timeout_seconds, self.memory_cap_bytes,
                              settings, self.config.text)

    def _oom_detected(self, engine: Engine) -> bool:
        container = getattr(engine, "container", None)
        if container and getattr(engine, "surreal_in_docker", False):
            result = subprocess.run(["docker", "inspect", "-f", "{{.State.OOMKilled}}", container],
                                    text=True, capture_output=True)
            return result.stdout.strip().lower() == "true"
        process = getattr(engine, "process", None)
        return bool(process and process.poll() in (-9, 137))

    def _run_cell(
        self, context: CellContext, artifacts: DataArtifacts, truth_path: Path | None
    ) -> None:
        context.directory.mkdir(parents=True, exist_ok=True)
        engine = self._engine(context)
        sampler = MemorySampler(
            context.directory / "memory.csv", engine.process_roots, lambda: context.phase,
            groups=engine.memory_process_groups,
        )
        settings = context.settings
        self.events.write("cell_start", cell_id=context.cell_id, engine=context.engine_name,
                          dimensions=context.dimensions, n_docs=context.n_docs,
                          storage=settings.storage if settings else None,
                          storage_setup=getattr(engine, "tikv_setup", None)
                          if settings and settings.storage == "tikv" else None,
                          transport=settings.transport if settings else None,
                          requested_memory_cap_bytes=self.config.memory_cap_bytes,
                          available_memory_bytes=self.available_memory_bytes,
                          memory_cap_bytes=self.memory_cap_bytes,
                          memory_limits={
                              "surrealdb_process_tree_bytes": self.memory_cap_bytes
                              if context.engine_name == "surrealdb" else None,
                              "tikv_pd_process_tree_bytes": None,
                              "tikv_pd_limit_policy": "uncapped; measured separately",
                          },
                          suites=asdict(self.config.suites),
                          query_topics=self.config.query_topics)
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
            sampler.sample_now()
            load_peak_rss, load_peak_pss = sampler.peak_bytes("load")
            load_surreal_rss, load_surreal_pss = sampler.peak_group_bytes("surrealdb", "load")
            load_storage_rss, load_storage_pss = sampler.peak_group_bytes("tikv_pd", "load")
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
                              index_details=index_stats.details,
                              load_peak_rss_bytes=load_peak_rss,
                              load_peak_pss_bytes=load_peak_pss,
                              load_surrealdb_peak_rss_bytes=load_surreal_rss,
                              load_surrealdb_peak_pss_bytes=load_surreal_pss,
                              load_tikv_pd_peak_rss_bytes=load_storage_rss,
                              load_tikv_pd_peak_pss_bytes=load_storage_pss,
                              peak_rss_bytes=load_peak_rss,
                              peak_pss_bytes=load_peak_pss)
            self.events.write("engine_versions", cell_id=context.cell_id, versions=engine.version())

            if self.config.measurement_state == "steady":
                self._steady_protocol(context, engine, artifacts, sampler)
            else:
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

            if self.config.suites.vector:
                assert truth_path is not None
                queries = np.load(artifacts.queries, mmap_mode="r")
                if self.config.measurement_state == "fresh":
                    for repeat in (1, 2):
                        context.phase = f"cold_{repeat}:stop"
                        engine.stop()
                        context.phase = f"cold_{repeat}:start"
                        restart_ready = engine.start()
                        context.phase = f"cold_{repeat}:first_query"
                        sampler.sample_now()
                        ids, query_seconds = engine.query(
                            queries[0], None, self.config.k, self.config.ef_values[0]
                        )
                        sampler.sample_now()
                        self.events.write(
                            "cold_open", cell_id=context.cell_id, repeat=repeat, label="normal",
                            ready_seconds=restart_ready, first_query_seconds=query_seconds,
                            time_to_first_query_seconds=restart_ready + query_seconds,
                            result_count=len(ids), source_ids=ids, query_kind="vector",
                        )
                self._suite(context, engine, artifacts, truth_path, "pre_churn", sampler)
            if self.config.text.enabled and self.config.suites.fts:
                self._text_suite(context, engine, artifacts, sampler)
            if self.config.text.enabled and self.config.suites.hybrid:
                self._hybrid_suite(context, engine, artifacts, sampler)
            if self.config.churn.enabled:
                changes = self._churn(context, engine, artifacts, sampler)
                if self.config.suites.vector:
                    assert truth_path is not None
                    post_truth = self._post_churn_truth(artifacts, truth_path, changes)
                    self._suite(context, engine, artifacts, post_truth, "post_churn", sampler)
            context.phase = "collect"
            sampler.sample_now()
            peak_rss, peak_pss = sampler.peak_bytes()
            surreal_rss, surreal_pss = sampler.peak_group_bytes("surrealdb")
            storage_rss, storage_pss = sampler.peak_group_bytes("tikv_pd")
            self.events.write("cell_complete", cell_id=context.cell_id, outcome="ok",
                              disk_bytes=engine.disk_bytes(), suites=asdict(self.config.suites),
                              query_topics=self.config.query_topics,
                              peak_rss_bytes=peak_rss, peak_pss_bytes=peak_pss,
                              surrealdb_peak_rss_bytes=surreal_rss,
                              surrealdb_peak_pss_bytes=surreal_pss,
                              tikv_pd_peak_rss_bytes=storage_rss,
                              tikv_pd_peak_pss_bytes=storage_pss)
        except Exception as error:
            sampler.sample_now()
            peak_rss, peak_pss = sampler.peak_bytes()
            surreal_rss, surreal_pss = sampler.peak_group_bytes("surrealdb")
            storage_rss, storage_pss = sampler.peak_group_bytes("tikv_pd")
            cap_peak_rss = surreal_rss if context.engine_name == "surrealdb" else peak_rss
            outcome = _classify_failure(
                oom_detected=self._oom_detected(engine), engine_alive=engine.alive(),
                peak_rss_bytes=cap_peak_rss, memory_cap_bytes=self.memory_cap_bytes,
            )
            failure_phase = _failure_phase(context.phase)
            self.events.write("cell_complete", cell_id=context.cell_id, outcome=outcome,
                              error=repr(error), traceback=traceback.format_exc(),
                              memory_cap_bytes=self.memory_cap_bytes,
                              phase=failure_phase, failure_phase=failure_phase,
                              peak_rss_bytes=peak_rss, peak_pss_bytes=peak_pss,
                              surrealdb_peak_rss_bytes=surreal_rss,
                              surrealdb_peak_pss_bytes=surreal_pss,
                              tikv_pd_peak_rss_bytes=storage_rss,
                              tikv_pd_peak_pss_bytes=storage_pss,
                              suites=asdict(self.config.suites),
                              query_topics=self.config.query_topics)
        finally:
            sampler.stop()
            try:
                engine.stop()
            finally:
                cleanup = getattr(engine, "cleanup", None)
                if cleanup:
                    cleanup()

    def _steady_protocol(self, context: CellContext, engine: Engine,
                         artifacts: DataArtifacts, sampler: MemorySampler) -> None:
        """Wait for stability, cold-restart, and discard one complete warm-up pass."""
        started = time.monotonic()
        deadline = started + QUIESCENCE_CAP_SECONDS
        detector = QuiescenceDetector()
        quiescent = False
        context.phase = "quiescence"
        while True:
            if not engine.alive():
                raise RuntimeError("engine exited during quiescence wait")
            rss_bytes, pss_bytes, pids = process_tree_memory_bytes(engine.process_roots())
            disk_bytes = engine.disk_bytes()
            quiescent = detector.observe(rss_bytes, disk_bytes)
            elapsed = time.monotonic() - started
            self.events.write(
                "quiescence_sample", cell_id=context.cell_id,
                sample=detector.sample_count, elapsed_seconds=elapsed,
                stable_samples=detector.stable_samples, rss_bytes=rss_bytes,
                pss_bytes=pss_bytes, disk_bytes=disk_bytes, pids=sorted(pids),
            )
            sampler.sample_now()
            if quiescent or time.monotonic() >= deadline:
                break
            time.sleep(min(QUIESCENCE_CADENCE_SECONDS, deadline - time.monotonic()))

        analyze_seconds: float | None = None
        autovacuum_wait_seconds: float | None = None
        autovacuum_active = False
        if context.engine_name == "postgres":
            context.phase = "quiescence:analyze"
            analyze_started = time.monotonic()
            engine.analyze()
            analyze_seconds = time.monotonic() - analyze_started
            autovacuum_started = time.monotonic()
            while True:
                autovacuum_active = engine.background_maintenance_active()
                self.events.write(
                    "autovacuum_sample", cell_id=context.cell_id,
                    elapsed_seconds=time.monotonic() - started, active=autovacuum_active,
                )
                if not autovacuum_active or time.monotonic() >= deadline:
                    break
                time.sleep(min(QUIESCENCE_CADENCE_SECONDS, deadline - time.monotonic()))
            autovacuum_wait_seconds = time.monotonic() - autovacuum_started

        cap_hit = not quiescent or (autovacuum_active and time.monotonic() >= deadline)
        self.events.write(
            "quiescence_complete", cell_id=context.cell_id,
            seconds=time.monotonic() - started, quiescent=quiescent, cap_hit=cap_hit,
            samples=detector.sample_count, stable_samples=detector.stable_samples,
            analyze_seconds=analyze_seconds,
            autovacuum_wait_seconds=autovacuum_wait_seconds,
            autovacuum_active_at_end=autovacuum_active,
            cadence_seconds=QUIESCENCE_CADENCE_SECONDS,
            required_stable_samples=QUIESCENCE_STABLE_SAMPLES,
            relative_threshold=QUIESCENCE_RELATIVE_THRESHOLD,
            cap_seconds=QUIESCENCE_CAP_SECONDS,
        )

        context.phase = "steady_cold_open:stop"
        engine.stop()
        context.phase = "steady_cold_open:start"
        restart_ready = engine.start()
        context.phase = "steady_cold_open:first_query"
        sampler.sample_now()
        ids, query_seconds, query_kind = self._first_query(engine, artifacts)
        sampler.sample_now()
        self.events.write(
            "cold_open", cell_id=context.cell_id, label="steady_protocol", repeat=1,
            ready_seconds=restart_ready, first_query_seconds=query_seconds,
            time_to_first_query_seconds=restart_ready + query_seconds,
            result_count=len(ids), source_ids=ids, query_kind=query_kind,
        )
        self._warmup(context, engine, artifacts, sampler)

    def _first_query(self, engine: Engine,
                     artifacts: DataArtifacts) -> tuple[list[int], float, str]:
        """Run the first enabled suite's first query for the steady cold-open sample."""
        if self.config.suites.vector:
            vectors = np.load(artifacts.queries, mmap_mode="r")
            ids, seconds = engine.query(
                vectors[0], None, self.config.k, self.config.ef_values[0]
            )
            return ids, seconds, "vector"
        query_texts, vectors, _ = text_queries_for_tier(
            artifacts, self.config.selectivities, 1.0
        )
        text_query = bytes(query_texts[0]).decode("ascii")
        if self.config.suites.fts:
            ids, seconds = engine.text_query(text_query, None, self.config.k)
            return ids, seconds, "fts"
        ids, seconds = engine.hybrid_query(
            vectors[0], text_query, None, self.config.k, self.config.ef_values[0],
            self.config.text.fts_candidates, self.config.text.rrf_k,
        )
        return ids, seconds, "hybrid"

    def _warmup(self, context: CellContext, engine: Engine,
                artifacts: DataArtifacts, sampler: MemorySampler) -> None:
        """Run every selected query set once without writing query or summary observations."""
        self.events.write("warmup_start", cell_id=context.cell_id, label="warmup",
                          suites=asdict(self.config.suites))
        modes = self.config.postgres_modes if context.engine_name == "postgres" else ("default",)
        if self.config.suites.vector:
            vectors = np.load(artifacts.queries, mmap_mode="r")
            for selectivity in self.config.selectivities:
                tenant = tenant_name(selectivity)
                for ef in self.config.ef_values:
                    for mode in modes:
                        context.phase = f"warmup:vector:s{selectivity}:ef{ef}:{mode}"
                        for vector in vectors:
                            engine.query(vector, tenant, self.config.k, ef, mode)
                        self.events.write(
                            "warmup_suite_complete", cell_id=context.cell_id, label="warmup",
                            suite="vector", selectivity=selectivity, ef=ef, mode=mode,
                            n_queries=len(vectors),
                        )
        if self.config.text.enabled and self.config.suites.fts:
            for selectivity in self.config.selectivities:
                query_texts, _, _ = text_queries_for_tier(
                    artifacts, self.config.selectivities, selectivity
                )
                tenant = tenant_name(selectivity)
                context.phase = f"warmup:fts:s{selectivity}"
                for encoded_query in query_texts:
                    engine.text_query(bytes(encoded_query).decode("ascii"), tenant, self.config.k)
                self.events.write(
                    "warmup_suite_complete", cell_id=context.cell_id, label="warmup",
                    suite="fts", selectivity=selectivity, n_queries=len(query_texts),
                )
        if self.config.text.enabled and self.config.suites.hybrid:
            for selectivity in self.config.selectivities:
                query_texts, vectors, _ = text_queries_for_tier(
                    artifacts, self.config.selectivities, selectivity
                )
                tenant = tenant_name(selectivity)
                for ef in self.config.ef_values:
                    context.phase = f"warmup:hybrid:s{selectivity}:ef{ef}"
                    for query_index, vector in enumerate(vectors):
                        engine.hybrid_query(
                            vector, bytes(query_texts[query_index]).decode("ascii"), tenant,
                            self.config.k, ef, self.config.text.fts_candidates,
                            self.config.text.rrf_k,
                        )
                    self.events.write(
                        "warmup_suite_complete", cell_id=context.cell_id, label="warmup",
                        suite="hybrid", selectivity=selectivity, ef=ef,
                        n_queries=len(vectors),
                    )
        sampler.sample_now()
        self.events.write("warmup_complete", cell_id=context.cell_id, label="warmup")

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
                    result_counts: list[int] = []
                    for query_index, vector in enumerate(queries):
                        ids, wall = engine.query(vector, tenant, self.config.k, ef, mode)
                        recall = recall_at_k(ids, exact[query_index], self.config.k)
                        underfill = len(ids) < self.config.k
                        latencies.append(wall)
                        recalls.append(recall)
                        underfills += int(underfill)
                        result_counts.append(len(ids))
                        self.queries.write("query", cell_id=context.cell_id, suite_id=suite_id,
                                           label=label, selectivity=selectivity, ef=ef, mode=mode,
                                           query_index=query_index, latency_seconds=wall,
                                           recall_at_10=recall, result_count=len(ids),
                                           underfill=underfill, source_ids=ids)
                    sampler.sample_now()
                    self.events.write("suite_complete", cell_id=context.cell_id, suite_id=suite_id,
                                      label=label, tier=tenant or "unfiltered",
                                      selectivity=selectivity, ef=ef, mode=mode,
                                      n_queries=len(latencies),
                                      p50_ms=1000 * float(np.percentile(latencies, 50)),
                                      p95_ms=1000 * float(np.percentile(latencies, 95)),
                                      mean_recall_at_10=float(np.mean(recalls)),
                                      underfill=underfills,
                                      underfill_percent=100 * underfills / len(latencies),
                                      mean_result_count=float(np.mean(result_counts)),
                                      plan=plan, plan_uses_index=uses_index)

    def _text_relevance(self, clusters: np.ndarray, eligible: np.ndarray,
                        relevant_count: int, query_cluster: int,
                        ids: list[int]) -> tuple[list[float], list[float]]:
        """Return observed and ideal same-cluster relevance for one filtered result list."""
        observed = [
            1.0 if 0 <= source_id < len(clusters) and eligible[source_id]
            and int(clusters[source_id]) == query_cluster else 0.0
            for source_id in ids
        ]
        return observed, [1.0] * min(self.config.k, relevant_count)

    def _text_suite(self, context: CellContext, engine: Engine, artifacts: DataArtifacts,
                    sampler: MemorySampler) -> None:
        """Run text-only filtered queries once per selectivity tier."""
        assert artifacts.query_texts is not None
        assert artifacts.document_clusters is not None
        document_clusters = np.load(artifacts.document_clusters, mmap_mode="r")
        tenants = np.load(artifacts.tenants, mmap_mode="r")
        for selectivity in self.config.selectivities:
            query_texts, _, query_clusters = text_queries_for_tier(
                artifacts, self.config.selectivities, selectivity
            )
            tenant = tenant_name(selectivity)
            eligible = (np.ones(len(document_clusters), dtype=np.bool_) if tenant is None else
                        np.asarray(tenants == tenant, dtype=np.bool_))
            relevant_counts = np.bincount(
                np.asarray(document_clusters[eligible], dtype=np.int64),
                minlength=self.config.clusters,
            )
            relevant_pool_sizes = [int(relevant_counts[int(cluster)]) for cluster in query_clusters]
            suite_id = f"{context.cell_id}:fts_suite:s{selectivity}"
            first_query = bytes(query_texts[0]).decode("ascii")
            context.phase = f"fts_suite:s{selectivity}:explain"
            plan = engine.text_explain(first_query, tenant, self.config.k)
            uses_index = engine.plan_uses_text_index(plan)
            self.plans.write(
                "fts_plan", cell_id=context.cell_id, suite_id=suite_id,
                selectivity=selectivity, uses_text_index=uses_index, plan=plan,
            )
            latencies: list[float] = []
            ndcgs: list[float] = []
            result_counts: list[int] = []
            underfills = 0
            context.phase = f"fts_suite:s{selectivity}:queries"
            sampler.sample_now()
            for query_index, encoded_query in enumerate(query_texts):
                text_query = bytes(encoded_query).decode("ascii")
                ids, wall = engine.text_query(text_query, tenant, self.config.k)
                query_cluster = int(query_clusters[query_index])
                observed, ideal = self._text_relevance(
                    document_clusters, eligible, int(relevant_counts[query_cluster]),
                    query_cluster, ids,
                )
                ndcg = ndcg_at_k(observed, ideal, self.config.k)
                underfill = len(ids) < self.config.k
                latencies.append(wall)
                ndcgs.append(ndcg)
                result_counts.append(len(ids))
                underfills += int(underfill)
                self.queries.write(
                    "fts_query", cell_id=context.cell_id, suite_id=suite_id,
                    selectivity=selectivity, query_index=query_index,
                    text_query=text_query, latency_seconds=wall, ndcg_at_10=ndcg,
                    result_count=len(ids), underfill=underfill, source_ids=ids,
                    eligible_relevant_pool_size=relevant_pool_sizes[query_index],
                )
            sampler.sample_now()
            self.events.write(
                "fts_suite_complete", cell_id=context.cell_id, suite_id=suite_id,
                tier=tenant or "unfiltered", selectivity=selectivity,
                n_queries=len(latencies), p50_ms=1000 * float(np.percentile(latencies, 50)),
                p95_ms=1000 * float(np.percentile(latencies, 95)),
                mean_ndcg_at_10=float(np.mean(ndcgs)), underfill=underfills,
                underfill_percent=100 * underfills / len(latencies),
                mean_result_count=float(np.mean(result_counts)), plan=plan,
                plan_uses_text_index=uses_index,
                eligible_relevant_pool_sizes=relevant_pool_sizes,
                min_eligible_relevant_pool_size=min(relevant_pool_sizes),
                mean_eligible_relevant_pool_size=float(np.mean(relevant_pool_sizes)),
                max_eligible_relevant_pool_size=max(relevant_pool_sizes),
                surrealdb_score_zero_issue=bool(
                    getattr(engine, "text_score_zero_detected", False)
                ),
            )

    def _hybrid_suite(self, context: CellContext, engine: Engine, artifacts: DataArtifacts,
                      sampler: MemorySampler) -> None:
        """Run one-statement vector + text RRF queries per selectivity and EF value."""
        assert artifacts.query_texts is not None
        assert artifacts.document_clusters is not None
        document_clusters = np.load(artifacts.document_clusters, mmap_mode="r")
        tenants = np.load(artifacts.tenants, mmap_mode="r")
        for selectivity in self.config.selectivities:
            query_texts, vectors, query_clusters = text_queries_for_tier(
                artifacts, self.config.selectivities, selectivity
            )
            tenant = tenant_name(selectivity)
            eligible = (np.ones(len(document_clusters), dtype=np.bool_) if tenant is None else
                        np.asarray(tenants == tenant, dtype=np.bool_))
            relevant_counts = np.bincount(
                np.asarray(document_clusters[eligible], dtype=np.int64),
                minlength=self.config.clusters,
            )
            relevant_pool_sizes = [int(relevant_counts[int(cluster)]) for cluster in query_clusters]
            for ef in self.config.ef_values:
                suite_id = f"{context.cell_id}:hybrid_suite:s{selectivity}:ef{ef}"
                first_query = bytes(query_texts[0]).decode("ascii")
                context.phase = f"hybrid_suite:s{selectivity}:ef{ef}:explain"
                plan = engine.hybrid_explain(
                    vectors[0], first_query, tenant, self.config.k, ef,
                    self.config.text.fts_candidates, self.config.text.rrf_k,
                )
                uses_vector, uses_text = engine.hybrid_plan_uses_indexes(plan)
                self.plans.write(
                    "hybrid_plan", cell_id=context.cell_id, suite_id=suite_id,
                    selectivity=selectivity, ef=ef, uses_vector_index=uses_vector,
                    uses_text_index=uses_text, uses_both_indexes=uses_vector and uses_text,
                    plan=plan,
                )
                latencies: list[float] = []
                ndcgs: list[float] = []
                result_counts: list[int] = []
                underfills = 0
                context.phase = f"hybrid_suite:s{selectivity}:ef{ef}:queries"
                sampler.sample_now()
                for query_index, vector in enumerate(vectors):
                    text_query = bytes(query_texts[query_index]).decode("ascii")
                    ids, wall = engine.hybrid_query(
                        vector, text_query, tenant, self.config.k, ef,
                        self.config.text.fts_candidates, self.config.text.rrf_k,
                    )
                    query_cluster = int(query_clusters[query_index])
                    observed, ideal = self._text_relevance(
                        document_clusters, eligible, int(relevant_counts[query_cluster]),
                        query_cluster, ids,
                    )
                    ndcg = ndcg_at_k(observed, ideal, self.config.k)
                    underfill = len(ids) < self.config.k
                    latencies.append(wall)
                    ndcgs.append(ndcg)
                    result_counts.append(len(ids))
                    underfills += int(underfill)
                    self.queries.write(
                        "hybrid_query", cell_id=context.cell_id, suite_id=suite_id,
                        selectivity=selectivity, ef=ef, query_index=query_index,
                        text_query=text_query, latency_seconds=wall, ndcg_at_10=ndcg,
                        result_count=len(ids), underfill=underfill, source_ids=ids,
                        eligible_relevant_pool_size=relevant_pool_sizes[query_index],
                    )
                sampler.sample_now()
                self.events.write(
                    "hybrid_suite_complete", cell_id=context.cell_id, suite_id=suite_id,
                    tier=tenant or "unfiltered", selectivity=selectivity, ef=ef,
                    candidates=self.config.text.fts_candidates, rrf_k=self.config.text.rrf_k,
                    n_queries=len(latencies),
                    p50_ms=1000 * float(np.percentile(latencies, 50)),
                    p95_ms=1000 * float(np.percentile(latencies, 95)),
                    mean_ndcg_at_10=float(np.mean(ndcgs)), underfill=underfills,
                    underfill_percent=100 * underfills / len(latencies),
                    mean_result_count=float(np.mean(result_counts)), plan=plan,
                    plan_uses_vector_index=uses_vector, plan_uses_text_index=uses_text,
                    plan_uses_both_indexes=uses_vector and uses_text,
                    eligible_relevant_pool_sizes=relevant_pool_sizes,
                    min_eligible_relevant_pool_size=min(relevant_pool_sizes),
                    mean_eligible_relevant_pool_size=float(np.mean(relevant_pool_sizes)),
                    max_eligible_relevant_pool_size=max(relevant_pool_sizes),
                    surrealdb_score_zero_issue=bool(
                        getattr(engine, "text_score_zero_detected", False)
                    ),
                )

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
