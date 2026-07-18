"""Result aggregation, publication charts, and Markdown summary generation."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as PlotPath


COLORS = {"surrealdb": "#2a78d6", "postgres": "#008300"}
DISPLAY = {"surrealdb": "SurrealDB", "postgres": "PostgreSQL"}
FAILURE = "#e34948"
EF_STYLES = {40: "-", 64: "--"}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _engine(cell_id: str) -> str:
    return cell_id.split("-d", 1)[0]


def _cell_parts(cell_id: str) -> tuple[str, int, int]:
    engine, rest = cell_id.split("-d", 1)
    dimensions, n_docs = rest.split("-n", 1)
    return engine, int(dimensions), int(n_docs)


def _number(value: float | None) -> str:
    return "—" if value is None else f"{value:,.3f}"


def _apply_style(axis: Axes, title: str, xlabel: str, ylabel: str) -> None:
    axis.set_facecolor("#ffffff")
    axis.set_title(title, color="#1a1d23", fontsize=13)
    axis.set_xlabel(xlabel, color="#6b7280", fontsize=11)
    axis.set_ylabel(ylabel, color="#6b7280", fontsize=11)
    axis.tick_params(colors="#6b7280", labelsize=11)
    axis.grid(True, color="#e5e7eb", linewidth=0.8)
    axis.set_axisbelow(True)
    for spine in axis.spines.values():
        spine.set_color("#e5e7eb")


def _save(figure: Figure, charts: Path, name: str) -> None:
    figure.patch.set_facecolor("#ffffff")
    figure.tight_layout()
    for extension in ("png", "svg"):
        figure.savefig(charts / f"{name}.{extension}", dpi=180, bbox_inches="tight",
                       facecolor="#ffffff")
    plt.close(figure)


def _rounded_bar(axis: Axes, center: float, width: float, value: float, color: str,
                 radius_x: float, radius_y: float) -> None:
    """Draw a bar with only its outer corners rounded."""
    left, right = center - width / 2, center + width / 2
    radius_y = min(radius_y, abs(value) / 2)
    if value > 0:
        vertices = [(left, 0), (right, 0), (right, value - radius_y),
                    (right, value), (right - radius_x, value), (left + radius_x, value),
                    (left, value), (left, value - radius_y), (left, 0)]
    else:
        vertices = [(left, 0), (right, 0), (right, value + radius_y),
                    (right, value), (right - radius_x, value), (left + radius_x, value),
                    (left, value), (left, value + radius_y), (left, 0)]
    codes = [PlotPath.MOVETO, PlotPath.LINETO, PlotPath.LINETO,
             PlotPath.CURVE3, PlotPath.CURVE3, PlotPath.LINETO,
             PlotPath.CURVE3, PlotPath.CURVE3, PlotPath.CLOSEPOLY]
    axis.add_patch(PathPatch(PlotPath(vertices, codes), facecolor=color, edgecolor="none"))


def _series_label(row: dict[str, Any]) -> str:
    base = DISPLAY[_engine(row["cell_id"])]
    mode = row.get("mode", "default")
    return base if mode == "default" else f"{base} {mode}"


def _plot_series(axis: Axes, rows: list[dict[str, Any]], value: str) -> None:
    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(_engine(row["cell_id"]), int(row["ef"]), row.get("mode", "default"))].append(row)
    series = sorted(grouped.items())
    for series_index, ((engine, ef, mode), points) in enumerate(series):
        points.sort(key=lambda item: float(item["selectivity"]), reverse=True)
        x = [100 * float(item["selectivity"]) for item in points]
        y = [float(item[value]) for item in points]
        label = f"{DISPLAY[engine]} ef={ef}" + ("" if mode == "default" else f" {mode}")
        axis.plot(x, y, color=COLORS[engine], linestyle=EF_STYLES.get(ef, "-."),
                  linewidth=2, marker="o", markersize=8, label=label)
        if x and math.isfinite(y[-1]):
            vertical_offset = (series_index - (len(series) - 1) / 2) * 11
            axis.annotate(label, (x[-1], y[-1]), xytext=(5, vertical_offset),
                          textcoords="offset points",
                          color=COLORS[engine], fontsize=8, va="center")


def _selectivity_figures(suites: list[dict[str, Any]], charts: Path) -> None:
    pre = [row for row in suites if row.get("label") == "pre_churn"]
    dimensions = sorted({_cell_parts(row["cell_id"])[1] for row in pre})
    for dimension in dimensions:
        scales = sorted({_cell_parts(row["cell_id"])[2] for row in pre
                         if _cell_parts(row["cell_id"])[1] == dimension})
        figure, axes = plt.subplots(1, len(scales), figsize=(6.5 * len(scales), 4.8), squeeze=False)
        for axis, n_docs in zip(axes[0], scales):
            rows = [row for row in pre if _cell_parts(row["cell_id"])[1:] == (dimension, n_docs)]
            _plot_series(axis, rows, "mean_recall_at_10")
            _apply_style(axis, f"{n_docs:,} vectors", "Eligible corpus (%)", "Recall@10")
            axis.set_xscale("log")
            axis.invert_xaxis()
            axis.set_ylim(-0.02, 1.02)
            axis.legend(frameon=False, fontsize=8)
        _save(figure, charts, f"recall-vs-selectivity-d{dimension}")

        figure, axes = plt.subplots(2, len(scales), figsize=(6.5 * len(scales), 8.5), squeeze=False)
        for column, n_docs in enumerate(scales):
            rows = [row for row in pre if _cell_parts(row["cell_id"])[1:] == (dimension, n_docs)]
            for axis, field, percentile in ((axes[0, column], "p50_seconds", "p50"),
                                             (axes[1, column], "p95_seconds", "p95")):
                _plot_series(axis, rows, field)
                _apply_style(axis, f"{percentile} · {n_docs:,} vectors",
                             "Eligible corpus (%)", "Latency (seconds)")
                axis.set_xscale("log")
                axis.invert_xaxis()
                axis.set_yscale("log")
                axis.legend(frameon=False, fontsize=8)
        _save(figure, charts, f"latency-vs-selectivity-d{dimension}")

        figure, axes = plt.subplots(1, len(scales), figsize=(6.5 * len(scales), 4.8), squeeze=False)
        for axis, n_docs in zip(axes[0], scales):
            rows = [row for row in pre if _cell_parts(row["cell_id"])[1:] == (dimension, n_docs)]
            _plot_series(axis, rows, "underfill_percent")
            _apply_style(axis, f"{n_docs:,} vectors", "Eligible corpus (%)", "Underfill (%)")
            axis.set_xscale("log")
            axis.invert_xaxis()
            axis.set_ylim(bottom=0)
            axis.legend(frameon=False, fontsize=8)
        _save(figure, charts, f"underfill-vs-selectivity-d{dimension}")


def _memory_peaks(results: Path) -> dict[str, dict[str, float]]:
    peaks: dict[str, dict[str, float]] = {}
    for memory_file in (results / "cells").glob("*/memory.csv") if (results / "cells").exists() else []:
        cell_id = memory_file.parent.name
        peak_rss = peak_pss = 0.0
        with memory_file.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if "queries" in row["phase"] or row["phase"] == "churn":
                    peak_rss = max(peak_rss, float(row["rss_bytes"]))
                    peak_pss = max(peak_pss, float(row["pss_bytes"]))
        peaks[cell_id] = {"rss": peak_rss, "pss": peak_pss or peak_rss}
    return peaks


def _scale_charts(events: list[dict[str, Any]], results: Path, charts: Path) -> None:
    loads = {row["cell_id"]: row for row in events if row["event"] == "load_complete"}
    colds: dict[str, list[float]] = defaultdict(list)
    for row in events:
        if row["event"] == "cold_open":
            colds[row["cell_id"]].append(float(row["time_to_first_query_seconds"]))
    outcomes = {row["cell_id"]: row for row in events if row["event"] == "cell_complete"}
    peaks = _memory_peaks(results)
    cells = set(loads) | set(outcomes) | set(peaks)
    dimensions = sorted({_cell_parts(cell)[1] for cell in cells})
    for dimension in dimensions:
        dimension_cells = [cell for cell in cells if _cell_parts(cell)[1] == dimension]
        figure, axis = plt.subplots(figsize=(7.5, 5))
        for engine in COLORS:
            points = sorted(((_cell_parts(cell)[2], peaks[cell]["pss"] / 1024**3)
                             for cell in dimension_cells if _engine(cell) == engine and cell in peaks))
            if points:
                axis.plot(*zip(*points), color=COLORS[engine], linewidth=2, marker="o", markersize=8,
                          label=DISPLAY[engine])
                axis.annotate(DISPLAY[engine], points[-1], xytext=(5, 0), textcoords="offset points",
                              color=COLORS[engine], va="center")
        for cell, row in outcomes.items():
            engine, dims, n_docs = _cell_parts(cell)
            if dims == dimension and row.get("outcome") == "exceeded_memory_cap":
                cap = float(row["memory_cap_bytes"]) / 1024**3
                axis.scatter([n_docs], [cap], color=FAILURE, marker="x", s=90, linewidths=2, zorder=5)
                axis.annotate("exceeded cap", (n_docs, cap), xytext=(5, 5), textcoords="offset points",
                              color=FAILURE, fontsize=9)
        _apply_style(axis, "Peak query-phase process-tree memory", "Vectors",
                     "PSS (GiB; RSS fallback)")
        axis.set_xscale("log")
        axis.legend(frameon=False)
        _save(figure, charts, f"memory-vs-scale-d{dimension}")

        figure, axis = plt.subplots(figsize=(7.5, 5))
        for engine in COLORS:
            points = sorted(((_cell_parts(cell)[2], float(np.median(colds[cell])))
                             for cell in colds if _engine(cell) == engine and
                             _cell_parts(cell)[1] == dimension))
            if points:
                axis.plot(*zip(*points), color=COLORS[engine], linewidth=2, marker="o", markersize=8,
                          label=DISPLAY[engine])
                axis.annotate(DISPLAY[engine], points[-1], xytext=(5, 0), textcoords="offset points",
                              color=COLORS[engine], va="center")
        _apply_style(axis, "Time to first query after restart", "Vectors", "Seconds")
        axis.set_xscale("log")
        axis.set_yscale("log")
        axis.legend(frameon=False)
        _save(figure, charts, f"cold-open-vs-scale-d{dimension}")

        figure, axes = plt.subplots(1, 2, figsize=(13, 5))
        for axis, field, ylabel, title in (
            (axes[0], "rows_per_second", "Rows / second", "Durable load throughput"),
            (axes[1], "time_to_queryable_seconds", "Seconds", "Total time to queryable"),
        ):
            for engine in COLORS:
                points = sorted(((_cell_parts(cell)[2], float(row[field])) for cell, row in loads.items()
                                 if _engine(cell) == engine and _cell_parts(cell)[1] == dimension))
                if points:
                    axis.plot(*zip(*points), color=COLORS[engine], linewidth=2, marker="o", markersize=8,
                              label=DISPLAY[engine])
                    axis.annotate(DISPLAY[engine], points[-1], xytext=(5, 0), textcoords="offset points",
                                  color=COLORS[engine], va="center")
            _apply_style(axis, title, "Vectors", ylabel)
            axis.set_xscale("log")
            axis.legend(frameon=False)
        _save(figure, charts, f"load-vs-scale-d{dimension}")


def _churn_charts(suites: list[dict[str, Any]], results: Path, charts: Path) -> None:
    post = [row for row in suites if row.get("label") == "post_churn"]
    if not post:
        return
    cells = sorted({row["cell_id"] for row in post})
    memory_series: dict[tuple[int, int], list[tuple[str, list[dict[str, str]]]]] = defaultdict(list)
    for cell_id in cells:
        memory_file = results / "cells" / cell_id / "memory.csv"
        if not memory_file.exists():
            continue
        rows = [row for row in csv.DictReader(memory_file.open(encoding="utf-8"))
                if row["phase"] == "churn"]
        if not rows:
            continue
        engine, dimension, n_docs = _cell_parts(cell_id)
        memory_series[(dimension, n_docs)].append((engine, rows))
    for (dimension, n_docs), series in sorted(memory_series.items()):
        figure, axis = plt.subplots(figsize=(7.5, 5))
        for engine, rows in sorted(series):
            start = float(rows[0]["monotonic_seconds"])
            x = [float(row["monotonic_seconds"]) - start for row in rows]
            y = [(float(row["pss_bytes"]) or float(row["rss_bytes"])) / 1024**3
                 for row in rows]
            axis.plot(x, y, color=COLORS[engine], linewidth=2, marker="o", markersize=8,
                      label=DISPLAY[engine])
            axis.annotate(DISPLAY[engine], (x[-1], y[-1]), xytext=(5, 0),
                          textcoords="offset points", color=COLORS[engine], va="center")
        _apply_style(axis, f"Churn memory · {n_docs:,} × {dimension}", "Elapsed seconds",
                     "PSS (GiB; RSS fallback)")
        axis.legend(frameon=False)
        _save(figure, charts, f"churn-memory-d{dimension}-n{n_docs}")

    pre_map = {(row["cell_id"], row["selectivity"], row["ef"], row["mode"]): row
               for row in suites if row.get("label") == "pre_churn"}
    deltas: dict[tuple[str, float], list[float]] = defaultdict(list)
    for row in post:
        key = (row["cell_id"], row["selectivity"], row["ef"], row["mode"])
        if key in pre_map:
            deltas[(_engine(row["cell_id"]), float(row["selectivity"]))].append(
                float(row["mean_recall_at_10"]) - float(pre_map[key]["mean_recall_at_10"]))
    selectivities = sorted({key[1] for key in deltas}, reverse=True)
    figure, axis = plt.subplots(figsize=(8, 5))
    positions = np.arange(len(selectivities))
    plotted = {(engine, selectivity): float(np.mean(deltas.get((engine, selectivity), [0.0])))
               for engine in COLORS for selectivity in selectivities}
    limit = max(max((abs(value) for value in plotted.values()), default=0) * 1.35, 0.01)
    axis.set_xlim(-0.6, len(selectivities) - 0.4)
    axis.set_ylim(-limit, limit)
    axis.set_xticks(positions, [f"{100 * value:g}%" for value in selectivities])
    axis.axhline(0, color="#6b7280", linewidth=0.8)
    _apply_style(axis, "Recall delta after churn", "Eligible corpus", "Post − pre recall@10")
    figure.canvas.draw()
    x_span = len(selectivities) + 0.2
    gap = 2 * x_span / axis.bbox.width
    group_width = 0.72
    bar_width = (group_width - gap) / 2
    radius_x = 4 * x_span / axis.bbox.width
    radius_y = 4 * (2 * limit) / axis.bbox.height
    for engine_index, engine in enumerate(COLORS):
        offset = (engine_index - 0.5) * (bar_width + gap)
        for position, selectivity in zip(positions, selectivities):
            center = float(position + offset)
            value = plotted[(engine, selectivity)]
            if value != 0:
                _rounded_bar(axis, center, bar_width, value, COLORS[engine], radius_x, radius_y)
            label_y = value + math.copysign(limit * 0.035, value or 1)
            axis.text(center, label_y, f"{value:+.3f}", ha="center",
                      va="bottom" if value >= 0 else "top", fontsize=8, color="#1a1d23")
    axis.legend(handles=[Patch(facecolor=COLORS[engine], label=DISPLAY[engine])
                         for engine in COLORS], frameon=False)
    _save(figure, charts, "churn-recall-delta")


def _markdown(events: list[dict[str, Any]], suites: list[dict[str, Any]], results: Path,
              peaks: dict[str, dict[str, float]]) -> str:
    metadata = json.loads((results / "metadata.json").read_text(encoding="utf-8"))
    versions = {row["cell_id"]: row["versions"] for row in events if row["event"] == "engine_versions"}
    loads = {row["cell_id"]: row for row in events if row["event"] == "load_complete"}
    outcomes = {row["cell_id"]: row for row in events if row["event"] == "cell_complete"}
    colds: dict[str, list[float]] = defaultdict(list)
    for row in events:
        if row["event"] == "cold_open":
            colds[row["cell_id"]].append(float(row["time_to_first_query_seconds"]))
    lines = ["# Benchmark summary", "", f"Config SHA-256: `{metadata['config_sha256']}`  ",
             f"Host: `{metadata['hostname']}` · `{metadata['platform']}` · Python `{metadata['python']}`",
             "", "## Cell overview", "",
             "| Engine | Dims | Vectors | Outcome | Version | Load rows/s | Queryable s | Peak PSS/RSS GiB | Cold first-query s |",
             "|---|---:|---:|---|---|---:|---:|---:|---:|"]
    cell_ids = sorted(set(loads) | set(outcomes), key=lambda cell: _cell_parts(cell)[1:])
    for cell in cell_ids:
        engine, dimensions, n_docs = _cell_parts(cell)
        load = loads.get(cell, {})
        outcome = outcomes.get(cell, {}).get("outcome", "incomplete")
        version = ", ".join(f"{key} {value}" for key, value in versions.get(cell, {}).items()) or "—"
        rows_per_second = load.get("rows_per_second")
        queryable = load.get("time_to_queryable_seconds")
        pss = peaks.get(cell, {}).get("pss")
        cold = float(np.median(colds[cell])) if cell in colds else None
        lines.append(f"| {DISPLAY[engine]} | {dimensions} | {n_docs:,} | {outcome} | {version} | "
                     f"{_number(rows_per_second)} | {_number(queryable)} | "
                     f"{_number(pss / 1024**3 if pss else None)} | {_number(cold)} |")
    lines += ["", "## Filtered suites", "",
              "| Engine | Dims | Vectors | Stage | Selectivity | ef | Mode | Index plan | Recall@10 | p50 ms | p95 ms | Underfill |",
              "|---|---:|---:|---|---:|---:|---|---|---:|---:|---:|---:|"]
    for row in sorted(suites, key=lambda item: (item["cell_id"], item["label"],
                                                -float(item["selectivity"]), item["ef"], item["mode"])):
        engine, dimensions, n_docs = _cell_parts(row["cell_id"])
        gate = "yes" if row["uses_vector_index"] else "**NO**"
        lines.append(f"| {DISPLAY[engine]} | {dimensions} | {n_docs:,} | {row['label']} | "
                     f"{100 * float(row['selectivity']):g}% | {row['ef']} | {row['mode']} | {gate} | "
                     f"{float(row['mean_recall_at_10']):.4f} | {1000 * float(row['p50_seconds']):.3f} | "
                     f"{1000 * float(row['p95_seconds']):.3f} | {float(row['underfill_percent']):.2f}% |")
    lines += ["", "## Metadata", "", "```json",
              json.dumps({"config_sha256": metadata["config_sha256"], "versions": versions,
                          "hardware_files": ["lscpu.txt", "meminfo.txt"]}, indent=2, sort_keys=True),
              "```", "", "Raw plans, per-query observations, and phase memory samples remain beside this report.", ""]
    return "\n".join(lines)


def generate_report(results: Path) -> None:
    """Generate all available charts and the Markdown summary from raw files."""
    if not (results / "metadata.json").exists():
        raise FileNotFoundError(f"not a benchmark result directory: {results}")
    charts = results / "charts"
    charts.mkdir(exist_ok=True)
    for pattern in ("*.png", "*.svg"):
        for old_chart in charts.glob(pattern):
            old_chart.unlink()
    events = _jsonl(results / "events.jsonl")
    suites = [row for row in events if row["event"] == "suite_complete"]
    _selectivity_figures(suites, charts)
    _scale_charts(events, results, charts)
    _churn_charts(suites, results, charts)
    peaks = _memory_peaks(results)
    (results / "summary.md").write_text(_markdown(events, suites, results, peaks), encoding="utf-8")
