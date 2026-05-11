"""Dash interface for the conversational metadata agent API."""

from __future__ import annotations

from typing import Any

import httpx

try:
    from dash import Dash, Input, Output, State, callback_context, dash_table, dcc, html
except ImportError as exc:  # pragma: no cover - shown when run directly without deps
    raise SystemExit("Dash is not installed. Run `pip install -r requirements.txt`.") from exc


DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_INPUT_DIR = "raw_data/20250708"
DEFAULT_OUTPUT_DIR = "fgt_output_api"
DEFAULT_PATTERN = "material_sample_position_thickness_date_setting"
DEFAULT_PATTERN_EXAMPLE = "FGT_1_1_20nm_20250708_0p1.txt means material FGT, sample position 1_1, thickness 20nm, date 2025-07-08, setting 0.1."


def create_dash_app() -> Dash:
    app = Dash(__name__, title="Metadata Agent")
    app.layout = html.Div(
        [
            dcc.Store(id="agent-state", data={}),
            html.Div(
                [
                    html.H1("Metadata Agent"),
                    html.P("I will help you turn .xy/.txt filenames into a consistent metadata table linked to your files."),
                ],
                className="header",
            ),
            html.Div(
                [
                    html.H2("Agent Question"),
                    html.P("Where is your data stored? Enter the folder path below."),
                    html.P("Then tell me the filename pattern and give one example, so I can parse the metadata transparently."),
                ],
                className="agent-question",
            ),
            html.Div(
                [
                    _field("API URL", "api-url", DEFAULT_API_URL),
                    _field("Raw data folder", "input-dir", DEFAULT_INPUT_DIR),
                    _field("Output folder", "output-dir", DEFAULT_OUTPUT_DIR),
                ],
                className="control-grid",
            ),
            html.Div(
                [
                    _textarea(
                        "Filename metadata pattern",
                        "metadata-pattern",
                        DEFAULT_PATTERN,
                        "Example: material_sample_thickness_date_setting",
                    ),
                    _textarea(
                        "One filename example and what it means",
                        "pattern-example",
                        DEFAULT_PATTERN_EXAMPLE,
                        "Example: FGT_1_1_20nm_20250708_0p1.txt means ...",
                    ),
                ],
                className="pattern-grid",
            ),
            html.Div(
                [
                    html.Button("Parse and Show Overview", id="scan-button", n_clicks=0, className="primary"),
                    html.Button("Approve and Write Outputs", id="approve-button", n_clicks=0),
                ],
                className="button-row",
            ),
            html.Div(
                [
                    dcc.Textarea(
                        id="feedback",
                        placeholder="Example: The 0p1 or 1p0 part should be setting_value, not exposure_time_s.",
                        value="",
                    ),
                    html.Button("Send Feedback", id="feedback-button", n_clicks=0),
                ],
                className="feedback-row",
            ),
            html.Div(id="assistant-message", className="assistant-message"),
            html.Div(id="suggestions", className="suggestions"),
            html.H2("File and Parameter Overview"),
            dash_table.DataTable(
                id="overview-table",
                data=[],
                columns=[],
                page_size=12,
                sort_action="native",
                filter_action="native",
                style_table={"overflowX": "auto"},
                style_cell={
                    "fontFamily": "system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
                    "fontSize": "13px",
                    "padding": "8px",
                    "textAlign": "left",
                    "whiteSpace": "normal",
                    "height": "auto",
                    "minWidth": "100px",
                    "maxWidth": "340px",
                },
                style_header={"fontWeight": "700", "backgroundColor": "#f4f6f8"},
            ),
            html.H2("Full Response Status"),
            html.Pre(id="status-json", className="status-json"),
        ],
        className="page",
    )
    app.index_string = _index_string()
    _register_callbacks(app)
    return app


def _field(label: str, component_id: str, value: str) -> html.Label:
    return html.Label([html.Span(label), dcc.Input(id=component_id, value=value, type="text")])


def _textarea(label: str, component_id: str, value: str, placeholder: str) -> html.Label:
    return html.Label([html.Span(label), dcc.Textarea(id=component_id, value=value, placeholder=placeholder)])


def _register_callbacks(app: Dash) -> None:
    @app.callback(
        Output("agent-state", "data"),
        Output("assistant-message", "children"),
        Output("suggestions", "children"),
        Output("overview-table", "data"),
        Output("overview-table", "columns"),
        Output("status-json", "children"),
        Input("scan-button", "n_clicks"),
        Input("feedback-button", "n_clicks"),
        Input("approve-button", "n_clicks"),
        State("api-url", "value"),
        State("input-dir", "value"),
        State("output-dir", "value"),
        State("metadata-pattern", "value"),
        State("pattern-example", "value"),
        State("feedback", "value"),
        State("agent-state", "data"),
        prevent_initial_call=True,
    )
    def agent_turn(
        scan_clicks: int,
        feedback_clicks: int,
        approve_clicks: int,
        api_url: str,
        input_dir: str,
        output_dir: str,
        metadata_pattern: str,
        pattern_example: str,
        feedback: str,
        agent_state: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], Any, Any, list[dict[str, str]], list[dict[str, str]], str]:
        del scan_clicks, feedback_clicks, approve_clicks
        trigger = callback_context.triggered[0]["prop_id"].split(".")[0] if callback_context.triggered else "scan-button"
        if trigger == "approve-button":
            user_message = "approve and write outputs"
        elif trigger == "feedback-button":
            user_message = feedback or ""
        else:
            user_message = ""

        try:
            response = _call_metadata_agent_api(
                api_url,
                input_dir,
                output_dir,
                metadata_pattern,
                pattern_example,
                user_message,
                agent_state or {},
            )
        except Exception as exc:
            message = html.Div([html.Strong("API call failed: "), html.Span(str(exc))], className="error")
            return agent_state or {}, message, "", [], [], ""

        next_state = response.get("state", {})
        table_overview = response.get("table_overview", [])
        suggestions = response.get("suggested_user_messages", [])
        columns = [{"name": column, "id": column} for column in _ordered_columns(table_overview)]
        assistant_message = response.get("assistant_message", "")
        return (
            next_state,
            _message_block(assistant_message),
            _suggestion_block(suggestions),
            table_overview,
            columns,
            _status_text(response),
        )


def _call_metadata_agent_api(
    api_url: str,
    input_dir: str,
    output_dir: str,
    metadata_pattern: str,
    pattern_example: str,
    user_message: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    url = api_url.rstrip("/") + "/metadata-agent/turn"
    payload = {
        "input_dir": input_dir,
        "output_dir": output_dir,
        "metadata_pattern": metadata_pattern,
        "pattern_example": pattern_example,
        "user_message": user_message,
        "state": state,
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


def _ordered_columns(rows: list[dict[str, str]]) -> list[str]:
    preferred = [
        "file",
        "sample_id",
        "material",
        "thickness_nm",
        "exposure_time_s",
        "measurement_type",
        "measurement_date",
        "setting_value",
        "position_1",
        "position_2",
        "replicate_index",
        "parse_status",
        "notes",
    ]
    seen: list[str] = []
    for column in preferred:
        if any(column in row for row in rows):
            seen.append(column)
    for row in rows:
        for column in row:
            if column not in seen:
                seen.append(column)
    return seen


def _message_block(message: str) -> html.Div:
    if not message:
        return html.Div("No assistant message yet.")
    return html.Div([html.H2("Agent Message"), html.Pre(message)])


def _suggestion_block(suggestions: list[str]) -> html.Div:
    if not suggestions:
        return html.Div()
    return html.Div(
        [
            html.H2("Possible Next Messages"),
            html.Ul([html.Li(message) for message in suggestions]),
        ]
    )


def _status_text(response: dict[str, Any]) -> str:
    state = response.get("state", {})
    summary = state.get("run_summary", "")
    errors = state.get("validation_errors", [])
    unclear = response.get("unclear_items", state.get("unclear_items", []))
    approved = state.get("approved", False)
    lines = [
        f"approved: {approved}",
        f"summary: {summary}",
        f"errors: {errors or 'none'}",
        f"unclear items: {unclear or 'none'}",
    ]
    return "\n".join(lines)


def _index_string() -> str:
    return """<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            body {
                margin: 0;
                background: #f7f8fa;
                color: #1f2933;
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }
            .page {
                max-width: 1280px;
                margin: 0 auto;
                padding: 28px;
            }
            .header h1 {
                margin: 0 0 6px;
                font-size: 30px;
            }
            .header p {
                margin: 0 0 24px;
                color: #566372;
            }
            .control-grid {
                display: grid;
                grid-template-columns: repeat(3, minmax(180px, 1fr));
                gap: 14px;
                margin-bottom: 14px;
            }
            label span {
                display: block;
                margin-bottom: 6px;
                font-size: 13px;
                font-weight: 700;
            }
            input, textarea {
                box-sizing: border-box;
                width: 100%;
                border: 1px solid #c8d0d9;
                border-radius: 6px;
                padding: 10px 12px;
                font: inherit;
                background: white;
            }
            textarea {
                min-height: 82px;
                resize: vertical;
            }
            .button-row, .feedback-row {
                display: flex;
                gap: 10px;
                align-items: stretch;
                margin: 12px 0;
            }
            .feedback-row textarea {
                flex: 1;
            }
            button {
                border: 1px solid #a8b3c2;
                background: white;
                color: #17212f;
                border-radius: 6px;
                padding: 10px 14px;
                font-weight: 700;
                cursor: pointer;
            }
            button.primary {
                background: #1463ff;
                border-color: #1463ff;
                color: white;
            }
            .assistant-message, .suggestions, .status-json {
                background: white;
                border: 1px solid #d9e0e8;
                border-radius: 8px;
                padding: 14px;
                margin: 16px 0;
            }
            .agent-question {
                background: #eef5ff;
                border: 1px solid #bdd5ff;
                border-radius: 8px;
                padding: 14px;
                margin: 0 0 16px;
            }
            .agent-question h2 {
                margin-top: 0;
            }
            .agent-question p {
                margin: 6px 0;
            }
            .pattern-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 14px;
                margin-bottom: 14px;
            }
            h2 {
                margin: 22px 0 10px;
                font-size: 18px;
            }
            pre {
                white-space: pre-wrap;
                margin: 0;
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            }
            .error {
                color: #9b1c1c;
            }
            @media (max-width: 780px) {
                .control-grid, .pattern-grid, .button-row, .feedback-row {
                    grid-template-columns: 1fr;
                    display: grid;
                }
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>"""


app = create_dash_app()
