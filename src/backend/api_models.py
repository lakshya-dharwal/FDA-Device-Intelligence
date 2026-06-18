"""
Pydantic request and response models for the backend API.
"""

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str


class ToolCallResult(BaseModel):
    tool_name: str
    tool_input: dict[str, Any]
    tool_output: dict[str, Any]
    duration_ms: float = 0.0


class QueryResponse(BaseModel):
    answer: str
    tools_called: list[str]
    tool_results: list[ToolCallResult] = Field(default_factory=list)
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
