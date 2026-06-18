"""
Claude agentic loop — sends user queries to Claude with FDA tool definitions,
then executes any tool calls Claude requests against the real OpenFDA API,
feeding results back until Claude produces a final answer.
"""

import json
import time
from functools import lru_cache

import anthropic

from src.mcp_server.fda_tools import (
    search_device_recalls,
    get_adverse_events,
    get_device_classifications,
)
from src.backend.exceptions import (
    BackendError,
    InternalQueryError,
    ModelProviderError,
    ModelProviderTimeoutError,
)
from src.backend.prompts import get_system_prompt
from src.backend.settings import AppSettings, get_settings

# Tool definitions in Anthropic tool_use format
TOOLS = [
    {
        "name": "search_device_recalls",
        "description": (
            "Search FDA device recall data using normalized device-name variants and optional "
            "date filters. Returns structured recall records with query metadata."
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
                "date_from": {
                    "type": "string",
                    "description": "Optional lower date bound in YYYY-MM-DD format.",
                },
                "date_to": {
                    "type": "string",
                    "description": "Optional upper date bound in YYYY-MM-DD format.",
                },
            },
            "required": ["search_term"],
        },
    },
    {
        "name": "get_adverse_events",
        "description": (
            "Retrieve FDA adverse event (MAUDE) reports using normalized device-name variants "
            "and optional date filters. Returns structured event records with query metadata."
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
                "date_from": {
                    "type": "string",
                    "description": "Optional lower date bound in YYYY-MM-DD format.",
                },
                "date_to": {
                    "type": "string",
                    "description": "Optional upper date bound in YYYY-MM-DD format.",
                },
            },
            "required": ["device_name"],
        },
    },
    {
        "name": "get_device_classifications",
        "description": (
            "Look up FDA device classification records using normalized device-name variants. "
            "Returns structured classification records and query metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "Name of the medical device to classify.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of results to return (default 5).",
                    "default": 5,
                },
            },
            "required": ["device_name"],
        },
    },
]

# Map tool names Claude will call → actual Python functions
TOOL_MAP = {
    "search_device_recalls": search_device_recalls,
    "get_adverse_events": get_adverse_events,
    "get_device_classifications": get_device_classifications,
}


@lru_cache(maxsize=1)
def get_anthropic_client():
    """Create and cache the Anthropic client from current settings."""
    settings = get_settings()
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def calculate_query_cost(
    settings: AppSettings,
    *,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate total query cost from token usage and configured pricing."""
    return (
        (input_tokens / 1_000_000) * settings.model_input_cost_per_mtok
        + (output_tokens / 1_000_000) * settings.model_output_cost_per_mtok
    )


def run_fda_query(query: str) -> dict:
    """
    Run an agentic Claude query against the FDA tools.

    Returns a dict with:
      answer        - final text response from Claude
      tools_called  - list of tool names that were invoked
      input_tokens  - cumulative input tokens across all API calls
      output_tokens - cumulative output tokens across all API calls
      cost_usd      - estimated cost
      latency_ms    - wall-clock time in milliseconds
    """
    start_time = time.monotonic()
    settings = get_settings()
    client = get_anthropic_client()

    messages = [{"role": "user", "content": query}]
    tools_called = []
    tool_results_for_response = []
    total_input_tokens = 0
    total_output_tokens = 0
    iteration_count = 0
    final_text = ""

    # Agentic loop: keep calling Claude until it stops requesting tool use
    while True:
        if time.monotonic() - start_time > settings.query_timeout_seconds:
            raise ModelProviderTimeoutError(
                "The query exceeded the maximum allowed execution time.",
                details={"timeout_seconds": settings.query_timeout_seconds},
            )

        iteration_count += 1
        if iteration_count > settings.max_tool_iterations:
            raise InternalQueryError(
                "The query exceeded the maximum number of tool-use steps.",
                details={"max_tool_iterations": settings.max_tool_iterations},
                code="tool_loop_exhausted",
            )

        try:
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=settings.anthropic_max_tokens,
                system=get_system_prompt(),
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.APITimeoutError as exc:
            raise ModelProviderTimeoutError(
                details={"provider": "anthropic"},
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ModelProviderError(
                "The AI model provider is rate-limiting requests.",
                details={"provider": "anthropic", "reason": str(exc)},
                code="model_provider_rate_limited",
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ModelProviderError(
                "Could not reach the AI model provider.",
                details={"provider": "anthropic", "reason": str(exc)},
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ModelProviderError(
                "The AI model provider returned an error.",
                details={
                    "provider": "anthropic",
                    "status_code": exc.status_code,
                    "reason": str(exc),
                },
                retryable=exc.status_code >= 500 or exc.status_code == 429,
            ) from exc
        except anthropic.AnthropicError as exc:
            raise ModelProviderError(
                "The AI model provider request failed.",
                details={"provider": "anthropic", "reason": str(exc)},
                retryable=False,
            ) from exc

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # Append Claude's response to the conversation
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            # Claude is done — extract the final text answer
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text
            break

        # Claude wants to call one or more tools — execute them all
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                tools_called.append(tool_name)

                fn = TOOL_MAP.get(tool_name)
                if not fn:
                    raise InternalQueryError(
                        f"Claude requested an unknown tool: {tool_name}",
                        details={"tool_name": tool_name},
                        code="unknown_tool_requested",
                    )

                try:
                    tool_start = time.monotonic()
                    result_text = fn(**tool_input)
                    duration_ms = round((time.monotonic() - tool_start) * 1000, 1)
                except BackendError:
                    raise
                except Exception as exc:
                    raise InternalQueryError(
                        f"Tool execution failed for {tool_name}.",
                        details={"tool_name": tool_name, "reason": str(exc)},
                        code="tool_execution_failed",
                    ) from exc

                tool_results_for_response.append(
                    {
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                        "tool_output": result_text,
                        "duration_ms": duration_ms,
                    }
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result_text, ensure_ascii=True),
                })

        # Feed tool results back to Claude
        messages.append({"role": "user", "content": tool_results})

    latency_ms = (time.monotonic() - start_time) * 1000
    cost_usd = calculate_query_cost(
        settings,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
    )

    return {
        "answer": final_text,
        "tools_called": tools_called,
        "tool_results": tool_results_for_response,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost_usd": round(cost_usd, 6),
        "latency_ms": round(latency_ms, 1),
    }
