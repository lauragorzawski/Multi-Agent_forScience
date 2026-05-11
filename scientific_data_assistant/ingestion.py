"""Phase 1: scan messy folders, parse .xy files, and extract metadata."""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .contracts import COMMENTS_COLUMNS, METADATA_COLUMNS, TRACE_COLUMNS, ProjectPaths, ensure_project_dirs

MATERIAL_TOKENS = [
    "CoFeB",
    "FGT",
    "FeRu",
    "RuFe",
    "MgO",
    "Ta",
    "Pt",
    "Co",
    "Fe",
    "Ru",
    "Ni",
    "Au",
    "Al",
]

MEASUREMENT_TOKENS = {
    "xrd": "xrd",
    "xrr": "xrr",
    "vsm": "vsm",
    "raman": "raman",
    "afm": "afm",
    "edx": "edx",
    "xps": "xps",
}


@dataclass
class ParsedXY:
    rows: list[tuple[float, float]]
    skipped_lines: int
    status: str
    note: str


MEASUREMENT_EXTENSIONS = {".xy", ".txt"}
MetadataExtractor = Callable[[Path], dict[str, object]]


def scan_xy_files(input_dir: Path) -> list[Path]:
    return sorted(path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in MEASUREMENT_EXTENSIONS)


def make_file_id(path: Path, input_dir: Path) -> str:
    relative = str(path.relative_to(input_dir)).encode("utf-8", errors="replace")
    digest = hashlib.sha1(relative).hexdigest()[:10]
    stem = re.sub(r"[^A-Za-z0-9]+", "_", path.stem).strip("_").lower()[:36]
    return f"{stem or 'trace'}_{digest}"


def parse_xy_file(path: Path) -> ParsedXY:
    rows: list[tuple[float, float]] = []
    skipped = 0

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ParsedXY([], 0, "failed", f"Could not read file: {exc}")

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "//", ";", "%")):
            skipped += 1
            continue

        parts = re.split(r"[\s,;\t]+", line)
        numeric: list[float] = []
        for part in parts:
            try:
                numeric.append(float(part))
            except ValueError:
                continue
            if len(numeric) == 2:
                break

        if len(numeric) == 2:
            rows.append((numeric[0], numeric[1]))
        else:
            skipped += 1

    if not rows:
        return ParsedXY([], skipped, "failed", "No numeric x/y rows found.")
    if skipped:
        return ParsedXY(rows, skipped, "warning", f"Parsed {len(rows)} rows; skipped {skipped} header/comment/malformed lines.")
    return ParsedXY(rows, skipped, "ok", f"Parsed {len(rows)} rows.")


def extract_metadata(path: Path) -> dict[str, str]:
    text = path.stem
    lower = text.lower()

    material = "missing"
    for token in MATERIAL_TOKENS:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text, re.IGNORECASE):
            material = token
            break

    thickness_nm = ""
    thickness_patterns = [
        r"(?P<value>\d+(?:\.\d+)?)\s*[_-]?\s*nm(?![a-z0-9])",
        r"\bt\s*[_-]?\s*(?P<value>\d+(?:\.\d+)?)\b",
        r"\bthick(?:ness)?\s*[_-]?\s*(?P<value>\d+(?:\.\d+)?)\b",
    ]
    for pattern in thickness_patterns:
        match = re.search(pattern, lower)
        if match:
            thickness_nm = _format_number(match.group("value"))
            break

    exposure_time_s = ""
    exposure_patterns = [
        (r"(?P<value>\d+(?:\.\d+)?)\s*[_-]?\s*s(?![a-z0-9])", 1.0),
        (r"(?P<value>\d+(?:\.\d+)?)\s*[_-]?\s*sec(?![a-z0-9])", 1.0),
        (r"(?P<value>\d+(?:\.\d+)?)\s*[_-]?\s*min(?![a-z0-9])", 60.0),
        (r"(?<![a-z0-9])exp(?:osure)?\s*[_-]?\s*(?P<value>\d+(?:\.\d+)?)", 1.0),
    ]
    for pattern, multiplier in exposure_patterns:
        match = re.search(pattern, lower)
        if match:
            exposure_time_s = _format_number(float(match.group("value")) * multiplier)
            break

    measurement_type = "unknown"
    for token, value in MEASUREMENT_TOKENS.items():
        if token in lower:
            measurement_type = value
            break

    sample_match = re.search(r"\b(sample|s)\s*[_-]?\s*(?P<id>[A-Za-z0-9]+)\b", text, re.IGNORECASE)
    sample_id = sample_match.group("id") if sample_match else re.sub(r"[^A-Za-z0-9]+", "_", path.stem).strip("_")

    missing = []
    if material == "missing":
        missing.append("material")
    if not thickness_nm:
        missing.append("thickness_nm")
    if not exposure_time_s:
        missing.append("exposure_time_s")
    if measurement_type == "unknown":
        missing.append("measurement_type")

    notes = "Metadata extracted from filename patterns."
    if missing:
        notes += " Missing: " + ", ".join(missing) + "."

    return {
        "sample_id": sample_id or "missing",
        "material": material,
        "thickness_nm": thickness_nm,
        "exposure_time_s": exposure_time_s,
        "measurement_type": measurement_type,
        "notes": notes,
    }


def run_phase1(
    input_dir: Path,
    output_dir: Path,
    metadata_extractor: MetadataExtractor | None = None,
    extra_metadata_columns: Iterable[str] | None = None,
) -> ProjectPaths:
    input_dir = input_dir.expanduser().resolve()
    paths = ProjectPaths(output_dir.expanduser().resolve())
    ensure_project_dirs(paths)

    extractor = metadata_extractor or extract_metadata
    table_columns = METADATA_COLUMNS + _normalize_extra_columns(extra_metadata_columns)
    xy_files = scan_xy_files(input_dir)
    metadata_rows: list[dict[str, str]] = []
    failed: list[str] = []
    warnings: list[str] = []

    for xy_file in xy_files:
        file_id = make_file_id(xy_file, input_dir)
        parsed = parse_xy_file(xy_file)
        metadata = extractor(xy_file)

        if parsed.rows:
            write_trace(paths.parsed_traces / f"{file_id}.csv", parsed.rows)

        if parsed.status == "failed":
            failed.append(f"- `{xy_file}`: {parsed.note}")
        elif parsed.status == "warning":
            warnings.append(f"- `{xy_file}`: {parsed.note}")

        row = {
            "file_id": file_id,
            "file_path": str(xy_file),
            "sample_id": _metadata_value(metadata, "sample_id", "missing"),
            "material": _metadata_value(metadata, "material", "missing"),
            "thickness_nm": _metadata_value(metadata, "thickness_nm", ""),
            "exposure_time_s": _metadata_value(metadata, "exposure_time_s", ""),
            "measurement_type": _metadata_value(metadata, "measurement_type", "unknown"),
            "x_column": "x",
            "y_column": "y",
            "parse_status": parsed.status,
            "notes": f"{_metadata_value(metadata, 'notes', 'Metadata extracted from filename patterns.')} {parsed.note}".strip(),
        }
        for column in table_columns:
            if column not in METADATA_COLUMNS:
                row[column] = _metadata_value(metadata, column, "")
        metadata_rows.append(row)

    write_csv(paths.metadata_table, table_columns, metadata_rows)
    ensure_comments_file(paths.comments)
    write_phase1_report(paths, input_dir, xy_files, metadata_rows, warnings, failed, table_columns)
    return paths


def write_trace(path: Path, rows: Iterable[tuple[float, float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(TRACE_COLUMNS)
        writer.writerows(rows)


def write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def ensure_comments_file(path: Path) -> None:
    if path.exists():
        return
    write_csv(path, COMMENTS_COLUMNS, [])


def write_phase1_report(
    paths: ProjectPaths,
    input_dir: Path,
    xy_files: list[Path],
    metadata_rows: list[dict[str, str]],
    warnings: list[str],
    failed: list[str],
    table_columns: list[str] | None = None,
) -> None:
    status_counts = _count(row["parse_status"] for row in metadata_rows)
    extra_columns = [column for column in table_columns or METADATA_COLUMNS if column not in METADATA_COLUMNS]

    report = [
        "# Phase 1 Report",
        "",
        f"Input folder: `{input_dir}`",
        f"Discovered measurement files: {len(xy_files)}",
        f"Metadata rows written: {len(metadata_rows)}",
        "",
        "## Filename Rules",
        "",
        "- Materials are matched from known material tokens such as Fe, Ru, FeRu, CoFeB, MgO, Pt, Ta.",
        "- Thickness is matched from patterns like `2nm`, `2_nm`, `t2`, or `thickness2`.",
        "- Exposure time is matched from patterns like `30s`, `30_sec`, `5min`, or `exp30`.",
        "- Measurement type is matched from filename tokens such as xrd, xrr, vsm, raman, afm, edx, xps.",
        "- Missing fields are left blank or marked `missing`; they are not guessed.",
        "- Extra user-approved metadata columns are appended after the required contract columns.",
        "",
        "## Extra Metadata Columns",
        "",
        ", ".join(extra_columns) if extra_columns else "None.",
        "",
        "## Parse Status",
        "",
        _format_counts(status_counts),
        "",
        "## Warnings",
        "",
        "\n".join(warnings) if warnings else "None.",
        "",
        "## Failed Files",
        "",
        "\n".join(failed) if failed else "None.",
        "",
    ]
    paths.phase1_report.write_text("\n".join(report), encoding="utf-8")


def _format_number(value: float | str) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.6g}"


def _normalize_extra_columns(columns: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    seen = set(METADATA_COLUMNS)
    for column in columns or []:
        clean = re.sub(r"[^A-Za-z0-9_]+", "_", str(column)).strip("_").lower()
        if not clean or clean in seen:
            continue
        normalized.append(clean)
        seen.add(clean)
    return normalized


def _metadata_value(metadata: dict[str, object], key: str, default: str) -> str:
    value = metadata.get(key, default)
    if value is None:
        return ""
    return str(value)


def _count(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "None."
    return "\n".join(f"- {key}: {value}" for key, value in sorted(counts.items()))
