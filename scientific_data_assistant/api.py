"""HTTP API for the scientific data assistant agents."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .metadata_agent import MetadataAgentState, run_metadata_agent_turn

try:
    from fastapi import FastAPI
except ImportError:  # pragma: no cover - optional server dependency
    FastAPI = None  # type: ignore[assignment]


class MetadataAgentTurnRequest(BaseModel):
    """Request body for one conversational metadata-agent turn."""

    input_dir: str | None = Field(default=None, description="Folder containing raw .xy/.txt files.")
    output_dir: str | None = Field(default=None, description="Folder where approved Phase 1 outputs should be written.")
    metadata_pattern: str | None = Field(
        default=None,
        description="User description of how filename parts map to metadata parameters.",
    )
    pattern_example: str | None = Field(
        default=None,
        description="One representative filename example and what each part means.",
    )
    use_model_agent: bool = Field(
        default=False,
        description="Use an optional LLM call to interpret pattern/example/feedback. Falls back to deterministic rules if unavailable.",
    )
    user_message: str = Field(
        default="",
        description=(
            "Conversation input. Use an empty string to scan/preview, feedback such as "
            "`Please extract the date from the filename.`, or `approve and write outputs`."
        ),
    )
    state: dict[str, Any] = Field(
        default_factory=dict,
        description="State returned from the previous turn. Send it back so the agent remembers the conversation.",
    )


class MetadataAgentTurnResponse(BaseModel):
    """Response body containing the updated metadata-agent state."""

    state: MetadataAgentState
    table_overview: list[dict[str, str]] = Field(default_factory=list)
    unclear_items: list[str] = Field(default_factory=list)
    suggested_user_messages: list[str] = Field(default_factory=list)
    assistant_message: str = ""
    model_status: str = ""


def run_metadata_agent_api_turn(payload: MetadataAgentTurnRequest | dict[str, Any]) -> dict[str, Any]:
    """Run one metadata-agent turn from an API-style payload."""

    request = payload if isinstance(payload, MetadataAgentTurnRequest) else MetadataAgentTurnRequest.model_validate(payload)
    state: MetadataAgentState = dict(request.state)
    if request.input_dir is not None:
        state["input_dir"] = request.input_dir
    if request.output_dir is not None:
        state["output_dir"] = request.output_dir
    if request.metadata_pattern is not None:
        state["metadata_pattern"] = request.metadata_pattern
    if request.pattern_example is not None:
        state["pattern_example"] = request.pattern_example
    state["use_model_agent"] = request.use_model_agent

    next_state = run_metadata_agent_turn(state, request.user_message)
    return {
        "state": next_state,
        "table_overview": next_state.get("table_overview", []),
        "unclear_items": next_state.get("unclear_items", []),
        "suggested_user_messages": next_state.get("suggested_user_messages", []),
        "assistant_message": _latest_assistant_message(next_state),
        "model_status": next_state.get("model_status", ""),
    }


def _latest_assistant_message(state: MetadataAgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if message.get("role") == "assistant":
            return message.get("content", "")
    return ""


def create_app() -> Any:
    """Create the FastAPI app, if FastAPI is installed."""

    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Run `pip install -r requirements.txt`.")

    app = FastAPI(
        title="Scientific Data Assistant API",
        version="0.1.0",
        description="API for the conversational metadata builder and scientific data assistant workflow.",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/metadata-agent/turn", response_model=MetadataAgentTurnResponse)
    def metadata_agent_turn(request: MetadataAgentTurnRequest) -> dict[str, Any]:
        return run_metadata_agent_api_turn(request)

    return app


app = create_app() if FastAPI is not None else None
