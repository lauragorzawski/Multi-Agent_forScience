"""Conversational LangGraph agent for Phase 1 metadata extraction."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Callable, TypedDict

from .contracts import METADATA_COLUMNS, ProjectPaths
from .ingestion import make_file_id, parse_xy_file, run_phase1, scan_xy_files


class MetadataAgentState(TypedDict, total=False):
    input_dir: str
    output_dir: str
    metadata_pattern: str
    pattern_example: str
    messages: list[dict[str, str]]
    discovered_files: list[str]
    proposed_columns: list[str]
    extraction_spec: dict[str, Any]
    generated_code: str
    preview_rows: list[dict[str, str]]
    table_overview: list[dict[str, str]]
    unclear_items: list[str]
    suggested_user_messages: list[str]
    conversation_stage: str
    validation_errors: list[str]
    run_summary: str
    approved: bool


MetadataExtractor = Callable[[Path], dict[str, object]]

SAFE_IMPORTS = {"re", "pathlib"}
DISALLOWED_CALLS = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "getattr",
    "globals",
    "input",
    "locals",
    "open",
    "setattr",
}
DISALLOWED_ATTR_CALLS = {
    "chmod",
    "mkdir",
    "open",
    "read_bytes",
    "read_text",
    "rename",
    "resolve",
    "rmdir",
    "symlink_to",
    "touch",
    "unlink",
    "write_bytes",
    "write_text",
}
PATH_ONLY_DISALLOWED_ATTR_CALLS = {"replace"}
KNOWN_EXTRA_COLUMNS = ["measurement_date", "setting_value", "position_1", "position_2", "replicate_index"]


def run_metadata_agent_turn(state: MetadataAgentState | None, user_message: str = "") -> MetadataAgentState:
    """Advance the metadata builder by one Streamlit-friendly conversation turn."""

    next_state: MetadataAgentState = dict(state or {})
    messages = list(next_state.get("messages", []))
    clean_message = user_message.strip()
    next_state["validation_errors"] = []
    if clean_message:
        messages.append({"role": "user", "content": clean_message})
        next_state["approved"] = _message_approves(clean_message)
    elif "approved" not in next_state:
        next_state["approved"] = False
    next_state["messages"] = messages

    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        return _run_without_langgraph(next_state)

    graph = StateGraph(MetadataAgentState)
    graph.add_node("scan_files", _scan_files)
    graph.add_node("infer_rules", _infer_rules)
    graph.add_node("generate_code", _generate_code)
    graph.add_node("validate_code", _validate_code)
    graph.add_node("build_preview", _build_preview)
    graph.add_node("commit_outputs", _commit_outputs)
    graph.add_node("respond", _respond)
    graph.set_entry_point("scan_files")
    graph.add_edge("scan_files", "infer_rules")
    graph.add_edge("infer_rules", "generate_code")
    graph.add_edge("generate_code", "validate_code")
    graph.add_conditional_edges("validate_code", _next_after_validation, {"commit": "commit_outputs", "preview": "build_preview"})
    graph.add_edge("build_preview", "respond")
    graph.add_edge("commit_outputs", "respond")
    graph.add_edge("respond", END)
    return graph.compile().invoke(next_state)


def validate_generated_code(code: str) -> list[str]:
    """Return validation errors for generated extraction code."""

    errors: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Syntax error: {exc}"]

    has_extractor = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "extract_metadata_from_filename":
            has_extractor = True
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            errors.extend(_validate_import(node))
        elif isinstance(node, ast.Call):
            errors.extend(_validate_call(node))

    if not has_extractor:
        errors.append("Generated code must define extract_metadata_from_filename(path).")
    return errors


def load_metadata_extractor(code: str) -> MetadataExtractor:
    """Compile validated extraction code into a callable metadata extractor."""

    errors = validate_generated_code(code)
    if errors:
        raise ValueError("; ".join(errors))

    namespace: dict[str, Any] = {"__builtins__": _safe_builtins(), "re": re, "Path": Path}
    exec(compile(code, "<metadata_agent_generated>", "exec"), namespace, namespace)
    extractor = namespace.get("extract_metadata_from_filename")
    if not callable(extractor):
        raise ValueError("Generated code did not create a callable extractor.")

    def wrapped(path: Path) -> dict[str, object]:
        metadata = extractor(path)
        if not isinstance(metadata, dict):
            raise ValueError("Generated extractor must return a dictionary.")
        return metadata

    return wrapped


def _run_without_langgraph(state: MetadataAgentState) -> MetadataAgentState:
    state = _scan_files(state)
    state = _infer_rules(state)
    state = _generate_code(state)
    state = _validate_code(state)
    if _next_after_validation(state) == "commit":
        state = _commit_outputs(state)
    else:
        state = _build_preview(state)
    return _respond(state)


def _scan_files(state: MetadataAgentState) -> MetadataAgentState:
    input_dir = Path(state.get("input_dir", "") or ".").expanduser()
    if not input_dir.exists():
        state["discovered_files"] = []
        state["validation_errors"] = [f"Input folder does not exist: {input_dir}"]
        return state

    files = scan_xy_files(input_dir)
    state["discovered_files"] = [str(path) for path in files]
    return state


def _infer_rules(state: MetadataAgentState) -> MetadataAgentState:
    files = [Path(path) for path in state.get("discovered_files", [])]
    previous_spec = dict(state.get("extraction_spec", {}))
    extra_columns = list(previous_spec.get("extra_columns", []))
    user_message = _latest_user_message(state)
    pattern_context = " ".join(
        part
        for part in [
            state.get("metadata_pattern", ""),
            state.get("pattern_example", ""),
            user_message,
        ]
        if part
    )

    for column in _infer_extra_columns(files):
        if column not in extra_columns:
            extra_columns.append(column)
    for column in _columns_from_feedback(pattern_context):
        if column not in extra_columns and column not in METADATA_COLUMNS:
            extra_columns.append(column)

    spec = {
        "base_columns": METADATA_COLUMNS,
        "extra_columns": extra_columns,
        "filename_examples": [path.name for path in files[:8]],
        "rules": [
            "sample_id comes from sample/S tokens when present, otherwise the filename stem",
            "material is matched from known material tokens",
            "thickness_nm is matched from nm/t/thickness filename patterns",
            "exposure_time_s is matched from s/sec/min/exp filename patterns",
            "measurement_type is matched from tokens such as xrd, xrr, vsm, raman, afm, edx, xps",
        ],
        "feedback_notes": previous_spec.get("feedback_notes", []),
        "user_metadata_pattern": state.get("metadata_pattern", ""),
        "user_pattern_example": state.get("pattern_example", ""),
    }
    if user_message and not _message_approves(user_message):
        spec["feedback_notes"] = [*spec["feedback_notes"], user_message][-6:]

    state["extraction_spec"] = spec
    state["proposed_columns"] = METADATA_COLUMNS + extra_columns
    return state


def _generate_code(state: MetadataAgentState) -> MetadataAgentState:
    extra_columns = list(state.get("extraction_spec", {}).get("extra_columns", []))
    state["generated_code"] = _generated_extractor_code(extra_columns)
    return state


def _validate_code(state: MetadataAgentState) -> MetadataAgentState:
    errors = list(state.get("validation_errors", []))
    code_errors = validate_generated_code(state.get("generated_code", ""))
    state["validation_errors"] = errors + code_errors
    return state


def _build_preview(state: MetadataAgentState) -> MetadataAgentState:
    if state.get("validation_errors"):
        state["preview_rows"] = []
        state["table_overview"] = []
        state["unclear_items"] = []
        return state

    if _needs_pattern_guidance(state):
        state["preview_rows"] = []
        state["table_overview"] = []
        state["unclear_items"] = []
        state["conversation_stage"] = "need_pattern"
        state["run_summary"] = f"Found {len(state.get('discovered_files', []))} measurement files. Waiting for filename pattern guidance."
        return state

    input_dir = Path(state.get("input_dir", "") or ".").expanduser()
    try:
        extractor = load_metadata_extractor(state.get("generated_code", ""))
        rows = _preview_rows(input_dir, extractor, state.get("extraction_spec", {}).get("extra_columns", []))
    except Exception as exc:
        state["validation_errors"] = [*state.get("validation_errors", []), f"Preview failed: {exc}"]
        state["preview_rows"] = []
        state["table_overview"] = []
        state["unclear_items"] = []
        return state

    state["preview_rows"] = rows
    state["table_overview"] = _table_overview(rows, state.get("extraction_spec", {}).get("extra_columns", []))
    state["unclear_items"] = _unclear_items(rows)
    state["conversation_stage"] = "review_overview"
    state["run_summary"] = f"Previewed {len(rows)} measurement files. Send feedback or approve to write outputs."
    return state


def _commit_outputs(state: MetadataAgentState) -> MetadataAgentState:
    if state.get("validation_errors"):
        return state

    input_dir = Path(state.get("input_dir", "") or ".").expanduser()
    output_dir = Path(state.get("output_dir", "") or "metadata_agent_output").expanduser()
    extra_columns = list(state.get("extraction_spec", {}).get("extra_columns", []))

    try:
        extractor = load_metadata_extractor(state.get("generated_code", ""))
        paths = run_phase1(input_dir, output_dir, metadata_extractor=extractor, extra_metadata_columns=extra_columns)
        state["preview_rows"] = _preview_rows(input_dir, extractor, extra_columns)
        state["table_overview"] = _table_overview(state["preview_rows"], extra_columns)
        state["unclear_items"] = _unclear_items(state["preview_rows"])
        _write_agent_artifacts(paths, state)
    except Exception as exc:
        state["validation_errors"] = [*state.get("validation_errors", []), f"Run failed: {exc}"]
        state["approved"] = False
        return state

    state["run_summary"] = f"Wrote approved metadata table and parsed traces to {output_dir}."
    state["conversation_stage"] = "approved"
    return state


def _respond(state: MetadataAgentState) -> MetadataAgentState:
    messages = list(state.get("messages", []))
    errors = state.get("validation_errors", [])
    state["suggested_user_messages"] = _suggested_user_messages(state)
    if errors:
        content = "I found a problem before writing outputs:\n\n" + "\n".join(f"- {error}" for error in errors)
    elif state.get("approved"):
        content = (
            f"{state.get('run_summary', 'Approved outputs written.')}\n\n"
            "The required Phase 1 columns are preserved, and any extra approved columns were appended."
        )
    elif state.get("conversation_stage") == "need_pattern":
        examples = state.get("extraction_spec", {}).get("filename_examples", [])
        example_text = "\n".join(f"- `{example}`" for example in examples[:5]) or "- no files found yet"
        content = (
            "Where is your data stored? I have the folder now, and I found the files below.\n\n"
            "What is the pattern of the metadata in your filenames? Please give one example and tell me what each part means.\n\n"
            f"Examples I found:\n{example_text}"
        )
    else:
        files = len(state.get("discovered_files", []))
        extras = state.get("extraction_spec", {}).get("extra_columns", [])
        extra_text = ", ".join(extras) if extras else "none yet"
        unclear = state.get("unclear_items", [])
        unclear_text = "\n\nUnclear items:\n" + "\n".join(f"- {item}" for item in unclear[:12]) if unclear else "\n\nI do not see obvious missing metadata in the preview."
        content = (
            f"I found {files} measurement files and drafted filename extraction rules.\n\n"
            f"Extra proposed columns: {extra_text}.\n\n"
            "I created the overview table from your filename pattern. Please review whether each file is linked to the right parameters."
            f"{unclear_text}\n\n"
            "Is this fine? Send feedback if anything is wrong, or approve when it looks right."
        )
    if not messages or messages[-1].get("role") != "assistant" or messages[-1].get("content") != content:
        messages.append({"role": "assistant", "content": content})
    state["messages"] = messages
    return state


def _next_after_validation(state: MetadataAgentState) -> str:
    if state.get("approved") and not state.get("validation_errors") and not _needs_pattern_guidance(state):
        return "commit"
    return "preview"


def _preview_rows(
    input_dir: Path,
    metadata_extractor: MetadataExtractor,
    extra_columns: list[str],
    limit: int = 50,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    columns = METADATA_COLUMNS + [column for column in extra_columns if column not in METADATA_COLUMNS]
    for xy_file in scan_xy_files(input_dir)[:limit]:
        parsed = parse_xy_file(xy_file)
        metadata = metadata_extractor(xy_file)
        row = {
            "file_id": make_file_id(xy_file, input_dir),
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
        for column in columns:
            if column not in METADATA_COLUMNS:
                row[column] = _metadata_value(metadata, column, "")
        rows.append(row)
    return rows


def _table_overview(rows: list[dict[str, str]], extra_columns: list[str]) -> list[dict[str, str]]:
    overview_columns = [
        "file",
        "sample_id",
        "material",
        "thickness_nm",
        "exposure_time_s",
        "measurement_type",
        *[column for column in extra_columns if column not in METADATA_COLUMNS],
        "parse_status",
        "notes",
    ]
    overview: list[dict[str, str]] = []
    for row in rows:
        item = {
            "file": Path(row.get("file_path", "")).name,
            "sample_id": row.get("sample_id", ""),
            "material": row.get("material", ""),
            "thickness_nm": row.get("thickness_nm", ""),
            "exposure_time_s": row.get("exposure_time_s", ""),
            "measurement_type": row.get("measurement_type", ""),
            "parse_status": row.get("parse_status", ""),
            "notes": row.get("notes", ""),
        }
        for column in overview_columns:
            if column not in item:
                item[column] = row.get(column, "")
        overview.append({column: item.get(column, "") for column in overview_columns})
    return overview


def _unclear_items(rows: list[dict[str, str]]) -> list[str]:
    unclear: list[str] = []
    for row in rows:
        file_name = Path(row.get("file_path", "")).name
        missing = []
        if row.get("material") == "missing":
            missing.append("material")
        if not row.get("thickness_nm"):
            missing.append("thickness")
        if not row.get("exposure_time_s"):
            missing.append("exposure/setting time")
        if row.get("measurement_type") == "unknown":
            missing.append("measurement type")
        if row.get("parse_status") != "ok":
            missing.append(f"parse status is {row.get('parse_status')}")
        if missing:
            unclear.append(f"{file_name}: " + ", ".join(missing))
    return unclear


def _suggested_user_messages(state: MetadataAgentState) -> list[str]:
    if state.get("validation_errors"):
        return [
            "Use input_dir raw_data/20250708",
            "Start over and scan again",
        ]
    if state.get("approved"):
        return [
            "Scan another folder",
            "Show me which metadata fields were missing",
        ]
    if state.get("conversation_stage") == "need_pattern":
        return [
            "The filename pattern is material_position_thickness_date_setting, for example FGT_1_1_20nm_20250708_0p1.txt.",
            "Please extract date, thickness, sample position, and setting value from the filename.",
        ]

    suggestions = [
        "This overview is not right: the 0p1 or 1p0 part should be setting_value.",
        "The numbers after FGT are sample position columns.",
        "Please extract the date from the filename.",
        "Please extract the setting value, for example 0p1 or 1p0, as setting_value.",
        "Please extract replicate numbers from trailing filename suffixes.",
        "approve and write outputs",
    ]
    extra_columns = set(state.get("extraction_spec", {}).get("extra_columns", []))
    if "measurement_date" in extra_columns:
        suggestions.remove("Please extract the date from the filename.")
    if "setting_value" in extra_columns:
        suggestions.remove("Please extract the setting value, for example 0p1 or 1p0, as setting_value.")
    if "replicate_index" in extra_columns:
        suggestions.remove("Please extract replicate numbers from trailing filename suffixes.")
    return suggestions


def _needs_pattern_guidance(state: MetadataAgentState) -> bool:
    if state.get("metadata_pattern") or state.get("pattern_example"):
        return False
    latest = _latest_user_message(state)
    if latest and not _message_approves(latest):
        return False
    return True


def _write_agent_artifacts(paths: ProjectPaths, state: MetadataAgentState) -> None:
    (paths.root / "metadata_agent_extractor.py").write_text(state.get("generated_code", ""), encoding="utf-8")
    report = [
        "# Metadata Agent Report",
        "",
        state.get("run_summary", ""),
        "",
        "## Proposed Columns",
        "",
        ", ".join(state.get("proposed_columns", [])) or "None.",
        "",
        "## Extraction Spec",
        "",
        "```json",
        json.dumps(state.get("extraction_spec", {}), indent=2),
        "```",
    ]
    (paths.root / "metadata_agent_report.md").write_text("\n".join(report), encoding="utf-8")


def _infer_extra_columns(files: list[Path]) -> list[str]:
    stems = [path.stem for path in files]
    extras: list[str] = []
    if any(re.search(r"(?<!\d)20\d{6}(?!\d)", stem) for stem in stems):
        extras.append("measurement_date")
    if any(re.search(r"(?<![A-Za-z0-9])\d+p\d+(?![A-Za-z0-9])", stem.lower()) for stem in stems):
        extras.append("setting_value")
    if any(re.search(r"^[A-Za-z]+[_-]\d+[_-]\d+[_-]", stem) for stem in stems):
        extras.extend(["position_1", "position_2"])
    if any(re.search(r"(?:_|-)\d+$", stem) for stem in stems):
        extras.append("replicate_index")
    return extras


def _columns_from_feedback(message: str) -> list[str]:
    columns: list[str] = []
    lower = message.lower()
    if "date" in lower:
        columns.append("measurement_date")
    if "setting" in lower or "field" in lower or "voltage" in lower:
        columns.append("setting_value")
    if "position" in lower:
        columns.extend(["position_1", "position_2"])
    if "replicate" in lower or "repeat" in lower:
        columns.append("replicate_index")

    for match in re.finditer(r"`([A-Za-z][A-Za-z0-9_]*)`", message):
        columns.append(match.group(1))
    for match in re.finditer(r"\bcolumn\s+(?:called\s+|named\s+)?([A-Za-z][A-Za-z0-9_]*)", message, re.IGNORECASE):
        columns.append(match.group(1))

    normalized: list[str] = []
    for column in columns:
        clean = re.sub(r"[^A-Za-z0-9_]+", "_", column).strip("_").lower()
        if clean and clean not in normalized:
            normalized.append(clean)
    return normalized[:8]


def _generated_extractor_code(extra_columns: list[str]) -> str:
    return f'''import re
from pathlib import Path

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
MEASUREMENT_TOKENS = {{
    "xrd": "xrd",
    "xrr": "xrr",
    "vsm": "vsm",
    "raman": "raman",
    "afm": "afm",
    "edx": "edx",
    "xps": "xps",
}}
EXTRA_COLUMNS = {extra_columns!r}


def _format_number(value):
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{{number:.6g}}"


def _format_date(value):
    return f"{{value[0:4]}}-{{value[4:6]}}-{{value[6:8]}}"


def extract_metadata_from_filename(path: Path) -> dict[str, str]:
    text = Path(path).stem
    lower = text.lower()

    material = "missing"
    for token in MATERIAL_TOKENS:
        if re.search(rf"(?<![A-Za-z0-9]){{re.escape(token)}}(?![A-Za-z0-9])", text, re.IGNORECASE):
            material = token
            break

    thickness_nm = ""
    for pattern in [
        r"(?P<value>\\d+(?:\\.\\d+)?)\\s*[_-]?\\s*nm(?![a-z0-9])",
        r"\\bt\\s*[_-]?\\s*(?P<value>\\d+(?:\\.\\d+)?)\\b",
        r"\\bthick(?:ness)?\\s*[_-]?\\s*(?P<value>\\d+(?:\\.\\d+)?)\\b",
    ]:
        match = re.search(pattern, lower)
        if match:
            thickness_nm = _format_number(match.group("value"))
            break

    exposure_time_s = ""
    for pattern, multiplier in [
        (r"(?P<value>\\d+(?:\\.\\d+)?)\\s*[_-]?\\s*s(?![a-z0-9])", 1.0),
        (r"(?P<value>\\d+(?:\\.\\d+)?)\\s*[_-]?\\s*sec(?![a-z0-9])", 1.0),
        (r"(?P<value>\\d+(?:\\.\\d+)?)\\s*[_-]?\\s*min(?![a-z0-9])", 60.0),
        (r"(?<![a-z0-9])exp(?:osure)?\\s*[_-]?\\s*(?P<value>\\d+(?:\\.\\d+)?)", 1.0),
    ]:
        match = re.search(pattern, lower)
        if match:
            exposure_time_s = _format_number(float(match.group("value")) * multiplier)
            break

    measurement_type = "unknown"
    for token, value in MEASUREMENT_TOKENS.items():
        if token in lower:
            measurement_type = value
            break

    sample_match = re.search(r"\\b(sample|s)\\s*[_-]?\\s*(?P<id>[A-Za-z0-9]+)\\b", text, re.IGNORECASE)
    sample_id = sample_match.group("id") if sample_match else re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")

    missing = []
    if material == "missing":
        missing.append("material")
    if not thickness_nm:
        missing.append("thickness_nm")
    if not exposure_time_s:
        missing.append("exposure_time_s")
    if measurement_type == "unknown":
        missing.append("measurement_type")

    notes = "Metadata extracted by the conversational metadata agent."
    if missing:
        notes += " Missing: " + ", ".join(missing) + "."

    metadata = {{
        "sample_id": sample_id or "missing",
        "material": material,
        "thickness_nm": thickness_nm,
        "exposure_time_s": exposure_time_s,
        "measurement_type": measurement_type,
        "notes": notes,
    }}

    if "measurement_date" in EXTRA_COLUMNS:
        match = re.search(r"(?<!\\d)(20\\d{{6}})(?!\\d)", text)
        metadata["measurement_date"] = _format_date(match.group(1)) if match else ""
    if "setting_value" in EXTRA_COLUMNS:
        matches = re.findall(r"(?<![A-Za-z0-9])(\\d+p\\d+)(?![A-Za-z0-9])", lower)
        metadata["setting_value"] = matches[-1].replace("p", ".") if matches else ""
    if "position_1" in EXTRA_COLUMNS or "position_2" in EXTRA_COLUMNS:
        match = re.search(r"^[A-Za-z]+[_-](?P<position_1>\\d+)[_-](?P<position_2>\\d+)[_-]", text)
        if "position_1" in EXTRA_COLUMNS:
            metadata["position_1"] = match.group("position_1") if match else ""
        if "position_2" in EXTRA_COLUMNS:
            metadata["position_2"] = match.group("position_2") if match else ""
    if "replicate_index" in EXTRA_COLUMNS:
        match = re.search(r"(?:_|-)(\\d+)$", text)
        metadata["replicate_index"] = match.group(1) if match else ""

    for column in EXTRA_COLUMNS:
        metadata.setdefault(column, "")
    return metadata
'''


def _validate_import(node: ast.Import | ast.ImportFrom) -> list[str]:
    errors: list[str] = []
    if isinstance(node, ast.Import):
        modules = [alias.name.split(".")[0] for alias in node.names]
    else:
        modules = [(node.module or "").split(".")[0]]
    for module in modules:
        if module not in SAFE_IMPORTS:
            errors.append(f"Import is not allowed: {module}")
    return errors


def _validate_call(node: ast.Call) -> list[str]:
    if isinstance(node.func, ast.Name) and node.func.id in DISALLOWED_CALLS:
        return [f"Call is not allowed: {node.func.id}"]
    if isinstance(node.func, ast.Attribute) and node.func.attr in DISALLOWED_ATTR_CALLS:
        return [f"Method call is not allowed: {node.func.attr}"]
    if isinstance(node.func, ast.Attribute) and node.func.attr in PATH_ONLY_DISALLOWED_ATTR_CALLS and _looks_path_like(node.func.value):
        return [f"Path method call is not allowed: {node.func.attr}"]
    return []


def _looks_path_like(node: ast.AST) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path":
        return True
    if isinstance(node, ast.Name) and node.id in {"path", "filepath", "file_path"}:
        return True
    return False


def _safe_builtins() -> dict[str, object]:
    return {
        "__import__": _safe_import,
        "dict": dict,
        "float": float,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "str": str,
        "ValueError": ValueError,
    }


def _safe_import(name: str, globals: object = None, locals: object = None, fromlist: tuple[str, ...] = (), level: int = 0) -> object:
    root = name.split(".")[0]
    if level != 0 or root not in SAFE_IMPORTS:
        raise ImportError(f"Import is not allowed: {name}")
    return __import__(name, globals, locals, fromlist, level)


def _metadata_value(metadata: dict[str, object], key: str, default: str) -> str:
    value = metadata.get(key, default)
    if value is None:
        return ""
    return str(value)


def _latest_user_message(state: MetadataAgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if message.get("role") == "user":
            return message.get("content", "")
    return ""


def _message_approves(message: str) -> bool:
    lower = message.lower()
    if any(blocker in lower for blocker in ["do not approve", "don't approve", "not approved", "not ready"]):
        return False
    return any(token in lower for token in ["approve", "approved", "looks good", "satisfied", "write outputs", "run final"])
