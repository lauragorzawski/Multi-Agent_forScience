"""Phase 3: comments and deterministic quality notes."""

from __future__ import annotations

import csv
from pathlib import Path

from .contracts import COMMENTS_COLUMNS, ProjectPaths


def load_comments(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_comments(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COMMENTS_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in COMMENTS_COLUMNS})


def add_comment(
    paths: ProjectPaths,
    file_id: str,
    comment: str,
    point_index: str = "",
    comment_type: str = "manual",
    created_by: str = "human",
) -> dict[str, str]:
    rows = load_comments(paths.comments)
    comment_id = f"comment_{len(rows) + 1:04d}"
    row = {
        "comment_id": comment_id,
        "file_id": file_id,
        "point_index": point_index,
        "comment": comment,
        "comment_type": comment_type,
        "created_by": created_by,
    }
    rows.append(row)
    write_comments(paths.comments, rows)
    return row


def generate_quality_comments(paths: ProjectPaths) -> list[dict[str, str]]:
    metadata = _load_metadata(paths.metadata_table)
    existing = [
        row
        for row in load_comments(paths.comments)
        if "filename does not contain enough recognized parameters" not in row.get("comment", "")
    ]
    seen = {(row.get("file_id", ""), row.get("comment", "")) for row in existing}
    additions: list[dict[str, str]] = []

    for row in metadata:
        messages: list[str] = []
        if row.get("parse_status") == "failed":
            messages.append("File could not be parsed; exclude from quantitative plotting until reviewed.")
        if row.get("material") == "missing":
            messages.append("Missing material metadata.")
        if not row.get("thickness_nm"):
            messages.append("Missing thickness metadata.")
        if not row.get("exposure_time_s"):
            messages.append("Missing exposure time metadata.")

        for message in messages:
            key = (row["file_id"], message)
            if key in seen:
                continue
            additions.append(
                {
                    "comment_id": f"comment_{len(existing) + len(additions) + 1:04d}",
                    "file_id": row["file_id"],
                    "point_index": "",
                    "comment": message,
                    "comment_type": "quality",
                    "created_by": "quality_critic_agent",
                }
            )

    write_comments(paths.comments, existing + additions)
    write_phase3_report(paths, additions)
    return additions


def comments_for_file(rows: list[dict[str, str]], file_id: str, point_index: int | None = None) -> list[str]:
    comments: list[str] = []
    for row in rows:
        if row.get("file_id") != file_id:
            continue
        row_point = row.get("point_index", "")
        if not row_point or point_index is None or row_point == str(point_index):
            comments.append(row.get("comment", ""))
    return [comment for comment in comments if comment]


def write_phase3_report(paths: ProjectPaths, additions: list[dict[str, str]]) -> None:
    report = [
        "# Phase 3 Report",
        "",
        f"Quality comments generated: {len(additions)}",
        "",
        "Comments are linked by `file_id` and optionally by `point_index`.",
        "Plot hover text can display both file-level comments and point-level comments.",
        "",
        "## New Quality Flags",
        "",
    ]
    if additions:
        report.extend(f"- `{row['file_id']}`: {row['comment']}" for row in additions)
    else:
        report.append("None.")
    paths.phase3_report.write_text("\n".join(report), encoding="utf-8")


def _load_metadata(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))
