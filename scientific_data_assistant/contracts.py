"""Shared file contracts for all hackathon phases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

METADATA_COLUMNS = [
    "file_id",
    "file_path",
    "sample_id",
    "material",
    "thickness_nm",
    "exposure_time_s",
    "measurement_type",
    "x_column",
    "y_column",
    "parse_status",
    "notes",
]

TRACE_COLUMNS = ["x", "y"]

COMMENTS_COLUMNS = [
    "comment_id",
    "file_id",
    "point_index",
    "comment",
    "comment_type",
    "created_by",
]


@dataclass(frozen=True)
class ProjectPaths:
    """Canonical output paths shared by all phases."""

    root: Path

    @property
    def metadata_table(self) -> Path:
        return self.root / "metadata_table.csv"

    @property
    def parsed_traces(self) -> Path:
        return self.root / "parsed_traces"

    @property
    def comments(self) -> Path:
        return self.root / "comments.csv"

    @property
    def phase1_report(self) -> Path:
        return self.root / "phase1_report.md"

    @property
    def phase2_report(self) -> Path:
        return self.root / "phase2_report.md"

    @property
    def phase3_report(self) -> Path:
        return self.root / "phase3_report.md"

    @property
    def phase4_report(self) -> Path:
        return self.root / "phase4_report.md"

    @property
    def plot_summary(self) -> Path:
        return self.root / "plot_summary.json"


def ensure_project_dirs(paths: ProjectPaths) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.parsed_traces.mkdir(parents=True, exist_ok=True)
