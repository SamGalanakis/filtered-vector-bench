"""Background Linux process-tree RSS/PSS sampling."""

from __future__ import annotations

import csv
import threading
import time
from pathlib import Path
from typing import Callable


def _children(pid: int) -> set[int]:
    found = {pid}
    changed = True
    while changed:
        changed = False
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit() or int(entry.name) in found:
                continue
            try:
                fields = (entry / "stat").read_text().split()
                parent = int(fields[3])
            except (FileNotFoundError, PermissionError, ProcessLookupError, IndexError, ValueError):
                continue
            if parent in found:
                found.add(int(entry.name))
                changed = True
    return found


def _kib(pid: int, filename: str, key: str) -> int:
    try:
        for line in Path(f"/proc/{pid}/{filename}").read_text().splitlines():
            if line.startswith(key + ":"):
                return int(line.split()[1])
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        pass
    return 0


def process_tree_memory_bytes(roots: list[int]) -> tuple[int, int, set[int]]:
    """Return summed RSS/PSS bytes and PIDs for the supplied process trees."""
    pids: set[int] = set()
    for root in roots:
        if root > 0 and Path(f"/proc/{root}").exists():
            pids.update(_children(root))
    rss = sum(_kib(pid, "status", "VmRSS") for pid in pids) * 1024
    pss = sum(_kib(pid, "smaps_rollup", "Pss") for pid in pids) * 1024
    return rss, pss, pids


class MemorySampler:
    """Sample summed process-tree memory to a phase-labeled CSV."""

    def __init__(self, path: Path, roots: Callable[[], list[int]], phase: Callable[[], str],
                 cadence_seconds: float = 2.0) -> None:
        self.path = path
        self.roots = roots
        self.phase = phase
        self.cadence_seconds = cadence_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._peaks: dict[str, tuple[int, int]] = {}

    def start(self) -> None:
        """Start sampling in a daemon thread."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, name="memory-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop sampling and flush the CSV."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.cadence_seconds + 2)

    def sample_now(self) -> None:
        """Capture a phase-boundary sample in addition to the fixed cadence."""
        self._sample()

    def peak_bytes(self, phase_prefix: str | None = None) -> tuple[int, int]:
        """Return peak summed RSS and PSS, optionally restricted to a phase prefix."""
        with self._write_lock:
            samples = [value for phase, value in self._peaks.items()
                       if phase_prefix is None or phase.startswith(phase_prefix)]
        return (max((value[0] for value in samples), default=0),
                max((value[1] for value in samples), default=0))

    def _run(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.cadence_seconds)

    def _sample(self) -> None:
        rss, pss, pids = process_tree_memory_bytes(self.roots())
        phase = self.phase()
        with self._write_lock:
            old_rss, old_pss = self._peaks.get(phase, (0, 0))
            self._peaks[phase] = (max(old_rss, rss), max(old_pss, pss))
            exists = self.path.exists() and self.path.stat().st_size > 0
            with self.path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=(
                    "unix_time", "monotonic_seconds", "phase", "pids", "rss_bytes", "pss_bytes"
                ))
                if not exists:
                    writer.writeheader()
                writer.writerow({"unix_time": time.time(), "monotonic_seconds": time.monotonic(),
                                 "phase": phase, "pids": ";".join(map(str, sorted(pids))),
                                 "rss_bytes": rss, "pss_bytes": pss})
