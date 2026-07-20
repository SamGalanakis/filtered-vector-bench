"""Background Linux process-tree RSS/PSS sampling."""

from __future__ import annotations

import csv
import json
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
                 cadence_seconds: float = 2.0,
                 groups: Callable[[], dict[str, list[int]]] | None = None) -> None:
        self.path = path
        self.roots = roots
        self.phase = phase
        self.cadence_seconds = cadence_seconds
        self.groups = groups
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._peaks: dict[str, tuple[int, int]] = {}
        self._group_peaks: dict[str, dict[str, tuple[int, int]]] = {}

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

    def peak_group_bytes(self, group: str,
                         phase_prefix: str | None = None) -> tuple[int, int]:
        """Return peak RSS/PSS for one separately sampled process group."""
        with self._write_lock:
            samples = [groups[group] for phase, groups in self._group_peaks.items()
                       if group in groups and
                       (phase_prefix is None or phase.startswith(phase_prefix))]
        return (max((value[0] for value in samples), default=0),
                max((value[1] for value in samples), default=0))

    def _run(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.cadence_seconds)

    def _sample(self) -> None:
        sampled_groups: dict[str, tuple[int, int, set[int]]] = {}
        if self.groups is not None:
            sampled_groups = {
                name: process_tree_memory_bytes(roots)
                for name, roots in self.groups().items()
            }
            rss = sum(value[0] for value in sampled_groups.values())
            pss = sum(value[1] for value in sampled_groups.values())
            pids = set().union(*(value[2] for value in sampled_groups.values()))
        else:
            rss, pss, pids = process_tree_memory_bytes(self.roots())
        phase = self.phase()
        with self._write_lock:
            old_rss, old_pss = self._peaks.get(phase, (0, 0))
            self._peaks[phase] = (max(old_rss, rss), max(old_pss, pss))
            phase_group_peaks = self._group_peaks.setdefault(phase, {})
            for name, (group_rss, group_pss, _) in sampled_groups.items():
                old_group_rss, old_group_pss = phase_group_peaks.get(name, (0, 0))
                phase_group_peaks[name] = (
                    max(old_group_rss, group_rss), max(old_group_pss, group_pss)
                )
            exists = self.path.exists() and self.path.stat().st_size > 0
            with self.path.open("a", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=(
                    "unix_time", "monotonic_seconds", "phase", "pids", "rss_bytes", "pss_bytes",
                    "surrealdb_pids", "surrealdb_rss_bytes", "surrealdb_pss_bytes",
                    "tikv_pd_pids", "tikv_pd_rss_bytes", "tikv_pd_pss_bytes", "process_groups_json",
                ))
                if not exists:
                    writer.writeheader()
                writer.writerow({"unix_time": time.time(), "monotonic_seconds": time.monotonic(),
                                 "phase": phase, "pids": ";".join(map(str, sorted(pids))),
                                 "rss_bytes": rss, "pss_bytes": pss,
                                 "surrealdb_pids": ";".join(map(str, sorted(
                                     sampled_groups.get("surrealdb", (0, 0, set()))[2]
                                 ))),
                                 "surrealdb_rss_bytes": sampled_groups.get(
                                     "surrealdb", (0, 0, set())
                                 )[0],
                                 "surrealdb_pss_bytes": sampled_groups.get(
                                     "surrealdb", (0, 0, set())
                                 )[1],
                                 "tikv_pd_pids": ";".join(map(str, sorted(
                                     sampled_groups.get("tikv_pd", (0, 0, set()))[2]
                                 ))),
                                 "tikv_pd_rss_bytes": sampled_groups.get(
                                     "tikv_pd", (0, 0, set())
                                 )[0],
                                 "tikv_pd_pss_bytes": sampled_groups.get(
                                     "tikv_pd", (0, 0, set())
                                 )[1],
                                 "process_groups_json": json.dumps({
                                     name: {"pids": sorted(value[2]), "rss_bytes": value[0],
                                            "pss_bytes": value[1]}
                                     for name, value in sampled_groups.items()
                                 }, sort_keys=True)})
