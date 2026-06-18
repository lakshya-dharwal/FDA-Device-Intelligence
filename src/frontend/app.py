"""
Streamlit frontend with query, analytics, and operational telemetry views.
"""

from __future__ import annotations

from io import StringIO

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

from src.backend.settings import get_settings

SETTINGS = get_settings()

EXAMPLE_QUESTIONS = [
    "What are recent Class I recalls for infusion pumps?",
    "Show me adverse events for the da Vinci surgical robot",
    "How is a pacemaker classified by the FDA?",
    "What recalls have been issued for glucose monitors in the past year?",
    "Are there any adverse events linked to metal-on-metal hip implants?",
]


def get_backend_config() -> tuple[str, str | None, int]:
    """Return backend connection details from session state or env defaults."""
    if "backend_url" not in st.session_state:
        st.session_state.backend_url = SETTINGS.frontend_backend_url
    if "api_token" not in st.session_state:
        st.session_state.api_token = SETTINGS.frontend_api_token or ""
    return (
        st.session_state.backend_url.rstrip("/"),
        st.session_state.api_token or None,
        SETTINGS.frontend_request_timeout_seconds,
    )


def build_headers(api_token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    return headers


def ensure_success(response: requests.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.ok:
        return payload

    error = payload.get("error", {})
    message = error.get("message", f"Request failed with status {response.status_code}.")
    if error.get("request_id"):
        message = f"{message} Request ID: {error['request_id']}"
    raise RuntimeError(message)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_metrics(base_url: str, api_token: str | None, timeout_seconds: int) -> dict:
    response = requests.get(
        f"{base_url}/metrics",
        headers=build_headers(api_token),
        timeout=timeout_seconds,
    )
    return ensure_success(response)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_history(base_url: str, api_token: str | None, timeout_seconds: int) -> list[dict]:
    response = requests.get(
        f"{base_url}/history",
        headers=build_headers(api_token),
        timeout=timeout_seconds,
    )
    return ensure_success(response)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_events(base_url: str, api_token: str | None, timeout_seconds: int) -> list[dict]:
    response = requests.get(
        f"{base_url}/events",
        headers=build_headers(api_token),
        timeout=timeout_seconds,
    )
    return ensure_success(response)


def run_query(base_url: str, api_token: str | None, timeout_seconds: int, query: str) -> dict:
    response = requests.post(
        f"{base_url}/query",
        headers=build_headers(api_token),
        json={"query": query},
        timeout=max(timeout_seconds, 120),
    )
    return ensure_success(response)


def dataframe_csv_download(label: str, dataframe: pd.DataFrame, file_name: str) -> None:
    buffer = StringIO()
    dataframe.to_csv(buffer, index=False)
    st.download_button(
        label=label,
        data=buffer.getvalue(),
        file_name=file_name,
        mime="text/csv",
    )


def render_tool_results(tool_results: list[dict]) -> None:
    """Render structured tool results directly in the UI."""
    if not tool_results:
        return

    st.subheader("Structured Results")

    for index, tool_call in enumerate(tool_results, start=1):
        tool_name = tool_call.get("tool_name", "tool")
        tool_input = tool_call.get("tool_input", {})
        tool_output = tool_call.get("tool_output", {})
        result_rows = tool_output.get("results", [])
        duration_ms = tool_call.get("duration_ms", 0.0)

        with st.expander(
            f"{index}. {tool_name} ({tool_output.get('result_count', 0)} results, {duration_ms:.1f} ms)",
            expanded=True,
        ):
            metadata = {
                "query": tool_output.get("query"),
                "normalized_terms": ", ".join(tool_output.get("normalized_terms", [])),
                "filters": ", ".join(
                    f"{key}={value}"
                    for key, value in (tool_output.get("filters") or {}).items()
                    if value
                )
                or "none",
                "search_fields": ", ".join(tool_output.get("search_fields", [])),
            }
            st.caption(
                " | ".join(
                    f"{key}: {value}"
                    for key, value in metadata.items()
                    if value not in (None, "")
                )
            )

            col_input, col_output = st.columns([1, 3])
            with col_input:
                if tool_input:
                    st.markdown("**Tool Input**")
                    st.json(tool_input, expanded=False)
            with col_output:
                if result_rows:
                    result_df = pd.DataFrame(result_rows)
                    st.dataframe(result_df, use_container_width=True)
                    dataframe_csv_download(
                        "Download results as CSV",
                        result_df,
                        f"{tool_name}-{index}.csv",
                    )
                else:
                    st.info("No structured results returned for this tool call.")


def filter_history(history: list[dict]) -> pd.DataFrame:
    """Apply dashboard filters to query history."""
    if not history:
        return pd.DataFrame()

    df = pd.DataFrame(history)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["tool_count"] = df["tools_called"].apply(lambda items: len(items or []))
    df["tools_display"] = df["tools_called"].apply(lambda items: ", ".join(items or []))
    df["status"] = df["status"].fillna("success")
    df["error_code"] = df["error_code"].fillna("")

    with st.sidebar:
        st.markdown("### History Filters")
        query_text = st.text_input("Search query text", value="")
        statuses = st.multiselect(
            "Status",
            options=sorted(df["status"].unique().tolist()),
            default=sorted(df["status"].unique().tolist()),
        )
        available_tools = sorted({tool for row in history for tool in row.get("tools_called", [])})
        selected_tools = st.multiselect("Tools used", options=available_tools, default=available_tools)

    filtered = df[df["status"].isin(statuses)]
    if query_text:
        filtered = filtered[filtered["query"].str.contains(query_text, case=False, na=False)]
    if selected_tools:
        filtered = filtered[
            filtered["tools_called"].apply(
                lambda items: any(tool in (items or []) for tool in selected_tools)
            )
        ]
    return filtered.sort_values("timestamp")


def render_analytics(metrics: dict, history: list[dict]) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Queries", int(metrics.get("total_queries", 0)))
    c2.metric("Failures", int(metrics.get("failed_queries", 0)))
    c3.metric("Total Cost", f"${metrics.get('total_cost_usd', 0):.4f}")
    c4.metric("Avg Latency", f"{metrics.get('avg_latency_ms', 0):.0f} ms")
    c5.metric("Avg Tool Time", f"{metrics.get('avg_tool_latency_ms', 0):.0f} ms")

    st.divider()

    if not history:
        st.info("No query history yet. Head to the Query tab and run a few questions.")
        return

    df = filter_history(history)
    if df.empty:
        st.warning("No history rows match the current filters.")
        return

    st.subheader("Cost Over Time")
    fig_cost = px.line(
        df,
        x="timestamp",
        y="cost_usd",
        color="status",
        markers=True,
        labels={"cost_usd": "Cost (USD)", "timestamp": "Time"},
    )
    st.plotly_chart(fig_cost, use_container_width=True)

    col_lat, col_tools = st.columns(2)
    with col_lat:
        st.subheader("Latency Distribution")
        fig_lat = px.histogram(
            df,
            x="latency_ms",
            color="status",
            nbins=20,
            labels={"latency_ms": "Latency (ms)"},
        )
        st.plotly_chart(fig_lat, use_container_width=True)

    with col_tools:
        st.subheader("Tool Frequency")
        exploded = df.explode("tools_called")
        exploded = exploded[exploded["tools_called"].notna() & (exploded["tools_called"] != "")]
        if exploded.empty:
            st.info("No tool calls recorded yet.")
        else:
            tool_counts = (
                exploded.groupby("tools_called")
                .size()
                .reset_index(name="count")
                .sort_values("count", ascending=False)
            )
            fig_tools = px.bar(
                tool_counts,
                x="tools_called",
                y="count",
                labels={"tools_called": "Tool", "count": "Times Called"},
            )
            st.plotly_chart(fig_tools, use_container_width=True)

    st.subheader("History Table")
    display_cols = [
        "timestamp",
        "status",
        "query",
        "tools_display",
        "tool_count",
        "total_tool_latency_ms",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "latency_ms",
        "error_code",
    ]
    st.dataframe(
        df[display_cols].sort_values("timestamp", ascending=False),
        use_container_width=True,
    )
    dataframe_csv_download(
        "Download filtered history as CSV",
        df[display_cols].sort_values("timestamp", ascending=False),
        "query-history.csv",
    )


def render_ops(metrics: dict, events: list[dict]) -> None:
    st.subheader("Operational Events")
    st.caption(
        f"Tracked warning/error events: {int(metrics.get('total_error_events', 0))}"
    )

    if not events:
        st.info("No telemetry events recorded yet.")
        return

    events_df = pd.DataFrame(events)
    events_df["timestamp"] = pd.to_datetime(events_df["timestamp"])
    st.dataframe(events_df.sort_values("timestamp", ascending=False), use_container_width=True)
    dataframe_csv_download(
        "Download events as CSV",
        events_df.sort_values("timestamp", ascending=False),
        "telemetry-events.csv",
    )


st.set_page_config(
    page_title="FDA Device Intelligence",
    page_icon="🏥",
    layout="wide",
)

backend_url, api_token, timeout_seconds = get_backend_config()

with st.sidebar:
    st.title("Control Plane")
    st.text_input("Backend URL", key="backend_url")
    st.text_input("API Token", key="api_token", type="password")
    if st.button("Clear cached reads"):
        fetch_metrics.clear()
        fetch_history.clear()
        fetch_events.clear()
        st.rerun()
    st.caption(
        "Reads are cached for 30 seconds. Query submissions always go directly to the backend."
    )

backend_url, api_token, timeout_seconds = get_backend_config()

st.title("FDA Device Intelligence Platform")
st.caption(
    "A production-oriented workspace for FDA device recall, adverse event, and classification analysis."
)

tab_query, tab_analytics, tab_ops = st.tabs(["Query", "Analytics", "Ops"])

with tab_query:
    selected_example = st.selectbox(
        "Choose an example question or write your own below:",
        EXAMPLE_QUESTIONS,
    )
    user_query = st.text_area("Your question:", value=selected_example, height=110)

    if st.button("Run Query", type="primary"):
        if not user_query.strip():
            st.warning("Please enter a question.")
        else:
            with st.spinner("Running FDA device intelligence query..."):
                try:
                    data = run_query(backend_url, api_token, timeout_seconds, user_query)
                except requests.exceptions.ConnectionError:
                    st.error("Cannot reach the backend. Verify the backend URL and server status.")
                    st.stop()
                except Exception as exc:
                    st.error(str(exc))
                    st.stop()

            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Tools", len(data.get("tools_called", [])))
            col2.metric("Latency", f"{data.get('latency_ms', 0):.0f} ms")
            col3.metric(
                "Tokens",
                f"{data.get('input_tokens', 0) + data.get('output_tokens', 0):,}",
            )
            col4.metric("Cost", f"${data.get('cost_usd', 0):.5f}")
            col5.metric(
                "Tool Time",
                f"{sum(item.get('duration_ms', 0.0) for item in data.get('tool_results', [])):.0f} ms",
            )

            st.divider()
            st.markdown(data.get("answer", "No answer returned."))

            tools = data.get("tools_called", [])
            if tools:
                st.caption(f"Tools used: `{'`, `'.join(tools)}`")

            render_tool_results(data.get("tool_results", []))

with tab_analytics:
    if st.button("Refresh analytics"):
        fetch_metrics.clear()
        fetch_history.clear()
        fetch_events.clear()
        st.rerun()

    try:
        metrics = fetch_metrics(backend_url, api_token, timeout_seconds)
        history = fetch_history(backend_url, api_token, timeout_seconds)
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    render_analytics(metrics, history)

with tab_ops:
    try:
        metrics = fetch_metrics(backend_url, api_token, timeout_seconds)
        events = fetch_events(backend_url, api_token, timeout_seconds)
    except Exception as exc:
        st.error(str(exc))
        st.stop()

    render_ops(metrics, events)
