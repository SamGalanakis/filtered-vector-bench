"""Engine adapter contract and shared launch helpers."""

from __future__ import annotations

import abc
import os
import resource
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from numpy.typing import NDArray


Row = tuple[int, str, NDArray[np.float32]]


@dataclass(frozen=True)
class PhaseStats:
    """Timing and storage statistics returned by load/build phases."""

    seconds: float
    rows: int = 0
    disk_bytes: int = 0
    details: dict[str, object] | None = None


class Engine(abc.ABC):
    """Contract for one isolated engine cell."""

    name: str

    def __init__(self, workdir: Path, dimensions: int, timeout: int, memory_cap_bytes: int) -> None:
        self.workdir = workdir
        self.dimensions = dimensions
        self.timeout = timeout
        self.memory_cap_bytes = memory_cap_bytes

    @abc.abstractmethod
    def prepare(self) -> None:
        """Create empty storage and schema prerequisites."""

    @abc.abstractmethod
    def start(self) -> float:
        """Start the service and return seconds until ready."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Stop the service cleanly when possible."""

    @abc.abstractmethod
    def load(self, rows: Iterable[Sequence[Row]]) -> PhaseStats:
        """Load all row batches and return statistics."""

    @abc.abstractmethod
    def build_index(self) -> PhaseStats:
        """Build the vector index, or return a documented no-op."""

    @abc.abstractmethod
    def query(self, vector: NDArray[np.float32], tenant: str | None, k: int, ef: int,
              mode: str = "default") -> tuple[list[int], float]:
        """Execute one ANN query and return source IDs and client wall seconds."""

    @abc.abstractmethod
    def explain(self, vector: NDArray[np.float32], tenant: str | None, k: int, ef: int,
                mode: str = "default") -> str:
        """Return the engine plan for the exact benchmark query."""

    @abc.abstractmethod
    def plan_uses_index(self, plan: str) -> bool:
        """Return whether the captured plan uses the vector index."""

    @abc.abstractmethod
    def version(self) -> dict[str, str]:
        """Return server and extension versions."""

    @abc.abstractmethod
    def process_roots(self) -> list[int]:
        """Return host process IDs at the roots of the engine process tree."""

    @abc.abstractmethod
    def disk_bytes(self) -> int:
        """Return durable storage bytes for this cell."""

    def churn_once(self, operation: str, source_id: int, tenant: str,
                   vector: NDArray[np.float32]) -> None:
        """Apply one mutation; adapters may override when churn is supported."""
        raise NotImplementedError(f"{self.name} does not implement churn")

    def alive(self) -> bool:
        """Return whether at least one reported root process still exists."""
        return any(Path(f"/proc/{pid}").exists() for pid in self.process_roots())

    def limited_command(self, command: list[str]) -> tuple[list[str], object | None]:
        """Wrap a local command in MemoryMax, with RLIMIT_AS as fallback."""
        if shutil.which("systemd-run"):
            probe = subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "true"],
                                   capture_output=True)
            if probe.returncode == 0:
                unit = f"fvb-{self.name}-{uuid.uuid4().hex[:10]}.scope"
                return (["systemd-run", "--user", "--scope", "--quiet", "--unit", unit,
                         "-p", f"MemoryMax={self.memory_cap_bytes}", *command], None)

        cap = self.memory_cap_bytes
        def set_limit() -> None:
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        return command, set_limit


def directory_size(path: Path) -> int:
    """Return recursive allocated file sizes, ignoring files that disappear."""
    total = 0
    if not path.exists():
        return 0
    for root, _, files in os.walk(path):
        for filename in files:
            try:
                total += (Path(root) / filename).stat().st_size
            except FileNotFoundError:
                continue
    return total

