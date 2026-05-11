"""Phase 2: plotting-ready data and optional Plotly figures."""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import Any

from .comments import comments_for_file, load_comments
from .contracts import ProjectPaths


def load_metadata(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_trace(path: Path) -> list[dict[str, float]]:
    if not path.exists():
        return []
    rows: list[dict[str, float]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                rows.append({"x": float(row["x"]), "y": float(row["y"])})
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def summarize_traces(paths: ProjectPaths) -> list[dict[str, Any]]:
    metadata = load_metadata(paths.metadata_table)
    comments = load_comments(paths.comments)
    summaries: list[dict[str, Any]] = []

    for row in metadata:
        file_id = row["file_id"]
        trace = load_trace(paths.parsed_traces / f"{file_id}.csv")
        y_values = [point["y"] for point in trace]
        x_values = [point["x"] for point in trace]
        summary = {
            **row,
            "n_points": len(trace),
            "x_min": min(x_values) if x_values else "",
            "x_max": max(x_values) if x_values else "",
            "y_min": min(y_values) if y_values else "",
            "y_max": max(y_values) if y_values else "",
            "y_mean": statistics.fmean(y_values) if y_values else "",
            "y_peak": max(y_values) if y_values else "",
            "file_comments": " | ".join(comments_for_file(comments, file_id)),
        }
        summaries.append(summary)
    return summaries


def build_overlay_points(paths: ProjectPaths) -> list[dict[str, Any]]:
    metadata = load_metadata(paths.metadata_table)
    comments = load_comments(paths.comments)
    points: list[dict[str, Any]] = []

    for row in metadata:
        file_id = row["file_id"]
        trace = load_trace(paths.parsed_traces / f"{file_id}.csv")
        for index, point in enumerate(trace):
            point_comments = comments_for_file(comments, file_id, index)
            hover = [
                f"file_id: {file_id}",
                f"sample: {row.get('sample_id', '')}",
                f"material: {row.get('material', '')}",
                f"thickness_nm: {row.get('thickness_nm', '')}",
                f"exposure_time_s: {row.get('exposure_time_s', '')}",
                f"x: {point['x']}",
                f"y: {point['y']}",
            ]
            if point_comments:
                hover.append("comments: " + " | ".join(point_comments))
            points.append({**row, "point_index": index, "x": point["x"], "y": point["y"], "hover": "<br>".join(hover)})
    return points


def write_plot_summary(paths: ProjectPaths) -> Path:
    summaries = summarize_traces(paths)
    payload = {
        "trace_count": len(summaries),
        "summaries": summaries,
        "supported_grouping_fields": ["material", "thickness_nm", "exposure_time_s", "measurement_type", "sample_id"],
        "supported_plot_modes": ["overlay traces", "peak y by parameter", "mean y by parameter"],
    }
    paths.plot_summary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_phase2_report(paths)
    return paths.plot_summary


def write_phase2_report(paths: ProjectPaths) -> None:
    report = [
        "# Phase 2 Report",
        "",
        "Supported plot types:",
        "",
        "- Overlay parsed x/y traces grouped by material, thickness, exposure time, measurement type, or sample ID.",
        "- Summary scatter plots using peak y or mean y against numeric metadata parameters.",
        "- Hover text includes file ID, metadata, x/y values, and available comments.",
        "",
        "Phase 2 reads `metadata_table.csv`, `parsed_traces/`, and `comments.csv` without modifying Phase 1 outputs.",
    ]
    paths.phase2_report.write_text("\n".join(report), encoding="utf-8")


def make_plotly_overlay(paths: ProjectPaths, color_by: str = "material") -> Any:
    try:
        import plotly.express as px
    except ImportError as exc:
        raise RuntimeError("Plotly is not installed. Run `pip install -r requirements.txt`.") from exc

    points = build_overlay_points(paths)
    if not points:
        return px.scatter(title="No parsed points available")
    return px.line(points, x="x", y="y", color=color_by, line_group="file_id", hover_data=["hover"], title="Parsed .xy traces")


def make_plotly_summary(paths: ProjectPaths, x_field: str = "thickness_nm", y_field: str = "y_peak", color_by: str = "material") -> Any:
    try:
        import plotly.express as px
    except ImportError as exc:
        raise RuntimeError("Plotly is not installed. Run `pip install -r requirements.txt`.") from exc

    rows = summarize_traces(paths)
    numeric_rows = []
    for row in rows:
        try:
            row[x_field] = float(row[x_field])
            row[y_field] = float(row[y_field])
        except (KeyError, TypeError, ValueError):
            continue
        numeric_rows.append(row)

    if not numeric_rows:
        return px.scatter(title=f"No numeric data for {x_field} vs {y_field}")
    return px.scatter(numeric_rows, x=x_field, y=y_field, color=color_by, hover_data=["file_id", "sample_id", "file_comments"])
