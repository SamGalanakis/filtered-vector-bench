"""Result aggregation, publication charts, and Markdown summary generation."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as PlotPath


COLORS = {"surrealdb": "#2a78d6", "postgres": "#008300"}
DISPLAY = {"surrealdb": "SurrealDB", "postgres": "PostgreSQL"}
FAILURE = "#e34948"
EF_STYLES: dict[int, Literal["-", "--"]] = {40: "-", 64: "--"}
MODE_MARKERS = {"default": "o", "strict_order": "s", "relaxed_order": "^"}


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


def _relevant_pool_summary(row: dict[str, Any]) -> str:
    minimum = row.get("min_eligible_relevant_pool_size")
    mean = row.get("mean_eligible_relevant_pool_size")
    maximum = row.get("max_eligible_relevant_pool_size")
    if minimum is None or mean is None or maximum is None:
        return "—"
    return f"{int(minimum)}/{float(mean):.1f}/{int(maximum)}"


def _normalized_suite(row: dict[str, Any]) -> dict[str, Any]:
    """Read both the current self-describing suite schema and historical events."""
    normalized = dict(row)
    selectivity = float(normalized["selectivity"])
    normalized.setdefault("tier", "unfiltered" if selectivity == 1.0 else
                          f"tenant_s{format(selectivity, '.8g').replace('.', '_')}")
    normalized.setdefault("p50_ms", 1000 * float(normalized.get("p50_seconds", 0.0)))
    normalized.setdefault("p95_ms", 1000 * float(normalized.get("p95_seconds", 0.0)))
    normalized.setdefault("underfill", round(
        float(normalized.get("underfill_percent", 0.0)) * int(normalized.get("n_queries", 0)) / 100
    ))
    normalized.setdefault("mean_result_count", None)
    normalized.setdefault("plan", "See plans.jsonl (historical event schema)")
    normalized.setdefault("plan_uses_index", normalized.get("uses_vector_index", False))
    return normalized


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
                  linewidth=2, marker=MODE_MARKERS.get(mode, "o"), markersize=8,
                  label="_nolegend_")
        if len(series) <= 4 and x and math.isfinite(y[-1]):
            vertical_offset = (series_index - (len(series) - 1) / 2) * 11
            axis.annotate(label, (x[-1], y[-1]), xytext=(5, vertical_offset),
                          textcoords="offset points",
                          color=COLORS[engine], fontsize=8, va="center")


def _plot_engine_series(axis: Axes, rows: list[dict[str, Any]], value: str) -> None:
    """Plot one no-EF series per engine for the FTS suite."""
    for series_index, engine in enumerate(sorted({_engine(row["cell_id"]) for row in rows})):
        points = sorted(
            (row for row in rows if _engine(row["cell_id"]) == engine),
            key=lambda item: float(item["selectivity"]), reverse=True,
        )
        x = [100 * float(item["selectivity"]) for item in points]
        y = [float(item[value]) for item in points]
        axis.plot(x, y, color=COLORS[engine], linewidth=2, marker="o", markersize=8,
                  label=DISPLAY[engine])
        if x and math.isfinite(y[-1]):
            offset = (series_index - 0.5) * 11
            axis.annotate(DISPLAY[engine], (x[-1], y[-1]), xytext=(5, offset),
                          textcoords="offset points", color=COLORS[engine], fontsize=8,
                          va="center")


def _series_legend(axis: Axes, rows: list[dict[str, Any]]) -> None:
    """Use one compact visual-key legend instead of one entry per PG series."""
    engines = sorted({_engine(row["cell_id"]) for row in rows})
    efs = sorted({int(row["ef"]) for row in rows})
    modes = [mode for mode in MODE_MARKERS
             if any(_engine(row["cell_id"]) == "postgres" and row.get("mode") == mode
                    for row in rows)]
    handles: list[Line2D] = [
        Line2D([], [], color=COLORS[engine], linewidth=2, label=DISPLAY[engine])
        for engine in engines
    ]
    handles.extend(Line2D([], [], color="#4b5563", linestyle=EF_STYLES.get(ef, "-."),
                          linewidth=2, label=f"ef={ef}") for ef in efs)
    handles.extend(Line2D([], [], color="#4b5563", linestyle="None",
                          marker=MODE_MARKERS[mode], markersize=7,
                          label=f"PG {mode.replace('_', ' ')}") for mode in modes)
    if handles:
        axis.legend(handles=handles, frameon=False, fontsize=8, ncol=2)


def _legend_if_present(axis: Axes) -> None:
    handles, _ = axis.get_legend_handles_labels()
    if handles:
        axis.legend(frameon=False)


def _failure_text(row: dict[str, Any], engine: str) -> str:
    phase = str(row.get("failure_phase", row.get("phase", "unknown phase")))
    if row.get("outcome") == "exceeded_memory_cap":
        reason = f"exceeded memory cap during {phase}"
    else:
        reason = f"failed during {phase}"
    return f"{DISPLAY[engine]}: no data — {reason} at this scale"


def _annotate_missing(axis: Axes, rows: list[dict[str, Any]], outcomes: dict[str, dict[str, Any]],
                      dimension: int, n_docs: int, vertical_slot: int = 0) -> None:
    missing: list[str] = []
    present = {_engine(row["cell_id"]) for row in rows}
    for engine in COLORS:
        cell = f"{engine}-d{dimension}-n{n_docs}"
        outcome = outcomes.get(cell)
        if engine not in present and outcome and outcome.get("outcome") != "ok":
            missing.append(_failure_text(outcome, engine))
    for index, message in enumerate(missing):
        axis.text(0.02, 0.03 + (vertical_slot * len(COLORS) + index) * 0.07, message,
                  transform=axis.transAxes,
                  color=FAILURE, fontsize=8, va="bottom")


def _selectivity_figures(suites: list[dict[str, Any]], outcomes: dict[str, dict[str, Any]],
                         charts: Path) -> None:
    pre = [row for row in suites if row.get("label") == "pre_churn"]
    all_cells = {row["cell_id"] for row in pre} | set(outcomes)
    dimensions = sorted({_cell_parts(cell)[1] for cell in all_cells})
    for dimension in dimensions:
        scales = sorted({_cell_parts(cell)[2] for cell in all_cells
                         if _cell_parts(cell)[1] == dimension})
        figure, axes = plt.subplots(1, len(scales), figsize=(6.5 * len(scales), 4.8), squeeze=False)
        for axis, n_docs in zip(axes[0], scales):
            rows = [row for row in pre if _cell_parts(row["cell_id"])[1:] == (dimension, n_docs)]
            _plot_series(axis, rows, "mean_recall_at_10")
            _apply_style(axis, f"{n_docs:,} vectors",
                         "filter selectivity (% of corpus eligible)", "Recall@10")
            axis.set_xscale("log")
            axis.invert_xaxis()
            axis.set_ylim(-0.02, 1.02)
            _series_legend(axis, rows)
            _annotate_missing(axis, rows, outcomes, dimension, n_docs)
        _save(figure, charts, f"recall-vs-selectivity-d{dimension}")

        figure, axes = plt.subplots(2, len(scales), figsize=(6.5 * len(scales), 8.5), squeeze=False)
        for column, n_docs in enumerate(scales):
            rows = [row for row in pre if _cell_parts(row["cell_id"])[1:] == (dimension, n_docs)]
            for axis, field, percentile in ((axes[0, column], "p50_ms", "p50"),
                                             (axes[1, column], "p95_ms", "p95")):
                _plot_series(axis, rows, field)
                _apply_style(axis, f"{percentile} · {n_docs:,} vectors",
                             "filter selectivity (% of corpus eligible)", "Latency (ms)")
                axis.set_xscale("log")
                axis.invert_xaxis()
                axis.set_yscale("log")
                _series_legend(axis, rows)
                _annotate_missing(axis, rows, outcomes, dimension, n_docs)
        _save(figure, charts, f"latency-vs-selectivity-d{dimension}")

        figure, axes = plt.subplots(1, len(scales), figsize=(6.5 * len(scales), 4.8), squeeze=False)
        for axis, n_docs in zip(axes[0], scales):
            rows = [row for row in pre if _cell_parts(row["cell_id"])[1:] == (dimension, n_docs)]
            _plot_series(axis, rows, "underfill_percent")
            _apply_style(axis, f"{n_docs:,} vectors",
                         "filter selectivity (% of corpus eligible)", "Underfill (%)")
            axis.set_xscale("log")
            axis.invert_xaxis()
            axis.set_ylim(bottom=0)
            _series_legend(axis, rows)
            _annotate_missing(axis, rows, outcomes, dimension, n_docs)
        _save(figure, charts, f"underfill-vs-selectivity-d{dimension}")


def _text_figures(fts: list[dict[str, Any]], hybrid: list[dict[str, Any]],
                  outcomes: dict[str, dict[str, Any]], charts: Path) -> None:
    """Render the FTS/hybrid latency families and shared-standard nDCG panels."""
    all_cells = {row["cell_id"] for row in [*fts, *hybrid]} | set(outcomes)
    dimensions = sorted({_cell_parts(cell)[1] for cell in all_cells})
    for dimension in dimensions:
        scales = sorted({_cell_parts(cell)[2] for cell in all_cells
                         if _cell_parts(cell)[1] == dimension})
        if fts:
            figure, axes = plt.subplots(
                2, len(scales), figsize=(6.5 * len(scales), 8.5), squeeze=False
            )
            for column, n_docs in enumerate(scales):
                rows = [row for row in fts
                        if _cell_parts(row["cell_id"])[1:] == (dimension, n_docs)]
                for axis, field, percentile in (
                    (axes[0, column], "p50_ms", "p50"),
                    (axes[1, column], "p95_ms", "p95"),
                ):
                    _plot_engine_series(axis, rows, field)
                    _apply_style(axis, f"{percentile} · {n_docs:,} documents",
                                 "filter selectivity (% eligible)", "Latency (ms)")
                    axis.set_xscale("log")
                    axis.invert_xaxis()
                    axis.set_yscale("log")
                    _legend_if_present(axis)
                    _annotate_missing(axis, rows, outcomes, dimension, n_docs)
            _save(figure, charts, f"fts-latency-vs-selectivity-d{dimension}")

        if hybrid:
            figure, axes = plt.subplots(
                2, len(scales), figsize=(6.5 * len(scales), 8.5), squeeze=False
            )
            for column, n_docs in enumerate(scales):
                rows = [row for row in hybrid
                        if _cell_parts(row["cell_id"])[1:] == (dimension, n_docs)]
                for axis, field, percentile in (
                    (axes[0, column], "p50_ms", "p50"),
                    (axes[1, column], "p95_ms", "p95"),
                ):
                    _plot_series(axis, rows, field)
                    _apply_style(axis, f"{percentile} · {n_docs:,} documents",
                                 "filter selectivity (% eligible)", "Latency (ms)")
                    axis.set_xscale("log")
                    axis.invert_xaxis()
                    axis.set_yscale("log")
                    _series_legend(axis, rows)
                    _annotate_missing(axis, rows, outcomes, dimension, n_docs)
            _save(figure, charts, f"hybrid-latency-vs-selectivity-d{dimension}")

        if fts or hybrid:
            figure, axes = plt.subplots(
                2, len(scales), figsize=(6.5 * len(scales), 8.5), squeeze=False
            )
            for column, n_docs in enumerate(scales):
                fts_rows = [row for row in fts
                            if _cell_parts(row["cell_id"])[1:] == (dimension, n_docs)]
                hybrid_rows = [row for row in hybrid
                               if _cell_parts(row["cell_id"])[1:] == (dimension, n_docs)]
                _plot_engine_series(axes[0, column], fts_rows, "mean_ndcg_at_10")
                _apply_style(axes[0, column], f"FTS · {n_docs:,} documents",
                             "filter selectivity (% eligible)", "nDCG@10")
                _plot_series(axes[1, column], hybrid_rows, "mean_ndcg_at_10")
                _apply_style(axes[1, column], f"Hybrid · {n_docs:,} documents",
                             "filter selectivity (% eligible)", "nDCG@10")
                for axis, rows in ((axes[0, column], fts_rows),
                                   (axes[1, column], hybrid_rows)):
                    axis.set_xscale("log")
                    axis.invert_xaxis()
                    axis.set_ylim(-0.02, 1.02)
                    _annotate_missing(axis, rows, outcomes, dimension, n_docs)
                _legend_if_present(axes[0, column])
                _series_legend(axes[1, column], hybrid_rows)
            _save(figure, charts, f"ndcg-vs-selectivity-d{dimension}")


def _memory_peaks(results: Path) -> dict[str, dict[str, float | str]]:
    peaks: dict[str, dict[str, float | str]] = {}
    for memory_file in (results / "cells").glob("*/memory.csv") if (results / "cells").exists() else []:
        cell_id = memory_file.parent.name
        peak_rss = peak_pss = load_rss = load_pss = overall_rss = overall_pss = 0.0
        peak_phase = "unknown"
        with memory_file.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                rss = float(row["rss_bytes"])
                pss = float(row["pss_bytes"])
                if rss > overall_rss:
                    peak_phase = row["phase"]
                overall_rss = max(overall_rss, rss)
                overall_pss = max(overall_pss, pss)
                if row["phase"].startswith("load"):
                    load_rss = max(load_rss, rss)
                    load_pss = max(load_pss, pss)
                if "queries" in row["phase"] or row["phase"] == "churn":
                    peak_rss = max(peak_rss, rss)
                    peak_pss = max(peak_pss, pss)
        peaks[cell_id] = {
            "rss": peak_rss, "pss": peak_pss or peak_rss,
            "load_rss": load_rss, "load_pss": load_pss or load_rss,
            "overall_rss": overall_rss, "overall_pss": overall_pss or overall_rss,
            "peak_phase": peak_phase,
        }
    return peaks


def _phase_label(phase: str) -> str:
    if phase.startswith("load"):
        return "load"
    if phase.startswith(("pre_churn", "post_churn")):
        return "filtered_suite"
    return phase.split(":", 1)[0]


def _effective_outcomes(events: list[dict[str, Any]],
                        peaks: dict[str, dict[str, float | str]]) -> dict[str, dict[str, Any]]:
    """Upgrade historical near-cap disconnects for faithful report rendering."""
    outcomes = {row["cell_id"]: dict(row) for row in events if row["event"] == "cell_complete"}
    for cell, row in outcomes.items():
        peak = peaks.get(cell, {})
        cap = int(row.get("memory_cap_bytes", 0))
        overall_rss = float(peak.get("overall_rss", 0.0))
        near_cap = cap and abs(overall_rss - cap) <= cap * 0.05
        if row.get("outcome") == "error" and near_cap:
            row["outcome"] = "exceeded_memory_cap"
            row["failure_phase"] = _phase_label(str(peak.get("peak_phase", "unknown")))
    return outcomes


def _scale_charts(events: list[dict[str, Any]], charts: Path,
                  outcomes: dict[str, dict[str, Any]],
                  peaks: dict[str, dict[str, float | str]]) -> None:
    loads = {row["cell_id"]: row for row in events if row["event"] == "load_complete"}
    colds: dict[str, list[float]] = defaultdict(list)
    for row in events:
        if row["event"] == "cold_open":
            colds[row["cell_id"]].append(float(row["time_to_first_query_seconds"]))
    cells = set(loads) | set(outcomes) | set(peaks)
    dimensions = sorted({_cell_parts(cell)[1] for cell in cells})
    for dimension in dimensions:
        dimension_cells = [cell for cell in cells if _cell_parts(cell)[1] == dimension]
        figure, axis = plt.subplots(figsize=(7.5, 5))
        for engine_index, engine in enumerate(COLORS):
            points = sorted(((_cell_parts(cell)[2], float(peaks[cell]["pss"]) / 1024**3)
                             for cell in dimension_cells if _engine(cell) == engine and cell in peaks
                             and float(peaks[cell]["pss"]) > 0
                             and outcomes.get(cell, {}).get("outcome", "ok") == "ok"))
            if points:
                axis.plot(*zip(*points), color=COLORS[engine], linewidth=2, marker="o", markersize=8,
                          label=DISPLAY[engine])
                offset = (engine_index - (len(COLORS) - 1) / 2) * 12
                axis.annotate(DISPLAY[engine], points[-1], xytext=(5, offset),
                              textcoords="offset points",
                              color=COLORS[engine], va="center")
        for cell, row in outcomes.items():
            engine, dims, n_docs = _cell_parts(cell)
            if dims == dimension and row.get("outcome") != "ok":
                cap = float(row["memory_cap_bytes"]) / 1024**3
                axis.scatter([n_docs], [cap], color=FAILURE, marker="x", s=90, linewidths=2, zorder=5)
                phase = str(row.get("failure_phase", row.get("phase", "unknown phase")))
                label = (f"exceeded cap during {phase}" if
                         row.get("outcome") == "exceeded_memory_cap" else f"failed during {phase}")
                axis.annotate(label, (n_docs, cap), xytext=(5, 5), textcoords="offset points",
                              color=FAILURE, fontsize=9)
        _apply_style(axis, "Peak query-phase process-tree memory", "Vectors",
                     "PSS (GiB; RSS fallback)")
        axis.set_xscale("log")
        _legend_if_present(axis)
        _save(figure, charts, f"memory-vs-scale-d{dimension}")

        if any(_cell_parts(cell)[1] == dimension for cell in colds):
            figure, axis = plt.subplots(figsize=(7.5, 5))
            for engine_index, engine in enumerate(COLORS):
                points = sorted(((_cell_parts(cell)[2], float(np.median(colds[cell])))
                                 for cell in colds if _engine(cell) == engine and
                                 _cell_parts(cell)[1] == dimension and
                                 outcomes.get(cell, {}).get("outcome", "ok") == "ok"))
                if points:
                    axis.plot(*zip(*points), color=COLORS[engine], linewidth=2, marker="o",
                              markersize=8, label=DISPLAY[engine])
                    offset = (engine_index - (len(COLORS) - 1) / 2) * 12
                    axis.annotate(DISPLAY[engine], points[-1], xytext=(5, offset),
                                  textcoords="offset points",
                                  color=COLORS[engine], va="center")
            cold_rows = [{"cell_id": cell} for cell in colds
                         if _cell_parts(cell)[1] == dimension and
                         outcomes.get(cell, {}).get("outcome", "ok") == "ok"]
            for slot, n_docs in enumerate(sorted({_cell_parts(cell)[2]
                                                  for cell in dimension_cells})):
                _annotate_missing(axis, [row for row in cold_rows
                                         if _cell_parts(row["cell_id"])[2] == n_docs],
                                  outcomes, dimension, n_docs, slot)
            _apply_style(axis, "Time to first query after restart", "Vectors", "Seconds")
            axis.set_xscale("log")
            axis.set_yscale("log")
            _legend_if_present(axis)
            _save(figure, charts, f"cold-open-vs-scale-d{dimension}")

        figure, axes = plt.subplots(1, 2, figsize=(13, 5))
        for axis, field, ylabel, title in (
            (axes[0], "rows_per_second", "Rows / second", "Durable load throughput"),
            (axes[1], "time_to_queryable_seconds", "Seconds", "Total time to queryable"),
        ):
            for engine_index, engine in enumerate(COLORS):
                points = sorted(((_cell_parts(cell)[2], float(row[field])) for cell, row in loads.items()
                                 if _engine(cell) == engine and _cell_parts(cell)[1] == dimension
                                 and outcomes.get(cell, {}).get("outcome", "ok") == "ok"))
                if points:
                    axis.plot(*zip(*points), color=COLORS[engine], linewidth=2, marker="o", markersize=8,
                              label=DISPLAY[engine])
                    offset = (engine_index - (len(COLORS) - 1) / 2) * 12
                    axis.annotate(DISPLAY[engine], points[-1], xytext=(5, offset),
                                  textcoords="offset points",
                                  color=COLORS[engine], va="center")
            load_rows = [{"cell_id": cell} for cell in loads
                         if _cell_parts(cell)[1] == dimension and
                         outcomes.get(cell, {}).get("outcome", "ok") == "ok"]
            for slot, n_docs in enumerate(sorted({_cell_parts(cell)[2]
                                                  for cell in dimension_cells})):
                _annotate_missing(axis, [row for row in load_rows
                                         if _cell_parts(row["cell_id"])[2] == n_docs],
                                  outcomes, dimension, n_docs, slot)
            _apply_style(axis, title, "Vectors", ylabel)
            axis.set_xscale("log")
            _legend_if_present(axis)
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
        for series_index, (engine, rows) in enumerate(sorted(series)):
            start = float(rows[0]["monotonic_seconds"])
            x = [float(row["monotonic_seconds"]) - start for row in rows]
            y = [(float(row["pss_bytes"]) or float(row["rss_bytes"])) / 1024**3
                 for row in rows]
            axis.plot(x, y, color=COLORS[engine], linewidth=2, marker="o", markersize=8,
                      label=DISPLAY[engine])
            offset = (series_index - (len(series) - 1) / 2) * 12
            axis.annotate(DISPLAY[engine], (x[-1], y[-1]), xytext=(5, offset),
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


def _markdown(events: list[dict[str, Any]], suites: list[dict[str, Any]],
              fts: list[dict[str, Any]], hybrid: list[dict[str, Any]], results: Path,
              peaks: dict[str, dict[str, float | str]],
              outcomes: dict[str, dict[str, Any]]) -> str:
    metadata = json.loads((results / "metadata.json").read_text(encoding="utf-8"))
    versions = {row["cell_id"]: row["versions"] for row in events if row["event"] == "engine_versions"}
    loads = {row["cell_id"]: row for row in events if row["event"] == "load_complete"}
    colds: dict[str, list[float]] = defaultdict(list)
    for row in events:
        if row["event"] == "cold_open":
            colds[row["cell_id"]].append(float(row["time_to_first_query_seconds"]))
    lines = ["# Benchmark summary", "", f"Config SHA-256: `{metadata['config_sha256']}`  ",
             f"Host: `{metadata['hostname']}` · `{metadata['platform']}` · Python `{metadata['python']}`",
             "", "## Cell overview", "",
             "| Engine | Dims | Vectors | Outcome | Version | Load rows/s | Queryable s | Load peak PSS/RSS GiB | Query peak PSS/RSS GiB | Cold first-query s |",
             "|---|---:|---:|---|---|---:|---:|---:|---:|---:|"]
    cell_ids = sorted(set(loads) | set(outcomes), key=lambda cell: _cell_parts(cell)[1:])
    for cell in cell_ids:
        engine, dimensions, n_docs = _cell_parts(cell)
        load = loads.get(cell, {})
        outcome_row = outcomes.get(cell, {})
        outcome = str(outcome_row.get("outcome", "incomplete"))
        if outcome != "ok" and outcome_row.get("failure_phase"):
            outcome += f" ({outcome_row['failure_phase']})"
        version = ", ".join(f"{key} {value}" for key, value in versions.get(cell, {}).items()) or "—"
        rows_per_second = load.get("rows_per_second")
        queryable = load.get("time_to_queryable_seconds")
        pss = float(peaks.get(cell, {}).get("pss", 0.0))
        load_pss = float(load.get("load_peak_pss_bytes") or
                         peaks.get(cell, {}).get("load_pss", 0.0))
        cold = float(np.median(colds[cell])) if cell in colds else None
        lines.append(f"| {DISPLAY[engine]} | {dimensions} | {n_docs:,} | {outcome} | {version} | "
                     f"{_number(rows_per_second)} | {_number(queryable)} | "
                     f"{_number(load_pss / 1024**3 if load_pss else None)} | "
                     f"{_number(pss / 1024**3 if pss else None)} | {_number(cold)} |")
    lines += ["", "## Filtered suites", "",
              "| Engine | Dims | Vectors | Stage | Tier | Selectivity | ef | Mode | Index plan | Recall@10 | p50 ms | p95 ms | Underfill | Mean results |",
              "|---|---:|---:|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|"]
    for row in sorted(suites, key=lambda item: (item["cell_id"], item["label"],
                                                -float(item["selectivity"]), item["ef"], item["mode"])):
        engine, dimensions, n_docs = _cell_parts(row["cell_id"])
        gate = "yes" if row["plan_uses_index"] else "**NO**"
        mean_results = row.get("mean_result_count")
        mean_results_text = "—" if mean_results is None else f"{float(mean_results):.2f}"
        lines.append(f"| {DISPLAY[engine]} | {dimensions} | {n_docs:,} | {row['label']} | "
                     f"{row['tier']} | {100 * float(row['selectivity']):g}% | {row['ef']} | "
                     f"{row['mode']} | {gate} | {float(row['mean_recall_at_10']):.4f} | "
                     f"{float(row['p50_ms']):.3f} | {float(row['p95_ms']):.3f} | "
                     f"{int(row['underfill'])}/{int(row.get('n_queries', 0))} "
                     f"({float(row['underfill_percent']):.2f}%) | {mean_results_text} |")
    lines += ["", "## Full-text suites", "",
              "| Engine | Dims | Documents | Tier | Selectivity | Relevant pool min/mean/max | Text index plan | nDCG@10 | p50 ms | p95 ms | Underfill | Mean results | Score issue #7290 |",
              "|---|---:|---:|---|---:|---:|---|---:|---:|---:|---:|---:|---|"]
    for row in sorted(fts, key=lambda item: (item["cell_id"], -float(item["selectivity"]))):
        engine, dimensions, n_docs = _cell_parts(row["cell_id"])
        gate = "yes" if row["plan_uses_text_index"] else "**NO**"
        issue = "**observed**" if row.get("surrealdb_score_zero_issue") else "no"
        lines.append(
            f"| {DISPLAY[engine]} | {dimensions} | {n_docs:,} | {row['tier']} | "
            f"{100 * float(row['selectivity']):g}% | {_relevant_pool_summary(row)} | {gate} | "
            f"{float(row['mean_ndcg_at_10']):.4f} | {float(row['p50_ms']):.3f} | "
            f"{float(row['p95_ms']):.3f} | {int(row['underfill'])}/"
            f"{int(row['n_queries'])} ({float(row['underfill_percent']):.2f}%) | "
            f"{float(row['mean_result_count']):.2f} | {issue} |"
        )
    lines += ["", "## Hybrid suites", "",
              "| Engine | Dims | Documents | Tier | Selectivity | Relevant pool min/mean/max | ef | Vector plan | Text plan | Both | nDCG@10 | p50 ms | p95 ms | Underfill | Mean results |",
              "|---|---:|---:|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|"]
    for row in sorted(hybrid, key=lambda item: (
        item["cell_id"], -float(item["selectivity"]), int(item["ef"])
    )):
        engine, dimensions, n_docs = _cell_parts(row["cell_id"])
        gates = ["yes" if row[key] else "**NO**" for key in (
            "plan_uses_vector_index", "plan_uses_text_index", "plan_uses_both_indexes"
        )]
        lines.append(
            f"| {DISPLAY[engine]} | {dimensions} | {n_docs:,} | {row['tier']} | "
            f"{100 * float(row['selectivity']):g}% | {_relevant_pool_summary(row)} | "
            f"{row['ef']} | {gates[0]} | "
            f"{gates[1]} | {gates[2]} | {float(row['mean_ndcg_at_10']):.4f} | "
            f"{float(row['p50_ms']):.3f} | {float(row['p95_ms']):.3f} | "
            f"{int(row['underfill'])}/{int(row['n_queries'])} "
            f"({float(row['underfill_percent']):.2f}%) | "
            f"{float(row['mean_result_count']):.2f} |"
        )
    lines += ["", "## Metadata", "", "```json",
              json.dumps({"config_sha256": metadata["config_sha256"],
                          "suites": metadata.get("config", {}).get("suites"),
                          "query_topics": metadata.get("config", {}).get("query_topics"),
                          "versions": versions,
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
    peaks = _memory_peaks(results)
    outcomes = _effective_outcomes(events, peaks)
    # Completed suites remain valid evidence even if a later suite kills the cell.
    suites = [_normalized_suite(row) for row in events if row["event"] == "suite_complete"]
    fts = [row for row in events if row["event"] == "fts_suite_complete"]
    hybrid = [row for row in events if row["event"] == "hybrid_suite_complete"]
    if suites:
        _selectivity_figures(suites, outcomes, charts)
    _text_figures(fts, hybrid, outcomes, charts)
    _scale_charts(events, charts, outcomes, peaks)
    _churn_charts(suites, results, charts)
    (results / "summary.md").write_text(
        _markdown(events, suites, fts, hybrid, results, peaks, outcomes), encoding="utf-8"
    )
