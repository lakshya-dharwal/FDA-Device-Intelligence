"""
Streamlit frontend — two tabs:
  1. Query  : natural language FDA question → AI answer with telemetry cards
  2. Analytics : charts and table from the /metrics and /history endpoints
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from collections import Counter

BACKEND = "http://localhost:8000"

EXAMPLE_QUESTIONS = [
    "What are recent Class I recalls for infusion pumps?",
    "Show me adverse events for the da Vinci surgical robot",
    "How is a pacemaker classified by the FDA?",
    "What recalls have been issued for glucose monitors in the past year?",
    "Are there any adverse events linked to metal-on-metal hip implants?",
]

st.set_page_config(
    page_title="FDA Device Intelligence",
    page_icon="🏥",
    layout="wide",
)

st.title("🏥 FDA Device Intelligence Platform")
st.caption(
    "Ask any question about FDA medical device recalls, adverse events, or classifications. "
    "Claude autonomously queries live FDA data and synthesises a clinical answer."
)

tab_query, tab_analytics = st.tabs(["🔍 Query", "📊 Analytics"])

# ── Tab 1: Query ──────────────────────────────────────────────────────────────
with tab_query:
    selected_example = st.selectbox(
        "Choose an example question or write your own below:",
        EXAMPLE_QUESTIONS,
    )

    user_query = st.text_area(
        "Your question:",
        value=selected_example,
        height=100,
    )

    if st.button("🔎 Search FDA Data", type="primary"):
        if not user_query.strip():
            st.warning("Please enter a question.")
        else:
            with st.spinner("Claude is querying live FDA data…"):
                try:
                    resp = requests.post(
                        f"{BACKEND}/query",
                        json={"query": user_query},
                        timeout=120,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except requests.exceptions.ConnectionError:
                    st.error(
                        "Cannot reach the backend. Make sure FastAPI is running: "
                        "`uvicorn src.backend.main:app --reload`"
                    )
                    st.stop()
                except Exception as e:
                    st.error(f"Request failed: {e}")
                    st.stop()

            # ── Telemetry metric cards ────────────────────────────────────────
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("🛠 Tools Called", len(data.get("tools_called", [])))
            col2.metric("⏱ Latency", f"{data.get('latency_ms', 0):.0f} ms")
            col3.metric(
                "🔤 Tokens",
                f"{data.get('input_tokens', 0) + data.get('output_tokens', 0):,}",
            )
            col4.metric("💲 Cost", f"${data.get('cost_usd', 0):.5f}")

            st.divider()

            # ── Answer ────────────────────────────────────────────────────────
            st.markdown(data.get("answer", "No answer returned."))

            tools = data.get("tools_called", [])
            if tools:
                st.caption(f"MCP tools used: `{'`, `'.join(tools)}`")

# ── Tab 2: Analytics ──────────────────────────────────────────────────────────
with tab_analytics:
    if st.button("🔄 Refresh"):
        st.rerun()

    # Summary metrics from /metrics
    try:
        m_resp = requests.get(f"{BACKEND}/metrics", timeout=10)
        m_resp.raise_for_status()
        metrics = m_resp.json()
    except Exception:
        metrics = {}
        st.warning("Could not reach backend for metrics.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Queries", int(metrics.get("total_queries", 0)))
    c2.metric("Total Cost", f"${metrics.get('total_cost_usd', 0):.4f}")
    c3.metric("Avg Latency", f"{metrics.get('avg_latency_ms', 0):.0f} ms")
    c4.metric("Avg Tokens / Query", f"{metrics.get('avg_tokens', 0):.0f}")

    st.divider()

    # Query history from /history
    try:
        h_resp = requests.get(f"{BACKEND}/history", timeout=10)
        h_resp.raise_for_status()
        history = h_resp.json()
    except Exception:
        history = []

    if not history:
        st.info("No query history yet. Head to the Query tab and run a few questions!")
    else:
        df = pd.DataFrame(history)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")

        # Cost over time
        st.subheader("💸 Cost Over Time")
        fig_cost = px.line(
            df,
            x="timestamp",
            y="cost_usd",
            markers=True,
            labels={"cost_usd": "Cost (USD)", "timestamp": "Time"},
        )
        st.plotly_chart(fig_cost, use_container_width=True)

        col_lat, col_tools = st.columns(2)

        # Latency distribution
        with col_lat:
            st.subheader("⏱ Latency Distribution")
            fig_lat = px.histogram(
                df,
                x="latency_ms",
                nbins=20,
                labels={"latency_ms": "Latency (ms)"},
            )
            st.plotly_chart(fig_lat, use_container_width=True)

        # Tool call frequency
        with col_tools:
            st.subheader("🛠 MCP Tool Call Frequency")
            all_tools = []
            for row in history:
                all_tools.extend(row.get("tools_called", []))
            if all_tools:
                tool_counts = Counter(all_tools)
                tool_df = pd.DataFrame(
                    tool_counts.items(), columns=["tool", "count"]
                ).sort_values("count", ascending=False)
                fig_tools = px.bar(
                    tool_df,
                    x="tool",
                    y="count",
                    labels={"tool": "Tool", "count": "Times Called"},
                )
                st.plotly_chart(fig_tools, use_container_width=True)
            else:
                st.info("No tool calls recorded yet.")

        # Recent history table
        st.subheader("📋 Recent Query History")
        display_cols = ["timestamp", "query", "tools_called", "input_tokens",
                        "output_tokens", "cost_usd", "latency_ms"]
        st.dataframe(
            df[display_cols].sort_values("timestamp", ascending=False).head(50),
            use_container_width=True,
        )
