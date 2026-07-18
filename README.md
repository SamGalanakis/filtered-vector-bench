# filtered-vector-bench

Vector-search benchmarks usually measure unfiltered ANN. Real applications almost always
filter—by tenant, user, permission scope, or category—and *filtered* ANN is where engines
differ most: pre- vs post-filtering, predicate pushdown, selectivity behavior, and memory under
load.

This project runs an identical, configurable filtered-vector workload against multiple engines
on the same machine, with the same data, queries, and exact ground truth. It reports recall,
latency, underfill, memory, cold-start, and load behavior as curves across a scale ladder.
Currently supported engines are SurrealDB (HNSW) and PostgreSQL + pgvector (HNSW). The harness
is engine-extensible by design: one adapter file per engine.

## Quickstart

Requirements are Python 3.11+, `uv`, Docker with at least 4 GiB available, and Linux for full
RSS/PSS accounting. The smoke workload uses 5,000 64-dimensional vectors and normally completes
in a few minutes. From the directory containing your checkout, run:

```bash
cd filtered-vector-bench
uv sync
uv run python scripts/run.py --config configs/smoke.yaml --engine all --out results/smoke
uv run python scripts/report.py --results results/smoke
```

For a serious run, edit the memory cap and engine modes in `configs/default.yaml`, stop unrelated
services, and run the same commands with that config. `configs/full.yaml` adds 3M and 10M rungs;
the 10M × 1024 corpus alone is about 38 GiB as float32 and needs at least 64 GiB RAM plus ample
disk. Results are appended as JSONL/CSV while a cell runs, so completed cells survive failures.

Binary mode downloads SurrealDB `v3.2.1`, verifies its pinned SHA-256 checksum, and caches it.
The built-in binary downloader targets Linux x86-64; use Docker or supply `engines.surrealdb.binary`
on other platforms.
Local PostgreSQL mode expects `initdb` and `postgres` on `PATH` with pgvector available.
Docker mode uses the pinned images in `docker/docker-compose.yml` and gives each cell an isolated
container and volume.

## What a run does

Each `(engine, dimensions, document count)` cell generates or reuses deterministic memory-mapped
data and exact eligible-subset ground truth. It then loads, settles, performs two cold restarts,
runs every configured selectivity/EF/query-mode suite, optionally applies churn, and collects
disk, plan, latency, recall, underfill, and process-tree memory data. A missing vector-index node
in `EXPLAIN` is recorded prominently but does not suppress the measurement. A process killed at
the configured memory cap becomes an `exceeded_memory_cap` result and does not abort later cells.
Generated NumPy data lives in ignored `data/`; disposable engine stores and downloaded binaries
live in ignored `.cache/`. Result directories therefore contain only portable measurements and
reports, not database files.

See [FAIRNESS.md](FAIRNESS.md) before interpreting comparisons. In particular, an engine's
idiomatic query can imply different filtered-ANN semantics; recall and underfill make that visible.

## Sample charts

`scripts/report.py` writes PNG and SVG charts plus `summary.md` beneath the result directory:

- recall@10, p50/p95 latency, and underfill versus selectivity
- peak query memory, restart-to-first-query, load rate, and time-to-queryable versus scale
- when enabled, churn memory and pre/post recall delta

No sample measurements are checked in: charts must identify the machine, exact config, and engine
versions that produced them.

## Configuration

YAML is validated strictly. Scale, dimension, selectivity, EF, query count, cluster distribution,
batching, timeout, memory cap, settle duration, pgvector modes, and churn are configurable. A
selectivity of `1.0` is unfiltered; other values receive deterministic tenant labels with the
requested corpus frequency. The run metadata contains the normalized config and SHA-256 hash.

PostgreSQL modes map to pgvector's `hnsw.iterative_scan`: `default` disables it,
`strict_order` preserves exact ordering, and `relaxed_order` permits relaxed ordering. SurrealDB
has one documented query mode. Engine HNSW construction parameters remain at each engine's
defaults and are captured in metadata.

## Add an engine

1. Add `fvb/engines/<name>.py` implementing `Engine` from `fvb/engines/base.py`.
2. Keep lifecycle and storage inside the per-cell work directory. Honor the supplied timeout and
   memory cap, return stable integer source IDs, and expose the root process IDs for sampling.
3. Implement `explain()` and a conservative `plan_uses_index()` gate.
4. Register the adapter in `fvb/runner.py`, add its fixed chart color in `fvb/report.py`, document
   parity choices in `FAIRNESS.md`, and add it to the smoke workflow.

Contributions should preserve deterministic inputs, raw results, and failure-as-data behavior.
