"""
Claude agentic loop — sends user queries to Claude with FDA tool definitions,
then executes any tool calls Claude requests against the real OpenFDA API,
feeding results back until Claude produces a final answer.

The loop is bounded by `settings.max_agent_iterations` so a misbehaving model
can never run up unbounded API cost.
"""

from __future__ import annotations

import time
from typing import Any

import anthropic

from src.config import settings
from src.logging_config import get_logger
from src.mcp_server.fda_tools import (
    get_adverse_events,
    get_device_classifications,
    search_device_recalls,
)

logger = get_logger(__name__)


class ClaudeClientError(RuntimeError):
    """Raised when the agentic loop cannot complete (auth, billing, API errors)."""


SYSTEM_PROMPT = """You are an FDA Device Intelligence Assistant. You help clinicians,
researchers, and regulators understand FDA medical device safety data including recalls,
adverse events, and device classifications. When answering questions, always use the
provided tools to fetch real, up-to-date FDA data rather than relying on your training
data. Be precise, cite the data you retrieved, and present findings in a structured,
clinically useful format."""

# Tool definitions in Anthropic tool_use format.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_device_recalls",
        "description": (
            "Search FDA device recall database by product description or reason for recall. "
            "Returns recall date, recalling firm, classification (Class I/II/III), "
            "product description, and reason for recall."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "Device name, product type, or keyword to search recalls for.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of results to return (default 10).",
                    "default": 10,
                },
            },
            "required": ["search_term"],
        },
    },
    {
        "name": "get_adverse_events",
        "description": (
            "Retrieve adverse event (MAUDE) reports from the FDA for a specific medical device. "
            "Returns event date, device brand name, event type, patient outcome, and narrative."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "Brand name or common name of the medical device.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of results to return (default 10).",
                    "default": 10,
                },
            },
            "required": ["device_name"],
        },
    },
    {
        "name": "get_device_classifications",
        "description": (
            "Look up FDA device classification (Class I, II, or III) for a medical device. "
            "Returns device name, risk class, regulation number, product code, and medical specialty."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "Name of the medical device to classify.",
                },
            },
            "required": ["device_name"],
        },
    },
]

# Map tool names Claude will call → actual Python functions.
TOOL_MAP = {
    "search_device_recalls": search_device_recalls,
    "get_adverse_events": get_adverse_events,
    "get_device_classifications": get_device_classifications,
}

# Cached Anthropic client so we don't rebuild it on every request.
_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    """
    Return a cached Anthropic client, constructing it on first use.

    Raises ClaudeClientError with a clear message if no API key is configured,
    rather than failing deep inside the SDK at call time.
    """
    global _client
    if not settings.has_anthropic_key:
        raise ClaudeClientError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env file."
        )
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _extract_text(content: list) -> str:
    """Concatenate all text blocks from a Claude response into a single string."""
    return "".join(getattr(block, "text", "") for block in content if getattr(block, "text", ""))


def _calc_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost from token counts using configured per-MTok pricing."""
    return (
        (input_tokens / 1_000_000) * settings.input_cost_per_mtok
        + (output_tokens / 1_000_000) * settings.output_cost_per_mtok
    )


def run_fda_query(query: str, client: anthropic.Anthropic | None = None) -> dict:
    """
    Run an agentic Claude query against the FDA tools.

    Args:
        query: The user's natural-language question.
        client: Optional Anthropic client (injected in tests); defaults to the
            cached process client from get_client().

    Returns a dict with: answer, tools_called, input_tokens, output_tokens,
    cost_usd, latency_ms.

    Raises:
        ClaudeClientError: if the Anthropic API call fails (auth, billing,
            rate limit, overload) or the loop exceeds max_agent_iterations.
    """
    client = client or get_client()
    start_time = time.time()

    messages: list[dict[str, Any]] = [{"role": "user", "content": query}]
    tools_called: list[str] = []
    total_input_tokens = 0
    total_output_tokens = 0
    final_text = ""

    # Agentic loop, bounded so a tool-use storm can't run forever.
    for iteration in range(settings.max_agent_iterations):
        try:
            response = client.messages.create(
                model=settings.claude_model,
                max_tokens=settings.max_tokens,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.APIStatusError as exc:
            # Auth, billing, rate-limit, overload, etc. — surface a clean message.
            logger.error("Anthropic API error (status %s): %s", exc.status_code, exc)
            raise ClaudeClientError(
                f"Anthropic API error ({exc.status_code}): {exc.message}"
            ) from exc
        except anthropic.APIError as exc:
            logger.error("Anthropic API error: %s", exc)
            raise ClaudeClientError(f"Anthropic API error: {exc}") from exc

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # Record Claude's turn in the running conversation.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            final_text = _extract_text(response.content)
            break

        # Claude requested one or more tools — execute them all and feed back.
        tool_results = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            tools_called.append(block.name)
            fn = TOOL_MAP.get(block.name)
            try:
                result_text = fn(**block.input) if fn else f"Unknown tool: {block.name}"
            except Exception as exc:  # tool execution shouldn't kill the loop
                logger.exception("Tool %s raised", block.name)
                result_text = f"Tool '{block.name}' failed: {exc}"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text,
            })

        messages.append({"role": "user", "content": tool_results})
    else:
        # Loop exhausted without a final answer.
        logger.error("Agentic loop hit max_agent_iterations=%s", settings.max_agent_iterations)
        raise ClaudeClientError(
            f"Query exceeded the maximum of {settings.max_agent_iterations} tool-use rounds."
        )

    latency_ms = (time.time() - start_time) * 1000
    cost_usd = _calc_cost(total_input_tokens, total_output_tokens)
    logger.info(
        "Query complete: tools=%s, tokens=%s/%s, cost=$%.5f, latency=%.0fms",
        tools_called, total_input_tokens, total_output_tokens, cost_usd, latency_ms,
    )

    return {
        "answer": final_text,
        "tools_called": tools_called,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost_usd": round(cost_usd, 6),
        "latency_ms": round(latency_ms, 1),
    }
