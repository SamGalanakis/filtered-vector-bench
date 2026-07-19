# Fairness policy

This benchmark is intended to make material asymmetries visible, not to claim that two different
systems are internally identical. The following rules are part of the benchmark contract.

## Identical workload

For a given dimension and scale, both engines consume byte-identical float32 vectors, source IDs,
tenant assignments, documents, query vectors, and text queries generated from one fixed seed.
Exact cosine top-K is
computed once with NumPy over each eligible tenant subset and shared by both engines. Query order
is deterministic and every configured engine sees the same matrix. Runs occur serially on the
same host to avoid cross-engine resource contention.

Each embedding cluster has a seeded, rank-ordered topic vocabulary (60 terms by default), disjoint
from the other clusters, plus a shared 2,000-term background vocabulary. Documents contain 80–200
tokens; the topic/background draw is binomial with expected topic share 35%, and both vocabulary
draws are Zipf-weighted. A document's RNG is derived from its source ID, so generation is invariant
to chunking. Each 3–6-term text query uses the topic vocabulary belonging to its query vector's
cluster. The same query mapping is reused across all selectivity tiers.

Full-text and hybrid quality use constructed same-cluster relevance within the eligible tenant
subset: a same-cluster row has grade 1 and every other row grade 0. The report computes nDCG@10;
when a tiny eligible subset contains no row from the query cluster, its ideal DCG is zero and the
query receives nDCG 0. Exact top-K recall is deliberately not reported for text because engine
lexical scores are not a shared exact-distance ordering. nDCG against the constructed relevance is
the shared standard for both FTS and hybrid.

Documents are stored in a fixed-width byte-string `.npy` memory map and decoded one load batch at a
time, just like vector chunks. With the default vocabulary widths the 200-token bound reserves
1,199 bytes per row: about 1.12 GiB at 1M rows and 11.17 GiB at 10M (plus a 128-byte NumPy header).
The fixed width trades some disk overhead for deterministic O(1) random access without an in-RAM
million-string object array.

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
and then builds HNSW. When text is enabled, SurrealDB also defines its FULLTEXT index before
inserts, so its text-index cost is inseparable from load; PostgreSQL generates an English
`tsvector` during COPY and separately times its post-load GIN build. PostgreSQL records vector and
text index seconds independently in `index_details`. The harness reports insert throughput,
index-build time, and total
time-to-queryable separately. The cross-engine comparison uses total time-to-queryable; raw load
rate alone is not presented as equivalent work.

The ordinary ladder loads vector and text indexes together. A separate 100k smoke validation must
compare vector-only with vector+text load for each engine so SurrealDB's maintain-during-load cost
remains visible; those delta measurements belong in the validation report rather than being
misrepresented as a separately exposed SurrealDB build timer.

`batch_size` is the maximum row count handed to both adapters. SurrealDB sends compact plain-text
`/sql` inserts with four in-flight workers and splits a configured batch further when its encoded
request would reach 4 MiB. The standard ladder uses 200 rows per configured batch, matching the
gentle control-loader shape. PostgreSQL consumes the same row batches but writes them into one
streaming COPY transaction; COPY chunk boundaries are client buffering units, not independently
parsed server statements, so request concurrency is not analogous there.

SurrealDB ingestion memory is load-pattern-sensitive. The first full ladder used 500-row JSON-RPC
variable inserts and reached 47.4 GiB RSS at 834k rows, while the control's 200-row, four-worker
`/sql` pattern completed the same 1M-row source corpus at 12.8 GiB RSS. This harness deliberately
uses the gentler bounded pattern so indexing and query phases can execute. The aggressive-pattern
behavior remains a real result and deserves a dedicated future ingestion-pattern phase; it is not
discarded or presented as though it did not happen.

## Memory

The sampler walks each engine's Linux process tree every two seconds. It records summed RSS and,
when `/proc/<pid>/smaps_rollup` is readable, summed proportional set size (PSS). PostgreSQL is a
multi-process server, so its summed RSS double-counts shared pages; PSS is the primary comparison
and both values are retained. SurrealDB is normally a single process, but receives exactly the
same accounting. Docker container PIDs are resolved from the host. Samples are phase-labeled.
PostgreSQL keeps one client backend alive throughout query suites, as the control harness does, so
the postmaster and its query backend are simultaneously present when the sampler walks descendants.

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

Before every selectivity suite, each adapter captures `EXPLAIN` for its exact query form. Vector
suites gate the vector index, FTS suites gate the GIN/FULLTEXT index, and hybrid suites record
vector, text, and combined gates. A failed gate is retained beside the timings and highlighted in
the summary; the suite still runs because fallback planning is itself a result. PostgreSQL emits
one JSON plan containing both materialized CTEs. SurrealDB 3.2.1 cannot prefix the multi-statement
`LET` fusion form with one `EXPLAIN`, so one RPC request captures EXPLAIN output for the two exact
candidate subqueries used by that statement; the combined gate requires both named indexes. Raw
plans are stored for audit.

## Query forms

Each adapter uses its engine's documented idiomatic ANN form rather than forcing textual symmetry:

- SurrealDB: `WHERE embedding <|K,EF|> $vec [AND tenant = $tenant]`
- PostgreSQL + pgvector: `[WHERE tenant = $1] ORDER BY embedding <=> $2 LIMIT K`, after setting
  `hnsw.ef_search` and the configured `hnsw.iterative_scan` mode

These may use pre- or post-filtering differently. Exact eligible-subset recall and underfill are
reported precisely so that behavior remains observable.

The full-text and hybrid forms are likewise native rather than textually symmetric:

- SurrealDB FTS: `content @0@ $text [AND tenant = $tenant]`, ordered by
  `search::score(0)`. The schema uses `TOKENIZERS class FILTERS lowercase,ascii` and a
  `FULLTEXT ... BM25` index. Hybrid is one RPC query request: two tenant-filtered `LET` subqueries
  retrieve text and HNSW top-40 candidates, followed by
  `search::rrf([$text_candidates, $vector_candidates], 10, 60)`. In SurrealDB 3.2.1 the function
  signature is `(lists, limit, k)`.
- PostgreSQL FTS: a stored generated `to_tsvector('english', content)` column with GIN, queried via
  `plainto_tsquery('english', ...)` and ordered by `ts_rank_cd`. Hybrid is one SQL statement with
  tenant-filtered vector and text top-40 materialized CTEs, rank-number RRF with `k=60`, and
  `LIMIT 10`.

PostgreSQL's stock ranking is lexical `ts_rank_cd`; it is not corpus-IDF BM25. True-BM25 extensions
exist, but they are not available on mainstream managed PostgreSQL services and are outside this
stock-engine comparison. SurrealDB's native FULLTEXT index does use BM25. This ranking asymmetry is
inherent and must be stated alongside results, not tuned away.

SurrealDB issue #7290 reports `search::score(0) = 0` for all matches on some fresh databases. The
harness detects and records an all-zero nonempty result set in every FTS/hybrid suite. The issue
thread notes that the failure was associated with very small corpora, so smoke and ladder corpora
remain above that range; no silent client-side reranking is allowed. If observed, results and the
flag remain as engine behavior rather than being presented as functioning BM25.

## Relationship to the reference control

The reference `vector-bench` corpus is not the same workload as this ladder's default corpus. It
uses seed 7423, 100 clusters, and cluster noise sigma 0.01; the ladder defaults use seed 20250308,
50 clusters, and sigma 0.12. Both normalize centers, corpus vectors, and center-plus-noise query
vectors, but the control creates a separate 100-query set per tier whereas the ladder deliberately
reuses one query set across selectivities for paired comparisons. Tenant assignment is independent
of vector cluster in both. The control assigns additional 50% and many small-background tenants;
the ladder assigns disjoint 10%, 1%, and 0.1% tenants plus one background label.

Those distribution choices explain why PostgreSQL ef=40 unfiltered recall at 1M is not expected to
match the control's 0.606. In an audited sample, the nearest corpus cosine was 0.923 in the tight
control distribution and only 0.175 in the ladder distribution. An independent exact scan matched
the ladder's stored ground-truth top 10, ruling out tier or truth-subset mislabeling. This is a
legitimate configured workload difference, not an engine comparison.

Methodology otherwise agrees on post-index `ANALYZE`, per-session `hnsw.ef_search`, cosine distance,
and PostgreSQL HNSW construction values `m=16, ef_construction=64` (now explicit in the ladder).
The control also configures 8 GiB `shared_buffers`, 8 GiB `maintenance_work_mem`, and a long-lived
suite backend; the ladder leaves PostgreSQL memory settings at server defaults under its common
cell cap. Its roughly 5.6 GiB control query PSS is therefore useful for validating full-tree
accounting, but is not a target memory value for the differently configured ladder server.

## Versions and host evidence

Container tags are pinned to `surrealdb/surrealdb:v3.2.1` and `pgvector/pgvector:pg17`; binary
SurrealDB downloads are pinned and checksum-verified. Runtime server and extension versions are
recorded rather than inferred from tags. Every result directory includes the normalized config,
its SHA-256 hash, `lscpu`, `/proc/meminfo`, platform data, and timestamps. Comparisons from
different machines or configs must not be merged into one line.
