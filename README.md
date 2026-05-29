# FDA Device Intelligence Platform

A healthcare AI platform where you type a natural-language question about FDA medical device safety and receive an AI-generated answer backed by live, real-time FDA data. Claude (Anthropic API) acts as the intelligence layer — it autonomously decides which FDA data tools to call, fetches the data, and synthesises a clinical-grade answer. Every query is logged with cost, latency, and token usage, and a Streamlit dashboard visualises this telemetry.

---

## Architecture

```
┌─────────────┐     HTTP POST /query      ┌──────────────────┐
│  Streamlit  │ ─────────────────────────▶ │  FastAPI Backend  │
│  Frontend   │ ◀───────────────────────── │  (main.py)        │
└─────────────┘     answer + telemetry    └────────┬─────────┘
                                                   │
                                          Anthropic SDK
                                                   │
                                                   ▼
                                        ┌──────────────────────┐
                                        │  Claude claude-       │
                                        │  sonnet-4-5          │
                                        │  (agentic loop)      │
                                        └────────┬─────────────┘
                                                 │ tool_use calls
                                                 ▼
                                        ┌──────────────────────┐
                                        │  MCP / FDA Tools      │
                                        │  fda_tools.py         │
                                        │  • search_recalls     │
                                        │  • get_adverse_events │
                                        │  • get_classifications│
                                        └────────┬─────────────┘
                                                 │ HTTPS GET
                                                 ▼
                                        ┌──────────────────────┐
                                        │  OpenFDA Public API   │
                                        │  api.fda.gov          │
                                        └──────────────────────┘

                    Telemetry (every query)
                    ┌──────────────────────┐
                    │  SQLite telemetry.db  │
                    │  (V2: GCP Firestore)  │
                    └──────────────────────┘
```

---

## Tech Stack

| Layer       | Technology                         |
|-------------|-------------------------------------|
| AI Model    | Claude claude-sonnet-4-5 (Anthropic API) |
| MCP Tools   | FastMCP (mcp library)               |
| Backend     | FastAPI + Uvicorn                   |
| Frontend    | Streamlit                           |
| Charts      | Plotly                              |
| Telemetry   | SQLite (V2: GCP Firestore)          |
| FDA Data    | OpenFDA public REST API (no auth)   |
| HTTP Client | requests / httpx                    |

---

## Local Setup

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd FDA-Device-Intelligence
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Add your Anthropic API key

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...your-key-here...
```

### 5. Start the FastAPI backend

```bash
uvicorn src.backend.main:app --reload --port 8000
```

The API will be live at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

### 6. Start the Streamlit frontend (new terminal)

```bash
streamlit run src/frontend/app.py
```

The dashboard opens at `http://localhost:8501`.

---

## Example Queries

1. **What are recent Class I recalls for infusion pumps?**
2. **Show me adverse events for the da Vinci surgical robot**
3. **How is a pacemaker classified by the FDA?**
4. **What recalls have been issued for glucose monitors in the past year?**
5. **Are there any adverse events linked to metal-on-metal hip implants?**

---

## API Endpoints

| Method | Path       | Description                              |
|--------|------------|------------------------------------------|
| GET    | `/health`  | Liveness probe                           |
| POST   | `/query`   | Run a natural-language FDA query         |
| GET    | `/metrics` | Aggregate telemetry stats                |
| GET    | `/history` | Full query history (newest first)        |

---

## Roadmap

- **V1 (current):** Local SQLite telemetry, OpenFDA public API, Claude agentic loop
- **V2 (planned):** GCP Cloud Run deployment, Firestore telemetry, authentication, streaming responses
