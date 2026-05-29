"""
Claude agentic loop — sends user queries to Claude with FDA tool definitions,
then executes any tool calls Claude requests against the real OpenFDA API,
feeding results back until Claude produces a final answer.
"""

import os
import time
import sys
from dotenv import load_dotenv
import anthropic

# Make sure the project root is on the path so we can import sibling packages
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.mcp_server.fda_tools import (
    search_device_recalls,
    get_adverse_events,
    get_device_classifications,
)

load_dotenv()

# Pricing constants for claude-sonnet-4-5 (per million tokens)
INPUT_COST_PER_MTOK = 3.00
OUTPUT_COST_PER_MTOK = 15.00

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """You are an FDA Device Intelligence Assistant. You help clinicians,
researchers, and regulators understand FDA medical device safety data including recalls,
adverse events, and device classifications. When answering questions, always use the
provided tools to fetch real, up-to-date FDA data rather than relying on your training
data. Be precise, cite the data you retrieved, and present findings in a structured,
clinically useful format."""

# Tool definitions in Anthropic tool_use format
TOOLS = [
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

# Map tool names Claude will call → actual Python functions
TOOL_MAP = {
    "search_device_recalls": search_device_recalls,
    "get_adverse_events": get_adverse_events,
    "get_device_classifications": get_device_classifications,
}


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
    start_time = time.time()

    messages = [{"role": "user", "content": query}]
    tools_called = []
    total_input_tokens = 0
    total_output_tokens = 0

    # Agentic loop: keep calling Claude until it stops requesting tool use
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # Append Claude's response to the conversation
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            # Claude is done — extract the final text answer
            final_text = ""
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
                if fn:
                    result_text = fn(**tool_input)
                else:
                    result_text = f"Unknown tool: {tool_name}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })

        # Feed tool results back to Claude
        messages.append({"role": "user", "content": tool_results})

    latency_ms = (time.time() - start_time) * 1000
    cost_usd = (
        (total_input_tokens / 1_000_000) * INPUT_COST_PER_MTOK
        + (total_output_tokens / 1_000_000) * OUTPUT_COST_PER_MTOK
    )

    return {
        "answer": final_text,
        "tools_called": tools_called,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost_usd": round(cost_usd, 6),
        "latency_ms": round(latency_ms, 1),
    }
