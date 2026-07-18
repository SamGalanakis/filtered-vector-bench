"""Configuration loading and strict validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ChurnConfig:
    """Optional mixed mutation workload."""

    enabled: bool
    seconds: int
    target_ops_per_second: int


@dataclass(frozen=True)
class EngineConfig:
    """Engine launch configuration."""

    mode: str
    image: str | None = None
    version: str | None = None
    binary: str | None = None


@dataclass(frozen=True)
class BenchmarkConfig:
    """Validated benchmark matrix and workload parameters."""

    seed: int
    dimensions: tuple[int, ...]
    scales: tuple[int, ...]
    selectivities: tuple[float, ...]
    ef_values: tuple[int, ...]
    n_queries: int
    k: int
    clusters: int
    cluster_sigma: float
    batch_size: int
    settle_seconds: int
    client_timeout_seconds: int
    memory_cap_gib: float
    data_chunk_rows: int
    ground_truth_batch_rows: int
    postgres_modes: tuple[str, ...]
    churn: ChurnConfig
    engines: dict[str, EngineConfig]

    @property
    def memory_cap_bytes(self) -> int:
        """Return the configured cap in bytes."""
        return int(self.memory_cap_gib * 1024**3)

    def normalized(self) -> dict[str, Any]:
        """Return a JSON-serializable normalized representation."""
        return asdict(self)

    def sha256(self) -> str:
        """Return the stable hash of the normalized configuration."""
        raw = json.dumps(self.normalized(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


_TOP_KEYS = {
    "seed", "dimensions", "scales", "selectivities", "ef_values", "n_queries", "k",
    "clusters", "cluster_sigma", "batch_size", "settle_seconds", "client_timeout_seconds",
    "memory_cap_gib", "data_chunk_rows", "ground_truth_batch_rows", "postgres_modes", "churn",
    "engines",
}


def _positive(value: Any, name: str, *, allow_float: bool = False) -> int | float:
    kind = (int, float) if allow_float else int
    if isinstance(value, bool) or not isinstance(value, kind) or value <= 0:
        raise ValueError(f"{name} must be a positive {'number' if allow_float else 'integer'}")
    return float(value) if allow_float else int(value)


def _engine(name: str, raw: Any) -> EngineConfig:
    if not isinstance(raw, dict):
        raise ValueError(f"engines.{name} must be a mapping")
    unknown = set(raw) - {"mode", "image", "version", "binary"}
    if unknown:
        raise ValueError(f"unknown engines.{name} keys: {sorted(unknown)}")
    mode = raw.get("mode")
    allowed = {"docker", "binary"} if name == "surrealdb" else {"docker", "local"}
    if mode not in allowed:
        raise ValueError(f"engines.{name}.mode must be one of {sorted(allowed)}")
    if mode == "docker" and not raw.get("image"):
        raise ValueError(f"engines.{name}.image is required for Docker mode")
    return EngineConfig(mode=mode, image=raw.get("image"), version=raw.get("version"),
                        binary=raw.get("binary"))


def load_config(path: Path) -> BenchmarkConfig:
    """Load and validate a benchmark YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("configuration root must be a mapping")
    missing = _TOP_KEYS - set(raw)
    unknown = set(raw) - _TOP_KEYS
    if missing or unknown:
        raise ValueError(f"configuration keys: missing={sorted(missing)}, unknown={sorted(unknown)}")

    dimensions = tuple(raw["dimensions"])
    scales = tuple(raw["scales"])
    selectivities = tuple(float(v) for v in raw["selectivities"])
    ef_values = tuple(raw["ef_values"])
    if not dimensions or any(not isinstance(v, int) or v <= 0 for v in dimensions):
        raise ValueError("dimensions must contain positive integers")
    if not scales or any(not isinstance(v, int) or v <= 0 for v in scales):
        raise ValueError("scales must contain positive integers")
    if tuple(sorted(set(scales))) != scales:
        raise ValueError("scales must be unique and ascending")
    if not selectivities or 1.0 not in selectivities or any(v <= 0 or v > 1 for v in selectivities):
        raise ValueError("selectivities must be in (0, 1] and include 1.0")
    filtered_sum = sum(v for v in selectivities if v < 1)
    if filtered_sum >= 1:
        raise ValueError("filtered selectivities must sum to less than 1 for disjoint tenants")
    if not ef_values or any(not isinstance(v, int) or v <= 0 for v in ef_values):
        raise ValueError("ef_values must contain positive integers")
    if raw["k"] != 10:
        raise ValueError("k must be 10 because the report contract is recall@10")
    modes = tuple(raw["postgres_modes"])
    valid_modes = {"default", "strict_order", "relaxed_order"}
    if not modes or set(modes) - valid_modes:
        raise ValueError(f"postgres_modes must be drawn from {sorted(valid_modes)}")

    churn_raw = raw["churn"]
    if not isinstance(churn_raw, dict) or set(churn_raw) != {
        "enabled", "seconds", "target_ops_per_second"
    }:
        raise ValueError("churn requires enabled, seconds, and target_ops_per_second")
    if not isinstance(churn_raw["enabled"], bool):
        raise ValueError("churn.enabled must be boolean")
    engines_raw = raw["engines"]
    if not isinstance(engines_raw, dict) or set(engines_raw) != {"surrealdb", "postgres"}:
        raise ValueError("engines must define exactly surrealdb and postgres")

    return BenchmarkConfig(
        seed=int(raw["seed"]), dimensions=dimensions, scales=scales,
        selectivities=selectivities, ef_values=ef_values,
        n_queries=int(_positive(raw["n_queries"], "n_queries")),
        k=int(_positive(raw["k"], "k")), clusters=int(_positive(raw["clusters"], "clusters")),
        cluster_sigma=float(_positive(raw["cluster_sigma"], "cluster_sigma", allow_float=True)),
        batch_size=int(_positive(raw["batch_size"], "batch_size")),
        settle_seconds=int(_positive(raw["settle_seconds"], "settle_seconds")),
        client_timeout_seconds=int(_positive(raw["client_timeout_seconds"], "client_timeout_seconds")),
        memory_cap_gib=float(_positive(raw["memory_cap_gib"], "memory_cap_gib", allow_float=True)),
        data_chunk_rows=int(_positive(raw["data_chunk_rows"], "data_chunk_rows")),
        ground_truth_batch_rows=int(_positive(raw["ground_truth_batch_rows"], "ground_truth_batch_rows")),
        postgres_modes=modes,
        churn=ChurnConfig(churn_raw["enabled"], int(_positive(churn_raw["seconds"], "churn.seconds")),
                          int(_positive(churn_raw["target_ops_per_second"], "churn.target_ops_per_second"))),
        engines={name: _engine(name, value) for name, value in engines_raw.items()},
    )
