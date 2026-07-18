# Fairness policy

This benchmark is intended to make material asymmetries visible, not to claim that two different
systems are internally identical. The following rules are part of the benchmark contract.

## Identical workload

For a given dimension and scale, both engines consume byte-identical float32 vectors, source IDs,
tenant assignments, and query vectors generated from one fixed seed. Exact cosine top-K is
computed once with NumPy over each eligible tenant subset and shared by both engines. Query order
is deterministic and every configured engine sees the same matrix. Runs occur serially on the
same host to avoid cross-engine resource contention.

## Durability

SurrealDB uses its RocksDB backend with SurrealDB 3.x sync-by-default behavior. PostgreSQL uses
`synchronous_commit=on`; no unlogged tables or durability-relaxing load switches are used. Both
therefore measure durable default writes rather than comparing durable and ephemeral storage.

## Index parameter policy

Each engine's HNSW construction defaults are used. Those defaults are what a new user receives,
and silently making one engine imitate another would be a different experiment. Effective values
and versions are recorded. Search breadth (`ef`) is workload-controlled because it is the curve's
independent variable. PostgreSQL's default/strict/relaxed iterative modes are separate series, not
pooled results.

## Load and build

SurrealDB's index is defined before inserts and maintained during load. PostgreSQL loads the table
and then builds HNSW. The harness reports insert throughput, index-build time, and total
time-to-queryable separately. The cross-engine comparison uses total time-to-queryable; raw load
rate alone is not presented as equivalent work.

## Memory

The sampler walks each engine's Linux process tree every two seconds. It records summed RSS and,
when `/proc/<pid>/smaps_rollup` is readable, summed proportional set size (PSS). PostgreSQL is a
multi-process server, so its summed RSS double-counts shared pages; PSS is the primary comparison
and both values are retained. SurrealDB is normally a single process, but receives exactly the
same accounting. Docker container PIDs are resolved from the host. Samples are phase-labeled.

Every engine starts under the same configured OS memory cap. `systemd-run --user --scope` with
`MemoryMax` is preferred for local processes; an address-space `ulimit` fallback is used where a
user systemd manager is unavailable. Docker receives the equivalent `--memory` limit. A cap kill
is a first-class `exceeded_memory_cap` cell outcome, plotted at the cap, not a missing observation.

## Warm and cold discipline

Cells run serially. After load/index build, the harness observes a fixed settle interval for
compaction or autovacuum. Warm filtered suites follow two stop/start cycles. Each cycle reports
time-to-ready and the first KNN separately; time-to-first-query is their sum. The harness does not
drop the host page cache because that requires privileged, machine-wide mutation and would not
represent an ordinary service restart. This is an engine-process cold restart, explicitly not a
physical cold-disk test.

## Plan verification

Before every selectivity suite, each adapter captures `EXPLAIN` for its exact query form and checks
for its vector index. A failed gate is retained beside the timings and highlighted in the summary;
the suite still runs because fallback planning is itself a result. The gate is deliberately
conservative and raw plans are stored for audit.

## Query forms

Each adapter uses its engine's documented idiomatic ANN form rather than forcing textual symmetry:

- SurrealDB: `WHERE embedding <|K,EF|> $vec [AND tenant = $tenant]`
- PostgreSQL + pgvector: `[WHERE tenant = $1] ORDER BY embedding <=> $2 LIMIT K`, after setting
  `hnsw.ef_search` and the configured `hnsw.iterative_scan` mode

These may use pre- or post-filtering differently. Exact eligible-subset recall and underfill are
reported precisely so that behavior remains observable.

## Versions and host evidence

Container tags are pinned to `surrealdb/surrealdb:v3.2.1` and `pgvector/pgvector:pg17`; binary
SurrealDB downloads are pinned and checksum-verified. Runtime server and extension versions are
recorded rather than inferred from tags. Every result directory includes the normalized config,
its SHA-256 hash, `lscpu`, `/proc/meminfo`, platform data, and timestamps. Comparisons from
different machines or configs must not be merged into one line.

