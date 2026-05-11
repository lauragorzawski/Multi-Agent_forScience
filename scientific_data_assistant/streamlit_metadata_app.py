"""Guided Streamlit interface for the metadata-agent API."""

from __future__ import annotations

from typing import Any

import httpx

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover - shown when run directly without deps
    raise SystemExit("Streamlit is not installed. Run `pip install -r requirements.txt`.") from exc


DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_INPUT_DIR = "raw_data/20250708"
DEFAULT_OUTPUT_DIR = "fgt_output_api"
DEFAULT_PATTERN = "material_sample_position_thickness_date_setting"
DEFAULT_PATTERN_EXAMPLE = (
    "FGT_1_1_20nm_20250708_0p1.txt means material FGT, sample position 1_1, "
    "thickness 20nm, date 2025-07-08, setting 0.1."
)
OVERVIEW_COLUMNS = [
    "file",
    "sample_id",
    "material",
    "thickness_nm",
    "measurement_date",
    "setting_value",
    "position_1",
    "position_2",
    "replicate_index",
    "parse_status",
    "notes",
]


def main() -> None:
    st.set_page_config(page_title="Metadata Agent", layout="wide")
    _ensure_state()

    st.title("Metadata Agent")
    st.write("I will help you turn `.xy` and `.txt` filenames into a consistent metadata table linked to your files.")

    with st.container(border=True):
        st.subheader("Agent Question")
        st.write("Where is your data stored?")
        st.write("Then tell me the pattern of the metadata in your filenames and give one example.")

    with st.sidebar:
        st.header("Connection")
        api_url = st.text_input("API URL", DEFAULT_API_URL)
        if st.button("Reset conversation"):
            st.session_state.metadata_agent_state = {}
            st.session_state.last_response = {}
            st.rerun()

    input_dir = st.text_input("Raw data folder", DEFAULT_INPUT_DIR)
    output_dir = st.text_input("Output folder", DEFAULT_OUTPUT_DIR)

    pattern_col, example_col = st.columns(2)
    with pattern_col:
        metadata_pattern = st.text_area(
            "What is the filename metadata pattern?",
            DEFAULT_PATTERN,
            help="Example: material_sample_position_thickness_date_setting",
        )
    with example_col:
        pattern_example = st.text_area(
            "Give one filename example and explain it",
            DEFAULT_PATTERN_EXAMPLE,
            help="Tell the agent what each filename part means.",
        )

    button_col_1, button_col_2 = st.columns([1, 1])
    with button_col_1:
        if st.button("Parse and Show Overview", type="primary", use_container_width=True):
            _run_turn(api_url, input_dir, output_dir, metadata_pattern, pattern_example, "")
    with button_col_2:
        if st.button("Approve and Write Outputs", use_container_width=True):
            _run_turn(api_url, input_dir, output_dir, metadata_pattern, pattern_example, "approve and write outputs")

    feedback = st.text_area(
        "Feedback to the agent",
        placeholder="Example: The 0p1 or 1p0 part should be setting_value, not exposure_time_s.",
    )
    if st.button("Send Feedback"):
        _run_turn(api_url, input_dir, output_dir, metadata_pattern, pattern_example, feedback)

    _render_response()


def _ensure_state() -> None:
    if "metadata_agent_state" not in st.session_state:
        st.session_state.metadata_agent_state = {}
    if "last_response" not in st.session_state:
        st.session_state.last_response = {}


def _run_turn(
    api_url: str,
    input_dir: str,
    output_dir: str,
    metadata_pattern: str,
    pattern_example: str,
    user_message: str,
) -> None:
    payload = {
        "input_dir": input_dir,
        "output_dir": output_dir,
        "metadata_pattern": metadata_pattern,
        "pattern_example": pattern_example,
        "user_message": user_message,
        "state": st.session_state.metadata_agent_state,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(api_url.rstrip("/") + "/metadata-agent/turn", json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        st.session_state.last_response = {"assistant_message": f"API call failed: {exc}", "table_overview": []}
        return

    st.session_state.last_response = data
    st.session_state.metadata_agent_state = data.get("state", {})


def _render_response() -> None:
    response = st.session_state.last_response
    state = response.get("state", {})
    assistant_message = response.get("assistant_message", "")
    if assistant_message:
        with st.chat_message("assistant"):
            st.markdown(assistant_message)

    table_overview = response.get("table_overview", [])
    if table_overview:
        st.subheader("File and Parameter Overview")
        st.dataframe(_ordered_rows(table_overview), use_container_width=True, hide_index=True)
    else:
        st.info("No overview yet. Fill in the folder and filename pattern, then click Parse and Show Overview.")

    unclear_items = response.get("unclear_items", state.get("unclear_items", []))
    if unclear_items:
        with st.expander("What is unclear?", expanded=True):
            for item in unclear_items:
                st.write(f"- {item}")

    suggestions = response.get("suggested_user_messages", [])
    if suggestions:
        with st.expander("Possible next messages", expanded=True):
            for suggestion in suggestions:
                st.code(suggestion)

    run_summary = state.get("run_summary", "")
    if run_summary:
        if state.get("approved") and not state.get("validation_errors"):
            st.success(run_summary)
        else:
            st.caption(run_summary)

    errors = state.get("validation_errors", [])
    for error in errors:
        st.error(error)

    preview_rows = state.get("preview_rows", [])
    if preview_rows:
        with st.expander("Full metadata table preview"):
            st.dataframe(preview_rows, use_container_width=True, hide_index=True)

    generated_code = state.get("generated_code", "")
    if generated_code:
        with st.expander("Generated extraction code"):
            st.code(generated_code, language="python")


def _ordered_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    for row in rows:
        columns = [column for column in OVERVIEW_COLUMNS if column in row]
        columns.extend(column for column in row if column not in columns)
        ordered.append({column: row.get(column, "") for column in columns})
    return ordered


if __name__ == "__main__":
    main()
