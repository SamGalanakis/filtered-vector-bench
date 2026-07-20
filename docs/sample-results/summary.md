# Benchmark summary

Measurement state: **steady**  
Config SHA-256: `2af455e9cbae2c9400a7d98957678dd158f740f208bac5255f3ecc7990951622`  
Host: `turbo2-sam` · `Linux-6.8.0-136-generic-x86_64-with-glibc2.39` · Python `3.13.14`

## Cell overview

| State | Engine | Dims | Vectors | Outcome | Version | Load rows/s | Queryable s | Load peak PSS/RSS GiB | Query peak PSS/RSS GiB | Cold first-query s |
|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|
| steady | SurrealDB | 1024 | 300,000 | ok | storage RocksDB, surrealdb surrealdb-3.2.1 | 629.922 | 476.249 | 10.350 | 36.997 | 4.663 |
| steady | PostgreSQL | 1024 | 300,000 | ok | pgvector 0.8.3, postgresql 17.10 | 2,405.851 | 892.303 | 0.162 | 0.168 | 0.239 |
| steady | SurrealDB | 1024 | 1,000,000 | exceeded_memory_cap (vector_warmup) | storage RocksDB, surrealdb surrealdb-3.2.1 | 837.881 | 1,193.487 | 18.906 | — | 21.922 |
| steady | PostgreSQL | 1024 | 1,000,000 | ok | pgvector 0.8.3, postgresql 17.10 | 2,514.450 | 3,562.942 | 0.163 | 0.169 | 0.240 |

## Quiescence

| State | Engine | Dims | Scale | Seconds | Samples | Stable samples | Cap hit | ANALYZE s | Autovacuum wait s |
|---|---|---:|---:|---:|---:|---:|---|---:|---:|
| steady | PostgreSQL | 1024 | 1,000,000 | 182.198 | 19 | 12 | false | 0.307 | 0.005 |
| steady | PostgreSQL | 1024 | 300,000 | 182.192 | 19 | 12 | false | 0.292 | 0.005 |
| steady | SurrealDB | 1024 | 1,000,000 | 354.060 | 34 | 12 | false | — | — |
| steady | SurrealDB | 1024 | 300,000 | 233.336 | 23 | 12 | false | — | — |

## Filtered suites

| State | Engine | Dims | Vectors | Stage | Tier | Selectivity | ef | Mode | Index plan | Recall@10 | p50 ms | p95 ms | Underfill | Mean results |
|---|---|---:|---:|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | unfiltered | 100% | 40 | default | yes | 0.1020 | 3.688 | 6.172 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | unfiltered | 100% | 40 | relaxed_order | yes | 0.1020 | 3.887 | 6.370 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | unfiltered | 100% | 64 | default | yes | 0.1510 | 5.347 | 10.088 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | unfiltered | 100% | 64 | relaxed_order | yes | 0.1510 | 5.427 | 10.141 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_1 | 10% | 40 | default | yes | 0.0880 | 3.819 | 6.247 | 100/100 (100.00%) | 3.93 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_1 | 10% | 40 | relaxed_order | yes | 0.2220 | 10.050 | 13.852 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_1 | 10% | 64 | default | yes | 0.1400 | 5.337 | 9.839 | 89/100 (89.00%) | 6.26 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_1 | 10% | 64 | relaxed_order | yes | 0.2510 | 9.917 | 16.587 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_01 | 1% | 40 | default | yes | 0.0300 | 3.698 | 6.311 | 100/100 (100.00%) | 0.44 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_01 | 1% | 40 | relaxed_order | yes | 0.5360 | 36.003 | 50.445 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_01 | 1% | 64 | default | yes | 0.0490 | 5.241 | 9.616 | 100/100 (100.00%) | 0.75 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_01 | 1% | 64 | relaxed_order | yes | 0.5380 | 37.544 | 52.442 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | default | **NO** | 0.0040 | 3.843 | 6.367 | 100/100 (100.00%) | 0.05 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | relaxed_order | **NO** | 0.4250 | 81.453 | 95.404 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | default | **NO** | 0.0060 | 5.316 | 9.753 | 100/100 (100.00%) | 0.06 |
| steady | PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | relaxed_order | **NO** | 0.4260 | 79.621 | 93.213 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | unfiltered | 100% | 40 | default | yes | 0.2490 | 3.349 | 6.105 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | unfiltered | 100% | 40 | relaxed_order | yes | 0.2490 | 3.413 | 6.344 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | unfiltered | 100% | 64 | default | yes | 0.3500 | 4.493 | 7.971 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | unfiltered | 100% | 64 | relaxed_order | yes | 0.3500 | 4.565 | 7.889 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 40 | default | yes | 0.2000 | 3.279 | 6.209 | 100/100 (100.00%) | 3.76 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 40 | relaxed_order | yes | 0.4100 | 7.250 | 12.627 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 64 | default | yes | 0.2790 | 4.587 | 7.799 | 89/100 (89.00%) | 5.93 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 64 | relaxed_order | yes | 0.4320 | 7.465 | 13.336 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 40 | default | **NO** | 0.0210 | 3.359 | 6.306 | 100/100 (100.00%) | 0.30 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 40 | relaxed_order | **NO** | 0.5990 | 21.252 | 37.820 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 64 | default | **NO** | 0.0330 | 4.497 | 7.542 | 100/100 (100.00%) | 0.44 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 64 | relaxed_order | **NO** | 0.6000 | 21.605 | 37.706 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | default | **NO** | 0.0030 | 3.333 | 6.335 | 100/100 (100.00%) | 0.03 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | relaxed_order | **NO** | 0.3480 | 76.521 | 91.720 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | default | **NO** | 0.0040 | 4.557 | 7.938 | 100/100 (100.00%) | 0.04 |
| steady | PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | relaxed_order | **NO** | 0.3480 | 78.338 | 90.513 | 0/100 (0.00%) | 10.00 |
| steady | SurrealDB | 1024 | 300,000 | pre_churn | unfiltered | 100% | 40 | default | yes | 0.1190 | 35.272 | 41.856 | 0/100 (0.00%) | 10.00 |
| steady | SurrealDB | 1024 | 300,000 | pre_churn | unfiltered | 100% | 64 | default | yes | 0.1730 | 34.709 | 39.492 | 0/100 (0.00%) | 10.00 |
| steady | SurrealDB | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 40 | default | yes | 0.5680 | 228.967 | 331.795 | 0/100 (0.00%) | 10.00 |
| steady | SurrealDB | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 64 | default | yes | 0.6740 | 351.925 | 482.447 | 0/100 (0.00%) | 10.00 |
| steady | SurrealDB | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 40 | default | yes | 0.6570 | 1039.782 | 1652.147 | 2/100 (2.00%) | 9.82 |
| steady | SurrealDB | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 64 | default | yes | 0.6940 | 1723.119 | 2430.679 | 2/100 (2.00%) | 9.82 |
| steady | SurrealDB | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | default | yes | 0.7590 | 10363.167 | 12490.046 | 9/100 (9.00%) | 9.22 |
| steady | SurrealDB | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | default | yes | 0.7890 | 14109.084 | 16434.906 | 9/100 (9.00%) | 9.22 |

## Full-text suites

| State | Engine | Dims | Documents | Tier | Selectivity | Relevant pool min/mean/max | Text index plan | nDCG@10 | p50 ms | p95 ms | Underfill | Mean results | Score issue #7290 |
|---|---|---:|---:|---|---:|---:|---|---:|---:|---:|---:|---:|---|
| steady | PostgreSQL | 1024 | 1,000,000 | unfiltered | 100% | 19701/19968.9/20292 | yes | 1.0000 | 21.243 | 87.074 | 0/100 (0.00%) | 10.00 | no |
| steady | PostgreSQL | 1024 | 1,000,000 | tenant_s0_1 | 10% | 1879/2004.3/2110 | yes | 0.9987 | 11.442 | 41.795 | 1/100 (1.00%) | 9.98 | no |
| steady | PostgreSQL | 1024 | 1,000,000 | tenant_s0_01 | 1% | 163/199.1/231 | yes | 0.8712 | 7.808 | 36.803 | 32/100 (32.00%) | 8.32 | no |
| steady | PostgreSQL | 1024 | 1,000,000 | tenant_s0_001 | 0.1% | 30/30.0/30 | yes | 0.5501 | 2.487 | 11.790 | 77/100 (77.00%) | 4.66 | no |
| steady | PostgreSQL | 1024 | 300,000 | unfiltered | 100% | 5808/5973.9/6159 | yes | 1.0000 | 6.054 | 27.391 | 0/100 (0.00%) | 10.00 | no |
| steady | PostgreSQL | 1024 | 300,000 | tenant_s0_1 | 10% | 549/600.5/652 | yes | 0.9744 | 3.148 | 11.156 | 7/100 (7.00%) | 9.66 | no |
| steady | PostgreSQL | 1024 | 300,000 | tenant_s0_01 | 1% | 41/59.7/84 | yes | 0.6821 | 2.190 | 9.090 | 58/100 (58.00%) | 6.24 | no |
| steady | PostgreSQL | 1024 | 300,000 | tenant_s0_001 | 0.1% | 30/30.0/30 | yes | 0.5288 | 0.727 | 3.201 | 76/100 (76.00%) | 4.56 | no |
| steady | SurrealDB | 1024 | 300,000 | unfiltered | 100% | 5808/5973.9/6159 | yes | 1.0000 | 90.268 | 304.425 | 0/100 (0.00%) | 10.00 | no |
| steady | SurrealDB | 1024 | 300,000 | tenant_s0_1 | 10% | 549/600.5/652 | yes | 0.9683 | 86.407 | 255.632 | 7/100 (7.00%) | 9.59 | no |
| steady | SurrealDB | 1024 | 300,000 | tenant_s0_01 | 1% | 41/59.7/84 | yes | 0.6531 | 69.088 | 261.325 | 61/100 (61.00%) | 5.91 | no |
| steady | SurrealDB | 1024 | 300,000 | tenant_s0_001 | 0.1% | 30/30.0/30 | yes | 0.5068 | 72.078 | 262.946 | 77/100 (77.00%) | 4.36 | no |

## Hybrid suites

| State | Engine | Dims | Documents | Tier | Selectivity | Relevant pool min/mean/max | ef | Vector plan | Text plan | Both | nDCG@10 | p50 ms | p95 ms | Underfill | Mean results |
|---|---|---:|---:|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|
| steady | PostgreSQL | 1024 | 1,000,000 | unfiltered | 100% | 19701/19968.9/20292 | 40 | yes | yes | yes | 0.7728 | 28.362 | 108.015 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | unfiltered | 100% | 19701/19968.9/20292 | 64 | yes | yes | yes | 0.8047 | 31.048 | 110.477 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | tenant_s0_1 | 10% | 1879/2004.3/2110 | 40 | yes | yes | yes | 0.8222 | 17.119 | 47.235 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | tenant_s0_1 | 10% | 1879/2004.3/2110 | 64 | yes | yes | yes | 0.8081 | 19.317 | 48.876 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | tenant_s0_01 | 1% | 163/199.1/231 | 40 | **NO** | yes | **NO** | 0.9693 | 94.747 | 127.425 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | tenant_s0_01 | 1% | 163/199.1/231 | 64 | **NO** | yes | **NO** | 0.9693 | 94.348 | 125.847 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | tenant_s0_001 | 0.1% | 30/30.0/30 | 40 | **NO** | yes | **NO** | 0.8813 | 6.962 | 22.639 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 1,000,000 | tenant_s0_001 | 0.1% | 30/30.0/30 | 64 | **NO** | yes | **NO** | 0.8813 | 7.257 | 20.163 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | unfiltered | 100% | 5808/5973.9/6159 | 40 | yes | yes | yes | 0.8457 | 12.752 | 32.992 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | unfiltered | 100% | 5808/5973.9/6159 | 64 | yes | yes | yes | 0.8836 | 13.824 | 33.329 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | tenant_s0_1 | 10% | 549/600.5/652 | 40 | yes | yes | yes | 0.8335 | 8.172 | 17.002 | 5/100 (5.00%) | 9.85 |
| steady | PostgreSQL | 1024 | 300,000 | tenant_s0_1 | 10% | 549/600.5/652 | 64 | yes | yes | yes | 0.8457 | 10.080 | 18.739 | 4/100 (4.00%) | 9.90 |
| steady | PostgreSQL | 1024 | 300,000 | tenant_s0_01 | 1% | 41/59.7/84 | 40 | **NO** | yes | **NO** | 0.8937 | 13.439 | 21.989 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | tenant_s0_01 | 1% | 41/59.7/84 | 64 | **NO** | yes | **NO** | 0.8937 | 13.553 | 21.663 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | tenant_s0_001 | 0.1% | 30/30.0/30 | 40 | **NO** | yes | **NO** | 0.9277 | 2.786 | 4.849 | 0/100 (0.00%) | 10.00 |
| steady | PostgreSQL | 1024 | 300,000 | tenant_s0_001 | 0.1% | 30/30.0/30 | 64 | **NO** | yes | **NO** | 0.9277 | 2.748 | 4.423 | 0/100 (0.00%) | 10.00 |
| steady | SurrealDB | 1024 | 300,000 | unfiltered | 100% | 5808/5973.9/6159 | 40 | yes | yes | yes | 0.6733 | 90.830 | 272.705 | 0/100 (0.00%) | 10.00 |
| steady | SurrealDB | 1024 | 300,000 | unfiltered | 100% | 5808/5973.9/6159 | 64 | yes | yes | yes | 0.6796 | 95.963 | 283.676 | 0/100 (0.00%) | 10.00 |
| steady | SurrealDB | 1024 | 300,000 | tenant_s0_1 | 10% | 549/600.5/652 | 40 | yes | yes | yes | 0.8901 | 271.032 | 469.190 | 0/100 (0.00%) | 10.00 |
| steady | SurrealDB | 1024 | 300,000 | tenant_s0_1 | 10% | 549/600.5/652 | 64 | yes | yes | yes | 0.9700 | 409.842 | 614.946 | 0/100 (0.00%) | 10.00 |
| steady | SurrealDB | 1024 | 300,000 | tenant_s0_01 | 1% | 41/59.7/84 | 40 | yes | yes | yes | 0.9363 | 1183.974 | 1661.093 | 1/100 (1.00%) | 9.92 |
| steady | SurrealDB | 1024 | 300,000 | tenant_s0_01 | 1% | 41/59.7/84 | 64 | yes | yes | yes | 0.9132 | 1768.458 | 2322.625 | 1/100 (1.00%) | 9.92 |
| steady | SurrealDB | 1024 | 300,000 | tenant_s0_001 | 0.1% | 30/30.0/30 | 40 | yes | yes | yes | 0.9331 | 5342.847 | 6511.199 | 2/100 (2.00%) | 9.85 |
| steady | SurrealDB | 1024 | 300,000 | tenant_s0_001 | 0.1% | 30/30.0/30 | 64 | yes | yes | yes | 0.9279 | 10852.238 | 12064.605 | 2/100 (2.00%) | 9.85 |

## Fresh vs steady

Only exact `(engine, dimensions, scale, suite, tier, ef, mode)` matches are shown.

| Suite | Engine | Dims | Scale | Tier | ef | Mode | Fresh p50 ms | Steady p50 ms | Steady − fresh ms | Change |
|---|---|---:|---:|---|---:|---|---:|---:|---:|---:|
| FTS | PostgreSQL | 1024 | 1,000,000 | unfiltered | — | default | 25.343 | 21.243 | -4.100 | -16.2% |
| FTS | PostgreSQL | 1024 | 1,000,000 | tenant_s0_1 | — | default | 13.589 | 11.442 | -2.147 | -15.8% |
| FTS | PostgreSQL | 1024 | 1,000,000 | tenant_s0_01 | — | default | 8.736 | 7.808 | -0.928 | -10.6% |
| FTS | PostgreSQL | 1024 | 1,000,000 | tenant_s0_001 | — | default | 3.023 | 2.487 | -0.535 | -17.7% |
| FTS | PostgreSQL | 1024 | 300,000 | unfiltered | — | default | 6.921 | 6.054 | -0.867 | -12.5% |
| FTS | PostgreSQL | 1024 | 300,000 | tenant_s0_1 | — | default | 2.719 | 3.148 | +0.429 | +15.8% |
| FTS | PostgreSQL | 1024 | 300,000 | tenant_s0_01 | — | default | 2.387 | 2.190 | -0.197 | -8.2% |
| FTS | PostgreSQL | 1024 | 300,000 | tenant_s0_001 | — | default | 2.266 | 0.727 | -1.539 | -67.9% |
| FTS | SurrealDB | 1024 | 300,000 | unfiltered | — | default | 171.226 | 90.268 | -80.957 | -47.3% |
| FTS | SurrealDB | 1024 | 300,000 | tenant_s0_1 | — | default | 95.202 | 86.407 | -8.795 | -9.2% |
| FTS | SurrealDB | 1024 | 300,000 | tenant_s0_01 | — | default | 72.293 | 69.088 | -3.205 | -4.4% |
| FTS | SurrealDB | 1024 | 300,000 | tenant_s0_001 | — | default | 72.077 | 72.078 | +0.002 | +0.0% |
| HYBRID | PostgreSQL | 1024 | 1,000,000 | unfiltered | 40 | default | 34.702 | 28.362 | -6.339 | -18.3% |
| HYBRID | PostgreSQL | 1024 | 1,000,000 | unfiltered | 64 | default | 35.989 | 31.048 | -4.941 | -13.7% |
| HYBRID | PostgreSQL | 1024 | 1,000,000 | tenant_s0_1 | 40 | default | 18.577 | 17.119 | -1.458 | -7.9% |
| HYBRID | PostgreSQL | 1024 | 1,000,000 | tenant_s0_1 | 64 | default | 20.696 | 19.317 | -1.379 | -6.7% |
| HYBRID | PostgreSQL | 1024 | 1,000,000 | tenant_s0_01 | 40 | default | 100.442 | 94.747 | -5.695 | -5.7% |
| HYBRID | PostgreSQL | 1024 | 1,000,000 | tenant_s0_01 | 64 | default | 103.064 | 94.348 | -8.716 | -8.5% |
| HYBRID | PostgreSQL | 1024 | 1,000,000 | tenant_s0_001 | 40 | default | 8.236 | 6.962 | -1.273 | -15.5% |
| HYBRID | PostgreSQL | 1024 | 1,000,000 | tenant_s0_001 | 64 | default | 9.452 | 7.257 | -2.195 | -23.2% |
| HYBRID | PostgreSQL | 1024 | 300,000 | unfiltered | 40 | default | 13.075 | 12.752 | -0.323 | -2.5% |
| HYBRID | PostgreSQL | 1024 | 300,000 | unfiltered | 64 | default | 14.774 | 13.824 | -0.950 | -6.4% |
| HYBRID | PostgreSQL | 1024 | 300,000 | tenant_s0_1 | 40 | default | 8.514 | 8.172 | -0.342 | -4.0% |
| HYBRID | PostgreSQL | 1024 | 300,000 | tenant_s0_1 | 64 | default | 10.125 | 10.080 | -0.044 | -0.4% |
| HYBRID | PostgreSQL | 1024 | 300,000 | tenant_s0_01 | 40 | default | 14.707 | 13.439 | -1.268 | -8.6% |
| HYBRID | PostgreSQL | 1024 | 300,000 | tenant_s0_01 | 64 | default | 14.825 | 13.553 | -1.272 | -8.6% |
| HYBRID | PostgreSQL | 1024 | 300,000 | tenant_s0_001 | 40 | default | 4.495 | 2.786 | -1.709 | -38.0% |
| HYBRID | PostgreSQL | 1024 | 300,000 | tenant_s0_001 | 64 | default | 4.446 | 2.748 | -1.699 | -38.2% |
| HYBRID | SurrealDB | 1024 | 300,000 | unfiltered | 40 | default | 109.996 | 90.830 | -19.166 | -17.4% |
| HYBRID | SurrealDB | 1024 | 300,000 | unfiltered | 64 | default | 102.706 | 95.963 | -6.742 | -6.6% |
| HYBRID | SurrealDB | 1024 | 300,000 | tenant_s0_1 | 40 | default | 298.169 | 271.032 | -27.137 | -9.1% |
| HYBRID | SurrealDB | 1024 | 300,000 | tenant_s0_1 | 64 | default | 405.698 | 409.842 | +4.145 | +1.0% |
| HYBRID | SurrealDB | 1024 | 300,000 | tenant_s0_01 | 40 | default | 1212.103 | 1183.974 | -28.129 | -2.3% |
| HYBRID | SurrealDB | 1024 | 300,000 | tenant_s0_01 | 64 | default | 1789.102 | 1768.458 | -20.644 | -1.2% |
| HYBRID | SurrealDB | 1024 | 300,000 | tenant_s0_001 | 40 | default | 10223.153 | 5342.847 | -4880.306 | -47.7% |
| HYBRID | SurrealDB | 1024 | 300,000 | tenant_s0_001 | 64 | default | 14601.451 | 10852.238 | -3749.212 | -25.7% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | unfiltered | 40 | default | 10.120 | 3.688 | -6.431 | -63.6% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | unfiltered | 40 | relaxed_order | 9.493 | 3.887 | -5.606 | -59.1% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | unfiltered | 64 | default | 12.875 | 5.347 | -7.528 | -58.5% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | unfiltered | 64 | relaxed_order | 12.460 | 5.427 | -7.033 | -56.4% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | tenant_s0_1 | 40 | default | 8.446 | 3.819 | -4.627 | -54.8% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | tenant_s0_1 | 40 | relaxed_order | 11.468 | 10.050 | -1.418 | -12.4% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | tenant_s0_1 | 64 | default | 6.281 | 5.337 | -0.944 | -15.0% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | tenant_s0_1 | 64 | relaxed_order | 12.658 | 9.917 | -2.741 | -21.7% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | tenant_s0_01 | 40 | default | 4.780 | 3.698 | -1.082 | -22.6% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | tenant_s0_01 | 40 | relaxed_order | 47.420 | 36.003 | -11.417 | -24.1% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | tenant_s0_01 | 64 | default | 6.017 | 5.241 | -0.775 | -12.9% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | tenant_s0_01 | 64 | relaxed_order | 42.914 | 37.544 | -5.370 | -12.5% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | tenant_s0_001 | 40 | default | 4.001 | 3.843 | -0.158 | -4.0% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | tenant_s0_001 | 40 | relaxed_order | 86.759 | 81.453 | -5.305 | -6.1% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | tenant_s0_001 | 64 | default | 5.557 | 5.316 | -0.241 | -4.3% |
| VECTOR | PostgreSQL | 1024 | 1,000,000 | tenant_s0_001 | 64 | relaxed_order | 90.015 | 79.621 | -10.394 | -11.5% |
| VECTOR | PostgreSQL | 1024 | 300,000 | unfiltered | 40 | default | 3.370 | 3.349 | -0.021 | -0.6% |
| VECTOR | PostgreSQL | 1024 | 300,000 | unfiltered | 40 | relaxed_order | 3.448 | 3.413 | -0.035 | -1.0% |
| VECTOR | PostgreSQL | 1024 | 300,000 | unfiltered | 64 | default | 4.521 | 4.493 | -0.028 | -0.6% |
| VECTOR | PostgreSQL | 1024 | 300,000 | unfiltered | 64 | relaxed_order | 4.817 | 4.565 | -0.253 | -5.2% |
| VECTOR | PostgreSQL | 1024 | 300,000 | tenant_s0_1 | 40 | default | 3.398 | 3.279 | -0.119 | -3.5% |
| VECTOR | PostgreSQL | 1024 | 300,000 | tenant_s0_1 | 40 | relaxed_order | 8.128 | 7.250 | -0.878 | -10.8% |
| VECTOR | PostgreSQL | 1024 | 300,000 | tenant_s0_1 | 64 | default | 4.714 | 4.587 | -0.126 | -2.7% |
| VECTOR | PostgreSQL | 1024 | 300,000 | tenant_s0_1 | 64 | relaxed_order | 7.837 | 7.465 | -0.372 | -4.7% |
| VECTOR | PostgreSQL | 1024 | 300,000 | tenant_s0_01 | 40 | default | 3.380 | 3.359 | -0.021 | -0.6% |
| VECTOR | PostgreSQL | 1024 | 300,000 | tenant_s0_01 | 40 | relaxed_order | 23.098 | 21.252 | -1.846 | -8.0% |
| VECTOR | PostgreSQL | 1024 | 300,000 | tenant_s0_01 | 64 | default | 4.594 | 4.497 | -0.097 | -2.1% |
| VECTOR | PostgreSQL | 1024 | 300,000 | tenant_s0_01 | 64 | relaxed_order | 23.124 | 21.605 | -1.519 | -6.6% |
| VECTOR | PostgreSQL | 1024 | 300,000 | tenant_s0_001 | 40 | default | 3.356 | 3.333 | -0.023 | -0.7% |
| VECTOR | PostgreSQL | 1024 | 300,000 | tenant_s0_001 | 40 | relaxed_order | 81.057 | 76.521 | -4.536 | -5.6% |
| VECTOR | PostgreSQL | 1024 | 300,000 | tenant_s0_001 | 64 | default | 4.815 | 4.557 | -0.258 | -5.4% |
| VECTOR | PostgreSQL | 1024 | 300,000 | tenant_s0_001 | 64 | relaxed_order | 83.347 | 78.338 | -5.009 | -6.0% |
| VECTOR | SurrealDB | 1024 | 300,000 | unfiltered | 40 | default | 24602.285 | 35.272 | -24567.014 | -99.9% |
| VECTOR | SurrealDB | 1024 | 300,000 | unfiltered | 64 | default | 38.004 | 34.709 | -3.295 | -8.7% |
| VECTOR | SurrealDB | 1024 | 300,000 | tenant_s0_1 | 40 | default | 310.207 | 228.967 | -81.240 | -26.2% |
| VECTOR | SurrealDB | 1024 | 300,000 | tenant_s0_1 | 64 | default | 431.376 | 351.925 | -79.451 | -18.4% |
| VECTOR | SurrealDB | 1024 | 300,000 | tenant_s0_01 | 40 | default | 1462.762 | 1039.782 | -422.979 | -28.9% |
| VECTOR | SurrealDB | 1024 | 300,000 | tenant_s0_01 | 64 | default | 1977.790 | 1723.119 | -254.671 | -12.9% |
| VECTOR | SurrealDB | 1024 | 300,000 | tenant_s0_001 | 40 | default | 10750.962 | 10363.167 | -387.795 | -3.6% |
| VECTOR | SurrealDB | 1024 | 300,000 | tenant_s0_001 | 64 | default | 14931.005 | 14109.084 | -821.922 | -5.5% |

### Peak process-tree memory

| Engine | Dims | Scale | Fresh peak PSS/RSS GiB | Steady peak PSS/RSS GiB | Delta GiB |
|---|---:|---:|---:|---:|---:|
| PostgreSQL | 1024 | 1,000,000 | 0.238 | 0.236 | -0.002 |
| PostgreSQL | 1024 | 300,000 | 0.236 | 0.236 | -0.000 |
| SurrealDB | 1024 | 1,000,000 | 47.797 | 47.584 | -0.213 |
| SurrealDB | 1024 | 300,000 | 38.019 | 37.092 | -0.927 |

## Metadata

```json
{
  "config_sha256": "2af455e9cbae2c9400a7d98957678dd158f740f208bac5255f3ecc7990951622",
  "hardware_files": [
    "lscpu.txt",
    "meminfo.txt"
  ],
  "measurement_state": "steady",
  "query_topics": "tenant_present",
  "suites": {
    "fts": true,
    "hybrid": true,
    "vector": true
  },
  "versions": {
    "postgres-d1024-n1000000": {
      "pgvector": "0.8.3",
      "postgresql": "17.10"
    },
    "postgres-d1024-n300000": {
      "pgvector": "0.8.3",
      "postgresql": "17.10"
    },
    "surrealdb-d1024-n1000000": {
      "storage": "RocksDB",
      "surrealdb": "surrealdb-3.2.1"
    },
    "surrealdb-d1024-n300000": {
      "storage": "RocksDB",
      "surrealdb": "surrealdb-3.2.1"
    }
  }
}
```

Raw plans, per-query observations, and phase memory samples remain beside this report.
