# Benchmark summary

Config SHA-256: `c299c46e5f5cec70e029af24365edef208d7620d08607de9b71f1d232eb8c2b2`  
Host: `turbo2-sam` · `Linux-6.8.0-136-generic-x86_64-with-glibc2.39` · Python `3.13.14`

## Cell overview

| Engine | Dims | Vectors | Outcome | Version | Load rows/s | Queryable s | Load peak PSS/RSS GiB | Query peak PSS/RSS GiB | Cold first-query s |
|---|---:|---:|---|---|---:|---:|---:|---:|---:|
| PostgreSQL | 1024 | 100,000 | ok | pgvector 0.8.3, postgresql 17.10 | 2,533.916 | 392.179 | 0.160 | 0.162 | 0.237 |
| SurrealDB | 1024 | 100,000 | ok | storage RocksDB, surrealdb surrealdb-3.2.1 | 2,109.679 | 47.401 | 3.825 | 5.647 | 1.214 |
| SurrealDB | 1024 | 300,000 | ok | storage RocksDB, surrealdb surrealdb-3.2.1 | 1,989.373 | 150.801 | 7.272 | 23.517 | 3.278 |
| PostgreSQL | 1024 | 300,000 | ok | pgvector 0.8.3, postgresql 17.10 | 2,513.401 | 870.643 | 0.161 | 0.165 | 0.236 |
| SurrealDB | 1024 | 1,000,000 | exceeded_memory_cap (filtered_suite) | storage RocksDB, surrealdb surrealdb-3.2.1 | 1,975.435 | 506.218 | 11.875 | 47.587 | 16.809 |
| PostgreSQL | 1024 | 1,000,000 | ok | pgvector 0.8.3, postgresql 17.10 | 2,503.743 | 3,561.370 | 0.161 | 0.165 | 0.241 |

## Filtered suites

| Engine | Dims | Vectors | Stage | Tier | Selectivity | ef | Mode | Index plan | Recall@10 | p50 ms | p95 ms | Underfill | Mean results |
|---|---:|---:|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|
| PostgreSQL | 1024 | 100,000 | pre_churn | unfiltered | 100% | 40 | default | yes | 0.5010 | 2.728 | 8.641 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | unfiltered | 100% | 40 | relaxed_order | yes | 0.5010 | 2.598 | 5.170 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | unfiltered | 100% | 40 | strict_order | yes | 0.5010 | 2.592 | 4.711 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | unfiltered | 100% | 64 | default | yes | 0.6540 | 3.406 | 6.293 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | unfiltered | 100% | 64 | relaxed_order | yes | 0.6540 | 3.554 | 6.554 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | unfiltered | 100% | 64 | strict_order | yes | 0.6540 | 3.701 | 6.711 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_1 | 10% | 40 | default | **NO** | 1.0000 | 27.435 | 29.541 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_1 | 10% | 40 | relaxed_order | **NO** | 1.0000 | 27.145 | 29.387 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_1 | 10% | 40 | strict_order | **NO** | 1.0000 | 27.202 | 29.121 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_1 | 10% | 64 | default | yes | 0.4750 | 3.553 | 6.443 | 89/100 (89.00%) | 6.27 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_1 | 10% | 64 | relaxed_order | yes | 0.7080 | 5.003 | 9.529 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_1 | 10% | 64 | strict_order | yes | 0.5610 | 5.355 | 32.761 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_01 | 1% | 40 | default | **NO** | 1.0000 | 2.458 | 2.584 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_01 | 1% | 40 | relaxed_order | **NO** | 1.0000 | 2.460 | 3.426 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_01 | 1% | 40 | strict_order | **NO** | 1.0000 | 2.416 | 3.394 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_01 | 1% | 64 | default | **NO** | 1.0000 | 2.425 | 2.972 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_01 | 1% | 64 | relaxed_order | **NO** | 1.0000 | 2.461 | 2.582 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_01 | 1% | 64 | strict_order | **NO** | 1.0000 | 2.416 | 3.406 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | default | **NO** | 1.0000 | 0.452 | 0.476 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | relaxed_order | **NO** | 1.0000 | 0.451 | 0.471 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | strict_order | **NO** | 1.0000 | 0.481 | 0.534 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | default | **NO** | 1.0000 | 0.453 | 0.476 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | relaxed_order | **NO** | 1.0000 | 0.480 | 0.501 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 100,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | strict_order | **NO** | 1.0000 | 0.453 | 0.478 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | unfiltered | 100% | 40 | default | yes | 0.1120 | 3.861 | 10.338 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | unfiltered | 100% | 40 | relaxed_order | yes | 0.1120 | 3.888 | 6.834 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | unfiltered | 100% | 40 | strict_order | yes | 0.1120 | 3.875 | 6.902 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | unfiltered | 100% | 64 | default | yes | 0.1710 | 5.399 | 9.908 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | unfiltered | 100% | 64 | relaxed_order | yes | 0.1710 | 5.775 | 9.869 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | unfiltered | 100% | 64 | strict_order | yes | 0.1710 | 5.806 | 10.071 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_1 | 10% | 40 | default | yes | 0.1020 | 3.797 | 6.901 | 99/100 (99.00%) | 4.10 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_1 | 10% | 40 | relaxed_order | yes | 0.2230 | 8.884 | 14.389 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_1 | 10% | 40 | strict_order | yes | 0.1020 | 15.779 | 55.489 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_1 | 10% | 64 | default | yes | 0.1590 | 5.744 | 9.977 | 94/100 (94.00%) | 6.38 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_1 | 10% | 64 | relaxed_order | yes | 0.2490 | 10.561 | 16.950 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_1 | 10% | 64 | strict_order | yes | 0.1590 | 13.211 | 54.773 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_01 | 1% | 40 | default | **NO** | 0.0240 | 3.724 | 6.862 | 100/100 (100.00%) | 0.44 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_01 | 1% | 40 | relaxed_order | **NO** | 0.5480 | 36.793 | 47.938 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_01 | 1% | 40 | strict_order | **NO** | 0.1800 | 45.174 | 59.266 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_01 | 1% | 64 | default | **NO** | 0.0460 | 5.534 | 9.857 | 100/100 (100.00%) | 0.70 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_01 | 1% | 64 | relaxed_order | **NO** | 0.5540 | 36.374 | 51.054 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_01 | 1% | 64 | strict_order | **NO** | 0.2180 | 41.491 | 55.876 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | default | **NO** | 0.0030 | 3.776 | 6.980 | 100/100 (100.00%) | 0.03 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | relaxed_order | **NO** | 0.4110 | 70.847 | 78.197 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | strict_order | **NO** | 0.2140 | 71.485 | 81.221 | 6/100 (6.00%) | 9.85 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | default | **NO** | 0.0050 | 5.538 | 9.668 | 100/100 (100.00%) | 0.05 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | relaxed_order | **NO** | 0.4110 | 69.416 | 76.330 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 1,000,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | strict_order | **NO** | 0.2380 | 70.585 | 79.288 | 3/100 (3.00%) | 9.91 |
| PostgreSQL | 1024 | 300,000 | pre_churn | unfiltered | 100% | 40 | default | yes | 0.2240 | 3.320 | 9.992 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | unfiltered | 100% | 40 | relaxed_order | yes | 0.2240 | 3.261 | 5.342 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | unfiltered | 100% | 40 | strict_order | yes | 0.2240 | 3.234 | 5.334 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | unfiltered | 100% | 64 | default | yes | 0.3170 | 4.496 | 8.301 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | unfiltered | 100% | 64 | relaxed_order | yes | 0.3170 | 4.598 | 8.199 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | unfiltered | 100% | 64 | strict_order | yes | 0.3170 | 4.693 | 8.234 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 40 | default | yes | 0.1810 | 3.233 | 5.531 | 100/100 (100.00%) | 3.62 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 40 | relaxed_order | yes | 0.3990 | 7.939 | 11.113 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 40 | strict_order | yes | 0.1970 | 9.880 | 54.183 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 64 | default | **NO** | 0.2780 | 4.561 | 7.986 | 94/100 (94.00%) | 5.90 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 64 | relaxed_order | **NO** | 0.4270 | 8.717 | 12.823 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 64 | strict_order | **NO** | 0.2840 | 9.075 | 53.015 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 40 | default | **NO** | 0.0330 | 3.202 | 5.396 | 100/100 (100.00%) | 0.40 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 40 | relaxed_order | **NO** | 0.6130 | 20.580 | 38.954 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 40 | strict_order | **NO** | 0.3100 | 22.417 | 55.718 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 64 | default | **NO** | 0.0510 | 4.447 | 7.970 | 100/100 (100.00%) | 0.60 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 64 | relaxed_order | **NO** | 0.6130 | 20.181 | 39.966 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 64 | strict_order | **NO** | 0.3580 | 21.713 | 56.572 | 0/100 (0.00%) | 10.00 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | default | **NO** | 0.0040 | 3.142 | 5.170 | 100/100 (100.00%) | 0.04 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | relaxed_order | **NO** | 0.3590 | 60.472 | 68.001 | 1/100 (1.00%) | 9.98 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | strict_order | **NO** | 0.2030 | 60.199 | 65.900 | 1/100 (1.00%) | 9.98 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | default | **NO** | 0.0050 | 4.675 | 8.162 | 100/100 (100.00%) | 0.05 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | relaxed_order | **NO** | 0.3600 | 59.117 | 64.421 | 1/100 (1.00%) | 9.98 |
| PostgreSQL | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | strict_order | **NO** | 0.2240 | 60.856 | 67.508 | 1/100 (1.00%) | 9.98 |
| SurrealDB | 1024 | 100,000 | pre_churn | unfiltered | 100% | 40 | default | yes | 0.5370 | 34.371 | 13014.180 | 0/100 (0.00%) | 10.00 |
| SurrealDB | 1024 | 100,000 | pre_churn | unfiltered | 100% | 64 | default | yes | 0.4880 | 36.847 | 43.210 | 0/100 (0.00%) | 10.00 |
| SurrealDB | 1024 | 100,000 | pre_churn | tenant_s0_1 | 10% | 40 | default | yes | 0.8630 | 215.772 | 330.449 | 0/100 (0.00%) | 10.00 |
| SurrealDB | 1024 | 100,000 | pre_churn | tenant_s0_1 | 10% | 64 | default | yes | 0.8660 | 217.420 | 338.333 | 0/100 (0.00%) | 10.00 |
| SurrealDB | 1024 | 100,000 | pre_churn | tenant_s0_01 | 1% | 40 | default | yes | 0.8310 | 1087.922 | 1409.920 | 3/100 (3.00%) | 9.73 |
| SurrealDB | 1024 | 100,000 | pre_churn | tenant_s0_01 | 1% | 64 | default | yes | 0.8990 | 1766.344 | 2092.774 | 3/100 (3.00%) | 9.73 |
| SurrealDB | 1024 | 100,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | default | yes | 0.9410 | 7198.257 | 7807.752 | 6/100 (6.00%) | 9.47 |
| SurrealDB | 1024 | 100,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | default | yes | 0.9460 | 9001.749 | 9375.959 | 6/100 (6.00%) | 9.47 |
| SurrealDB | 1024 | 300,000 | pre_churn | unfiltered | 100% | 40 | default | yes | 0.5640 | 21893.479 | 25968.129 | 0/100 (0.00%) | 10.00 |
| SurrealDB | 1024 | 300,000 | pre_churn | unfiltered | 100% | 64 | default | yes | 0.1760 | 40.773 | 26630.478 | 0/100 (0.00%) | 10.00 |
| SurrealDB | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 40 | default | yes | 0.5730 | 298.574 | 594.090 | 0/100 (0.00%) | 10.00 |
| SurrealDB | 1024 | 300,000 | pre_churn | tenant_s0_1 | 10% | 64 | default | yes | 0.6740 | 385.644 | 693.753 | 0/100 (0.00%) | 10.00 |
| SurrealDB | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 40 | default | yes | 0.6570 | 1222.704 | 1912.993 | 2/100 (2.00%) | 9.82 |
| SurrealDB | 1024 | 300,000 | pre_churn | tenant_s0_01 | 1% | 64 | default | yes | 0.7030 | 1833.604 | 2398.680 | 2/100 (2.00%) | 9.82 |
| SurrealDB | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 40 | default | yes | 0.7520 | 10566.628 | 12368.927 | 8/100 (8.00%) | 9.28 |
| SurrealDB | 1024 | 300,000 | pre_churn | tenant_s0_001 | 0.1% | 64 | default | yes | 0.7860 | 14927.723 | 16647.141 | 8/100 (8.00%) | 9.28 |

## Metadata

```json
{
  "config_sha256": "c299c46e5f5cec70e029af24365edef208d7620d08607de9b71f1d232eb8c2b2",
  "hardware_files": [
    "lscpu.txt",
    "meminfo.txt"
  ],
  "versions": {
    "postgres-d1024-n100000": {
      "pgvector": "0.8.3",
      "postgresql": "17.10"
    },
    "postgres-d1024-n1000000": {
      "pgvector": "0.8.3",
      "postgresql": "17.10"
    },
    "postgres-d1024-n300000": {
      "pgvector": "0.8.3",
      "postgresql": "17.10"
    },
    "surrealdb-d1024-n100000": {
      "storage": "RocksDB",
      "surrealdb": "surrealdb-3.2.1"
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
