"""Streamlit dashboard for the full hackathon demo."""

from __future__ import annotations

from pathlib import Path

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover - shown when run directly without deps
    raise SystemExit("Streamlit is not installed. Run `pip install -r requirements.txt`.") from exc

from scientific_data_assistant.agents import run_discussion
from scientific_data_assistant.comments import add_comment, generate_quality_comments, load_comments
from scientific_data_assistant.contracts import ProjectPaths
from scientific_data_assistant.ingestion import run_phase1
from scientific_data_assistant.metadata_agent import run_metadata_agent_turn
from scientific_data_assistant.plotting import load_metadata, make_plotly_overlay, make_plotly_summary, summarize_traces, write_plot_summary


def main() -> None:
    st.set_page_config(page_title="Scientific Data Assistant", layout="wide")
    st.title("Scientific Data Assistant")

    default_project = Path("demo_output")
    project_dir = Path(st.sidebar.text_input("Project output folder", str(default_project)))
    paths = ProjectPaths(project_dir)

    tabs = st.tabs(["Metadata Agent", "Data Review", "Plots", "Comments", "Agent Discussion"])

    with tabs[0]:
        st.subheader("Phase 1: Conversational Metadata Builder")
        agent_input_dir = Path(st.text_input("Raw data folder", "sample_data", key="metadata_agent_input_dir"))
        agent_output_dir = Path(st.text_input("Agent output folder", str(project_dir), key="metadata_agent_output_dir"))

        if "metadata_agent_state" not in st.session_state:
            st.session_state.metadata_agent_state = {}
        st.session_state.metadata_agent_state.update({"input_dir": str(agent_input_dir), "output_dir": str(agent_output_dir)})

        button_cols = st.columns(2)
        if button_cols[0].button("Scan and preview"):
            st.session_state.metadata_agent_state = run_metadata_agent_turn(st.session_state.metadata_agent_state, "")
        if button_cols[1].button("Approve and write outputs"):
            st.session_state.metadata_agent_state = run_metadata_agent_turn(st.session_state.metadata_agent_state, "approve and write outputs")

        feedback = st.text_area("Feedback", key="metadata_agent_feedback", placeholder="Example: include the date and setting value from the filename")
        if st.button("Send feedback"):
            st.session_state.metadata_agent_state = run_metadata_agent_turn(st.session_state.metadata_agent_state, feedback)

        agent_state = st.session_state.metadata_agent_state
        for message in agent_state.get("messages", [])[-6:]:
            with st.chat_message(message.get("role", "assistant")):
                st.markdown(message.get("content", ""))

        discovered_files = agent_state.get("discovered_files", [])
        if discovered_files:
            st.caption(f"Discovered {len(discovered_files)} .xy/.txt files")
            st.dataframe([{"file": Path(path).name} for path in discovered_files[:20]], use_container_width=True)

        proposed_columns = agent_state.get("proposed_columns", [])
        if proposed_columns:
            st.caption("Proposed dataframe columns")
            st.write(", ".join(proposed_columns))

        errors = agent_state.get("validation_errors", [])
        for error in errors:
            st.error(error)

        generated_code = agent_state.get("generated_code", "")
        if generated_code:
            with st.expander("Generated extraction code", expanded=False):
                st.code(generated_code, language="python")

        table_overview = agent_state.get("table_overview", [])
        if table_overview:
            st.caption("File and parameter overview")
            st.dataframe(table_overview, use_container_width=True)

        suggested_messages = agent_state.get("suggested_user_messages", [])
        if suggested_messages:
            st.caption("Possible next messages")
            st.write("\n".join(f"- {message}" for message in suggested_messages))

        preview_rows = agent_state.get("preview_rows", [])
        if preview_rows:
            with st.expander("Full dataframe preview", expanded=False):
                st.dataframe(preview_rows, use_container_width=True)

        if agent_state.get("run_summary"):
            st.success(agent_state["run_summary"] if agent_state.get("approved") and not errors else agent_state["run_summary"])

    with tabs[1]:
        st.subheader("Phase 1: Data Sorting and Metadata Extraction")
        input_dir = Path(st.text_input("Folder containing .xy/.txt files", "sample_data"))
        if st.button("Run Phase 1 ingestion"):
            run_phase1(input_dir, project_dir)
            st.success(f"Wrote outputs to {project_dir}")

        metadata = load_metadata(paths.metadata_table)
        if metadata:
            st.dataframe(metadata, use_container_width=True)
        else:
            st.info("No metadata table found yet. Run Phase 1 first.")

    with tabs[2]:
        st.subheader("Phase 2: Plotting Over Parameters")
        if st.button("Refresh plot summary"):
            write_plot_summary(paths)
            st.success("Plot summary refreshed.")

        metadata = load_metadata(paths.metadata_table)
        if metadata:
            color_by = st.selectbox("Color/group by", ["material", "thickness_nm", "exposure_time_s", "measurement_type", "sample_id"])
            mode = st.radio("Plot mode", ["Overlay traces", "Summary scatter"], horizontal=True)
            if mode == "Overlay traces":
                st.plotly_chart(make_plotly_overlay(paths, color_by=color_by), use_container_width=True)
            else:
                x_field = st.selectbox("X parameter", ["thickness_nm", "exposure_time_s"])
                y_field = st.selectbox("Y summary", ["y_peak", "y_mean"])
                st.plotly_chart(make_plotly_summary(paths, x_field=x_field, y_field=y_field, color_by=color_by), use_container_width=True)
            st.dataframe(summarize_traces(paths), use_container_width=True)
        else:
            st.info("No parsed data available yet.")

    with tabs[3]:
        st.subheader("Phase 3: Hover Comments and Data Quality Notes")
        metadata = load_metadata(paths.metadata_table)
        file_ids = [row["file_id"] for row in metadata]

        if st.button("Generate quality comments"):
            additions = generate_quality_comments(paths)
            st.success(f"Generated {len(additions)} quality comments.")

        if file_ids:
            file_id = st.selectbox("File ID", file_ids)
            point_index = st.text_input("Point index, optional", "")
            comment = st.text_area("Comment", "higher error because measurement system was damaged")
            comment_type = st.selectbox("Comment type", ["manual", "quality", "outlier", "agent"])
            if st.button("Add comment"):
                add_comment(paths, file_id=file_id, point_index=point_index, comment=comment, comment_type=comment_type)
                st.success("Comment added.")

        st.dataframe(load_comments(paths.comments), use_container_width=True)

    with tabs[4]:
        st.subheader("Phase 4: Multi-Agent Scientific Discussion")
        question = st.text_area(
            "Ask a scientific question",
            "Which sample has the strongest signal, what metadata trend is visible, and what should we inspect next?",
        )
        if st.button("Run agents"):
            state = run_discussion(project_dir, question)
            st.markdown(state.get("answer", "No answer produced."))


if __name__ == "__main__":
    main()
