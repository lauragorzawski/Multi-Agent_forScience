"""Phase 4: LangGraph-orchestrated, evidence-citing discussion agents."""

from __future__ import annotations

import json
import os
import statistics
from pathlib import Path
from typing import Any, TypedDict

from .comments import generate_quality_comments, load_comments
from .contracts import ProjectPaths
from .plotting import load_metadata, load_trace, summarize_traces, write_plot_summary


class AgentState(TypedDict, total=False):
    project_dir: str
    question: str
    inspection: str
    trends: str
    quality: str
    answer: str
    citations: list[str]


def run_discussion(project_dir: Path, question: str) -> AgentState:
    paths = ProjectPaths(project_dir.expanduser().resolve())
    state: AgentState = {"project_dir": str(paths.root), "question": question, "citations": []}

    try:
        from langgraph.graph import END, StateGraph
    except ImportError:
        for node in (data_inspector_agent, trend_analyst_agent, quality_critic_agent, discussion_agent):
            state = node(state)
        return state

    graph = StateGraph(AgentState)
    graph.add_node("data_inspector", data_inspector_agent)
    graph.add_node("trend_analyst", trend_analyst_agent)
    graph.add_node("quality_critic", quality_critic_agent)
    graph.add_node("discussion", discussion_agent)
    graph.set_entry_point("data_inspector")
    graph.add_edge("data_inspector", "trend_analyst")
    graph.add_edge("trend_analyst", "quality_critic")
    graph.add_edge("quality_critic", "discussion")
    graph.add_edge("discussion", END)
    app = graph.compile()
    return app.invoke(state)


def data_inspector_agent(state: AgentState) -> AgentState:
    paths = _paths(state)
    metadata = load_metadata(paths.metadata_table)
    ok = sum(row.get("parse_status") == "ok" for row in metadata)
    warnings = sum(row.get("parse_status") == "warning" for row in metadata)
    failed = sum(row.get("parse_status") == "failed" for row in metadata)
    missing_material = sum(row.get("material") == "missing" for row in metadata)

    state["inspection"] = (
        f"Data Inspector Agent: found {len(metadata)} metadata rows; "
        f"{ok} ok, {warnings} warnings, {failed} failed parses; "
        f"{missing_material} rows missing material."
    )
    state.setdefault("citations", []).append("metadata_table.csv")
    return state


def trend_analyst_agent(state: AgentState) -> AgentState:
    paths = _paths(state)
    summaries = summarize_traces(paths)
    usable = [row for row in summaries if row.get("parse_status") in {"ok", "warning"} and row.get("n_points", 0)]

    if not usable:
        state["trends"] = "Trend Analyst Agent: no usable parsed traces are available for quantitative trend analysis."
        return state

    strongest = max(usable, key=lambda row: _float_or_low(row.get("y_peak")))
    by_material = _group_numeric(usable, "material", "y_peak")
    by_thickness = _group_numeric(usable, "thickness_nm", "y_peak")
    trend_lines = [
        "Trend Analyst Agent:",
        f"- Strongest peak y is `{_format(strongest.get('y_peak'))}` from file_id `{strongest['file_id']}`.",
        f"- Material groups by mean peak y: {_format_groups(by_material)}.",
    ]
    if by_thickness:
        trend_lines.append(f"- Thickness groups by mean peak y: {_format_groups(by_thickness)}.")
    else:
        trend_lines.append("- Thickness trend could not be computed because numeric thickness metadata is missing.")

    state["trends"] = "\n".join(trend_lines)
    state.setdefault("citations", []).append(str(paths.plot_summary.name))
    write_plot_summary(paths)
    return state


def quality_critic_agent(state: AgentState) -> AgentState:
    paths = _paths(state)
    additions = generate_quality_comments(paths)
    write_plot_summary(paths)
    comments = load_comments(paths.comments)
    summaries = summarize_traces(paths)

    peaks = [(row["file_id"], float(row["y_peak"])) for row in summaries if _is_number(row.get("y_peak"))]
    outlier_note = ""
    if len(peaks) >= 3:
        values = [value for _, value in peaks]
        mean = statistics.fmean(values)
        stdev = statistics.pstdev(values)
        outliers = [file_id for file_id, value in peaks if stdev and abs(value - mean) > 2 * stdev]
        if outliers:
            outlier_note = f" Potential peak outliers by simple 2-sigma rule: {', '.join(outliers)}."

    state["quality"] = (
        f"Quality Critic Agent: {len(comments)} total comments/quality notes; "
        f"{len(additions)} new quality notes generated this run."
        f"{outlier_note}"
    )
    state.setdefault("citations", []).append("comments.csv")
    return state


def discussion_agent(state: AgentState) -> AgentState:
    question = state.get("question", "")
    citations = sorted(set(state.get("citations", [])))
    deterministic_answer = [
        f"Question: {question}",
        "",
        state.get("inspection", ""),
        "",
        state.get("trends", ""),
        "",
        state.get("quality", ""),
        "",
        "Discussion Agent:",
        "- Treat rows with failed parsing or missing metadata as review-first, not conclusion-ready.",
        "- Use material/thickness/exposure comparisons only where those metadata fields are present.",
        "- A good next experiment is to repeat suspicious or commented measurements, then compare peak/mean y under the same material and thickness group.",
        "",
        "Evidence used: " + ", ".join(citations),
    ]
    state["answer"] = _maybe_polish_with_llm("\n".join(line for line in deterministic_answer if line is not None), citations)
    _paths(state).phase4_report.write_text(_phase4_report(state), encoding="utf-8")
    return state


def _paths(state: AgentState) -> ProjectPaths:
    return ProjectPaths(Path(state["project_dir"]))


def _phase4_report(state: AgentState) -> str:
    return "\n".join(
        [
            "# Phase 4 Report",
            "",
            "LangGraph coordinates four deterministic, evidence-citing agents:",
            "",
            "- Data Inspector Agent: checks row counts, parse status, and metadata completeness.",
            "- Trend Analyst Agent: computes peak and group summaries from parsed traces.",
            "- Quality Critic Agent: creates quality comments and flags risky rows.",
            "- Discussion Agent: combines evidence into a user-facing answer.",
            "",
            "## Latest Answer",
            "",
            state.get("answer", ""),
        ]
    )


def _group_numeric(rows: list[dict[str, Any]], group_field: str, value_field: str) -> dict[str, float]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        group = str(row.get(group_field) or "missing")
        if group == "missing" or not _is_number(row.get(value_field)):
            continue
        grouped.setdefault(group, []).append(float(row[value_field]))
    return {group: statistics.fmean(values) for group, values in grouped.items()}


def _format_groups(groups: dict[str, float]) -> str:
    if not groups:
        return "not enough metadata"
    ordered = sorted(groups.items(), key=lambda item: item[1], reverse=True)
    return "; ".join(f"{group}={_format(value)}" for group, value in ordered)


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _float_or_low(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def _format(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.4g}"


def _maybe_polish_with_llm(answer: str, citations: list[str]) -> str:
    """Optionally polish the final answer if OpenAI credentials are configured.

    The numerical evidence is still computed deterministically before this step.
    If the optional dependency or API key is missing, the deterministic answer is
    returned unchanged.
    """

    _load_local_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return answer
    if api_key.startswith(("replace_", "paste_", "your_")):
        return answer + "\n\nLLM polish skipped: `.env` still contains a placeholder API key."

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return answer + "\n\nLLM polish skipped: install `langchain-openai` to use OPENAI_API_KEY."

    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    prompt = (
        "Rewrite this scientific data assistant answer to be concise, clear, and judge-friendly. "
        "Do not add new facts, numbers, files, or claims. Preserve the evidence citations exactly: "
        f"{', '.join(citations)}.\n\n"
        f"{answer}"
    )
    try:
        response = ChatOpenAI(model=model, temperature=0, api_key=api_key).invoke(prompt)
    except Exception as exc:  # pragma: no cover - depends on network/API availability
        return answer + f"\n\nLLM polish skipped: {exc}"
    return str(response.content)


def _load_local_env() -> None:
    """Load simple KEY=VALUE pairs from the nearest .env file.

    This avoids adding a runtime dependency just to support local hackathon use.
    Existing environment variables win over values in .env, unless the existing
    value is one of our obvious placeholders.
    """

    for folder in [Path.cwd(), *Path.cwd().parents]:
        env_path = folder / ".env"
        if not env_path.exists():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            current = os.environ.get(key, "")
            current_is_placeholder = current.startswith(("replace_", "paste_", "your_"))
            if key and (key not in os.environ or current_is_placeholder):
                os.environ[key] = value
        return


def export_state_json(state: AgentState) -> str:
    return json.dumps(state, indent=2)
