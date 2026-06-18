# FDA Device Intelligence Platform

A healthcare AI platform where you type a natural-language question about FDA medical device safety and receive an AI-generated answer backed by live FDA data. Claude (Anthropic API) acts as the intelligence layer, the backend retrieves structured FDA records, and a Streamlit control plane visualizes query output, telemetry, and operational events.

---

## Architecture

```
┌─────────────┐     HTTP(S) /query       ┌──────────────────┐
│  Streamlit  │ ────────────────────────▶ │  FastAPI Backend  │
│  Frontend   │ ◀──────────────────────── │  (main.py)        │
└─────────────┘  answer + metrics/events └────────┬─────────┘
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
                                        │  Structured FDA Tools │
                                        │  fda_tools.py         │
                                        │  • normalized search  │
                                        │  • date filters       │
                                        │  • ranked results     │
                                        └────────┬─────────────┘
                                                 │ HTTPS GET
                                                 ▼
                                        ┌──────────────────────┐
                                        │  OpenFDA Public API   │
                                        │  api.fda.gov          │
                                        └──────────────────────┘

                    Telemetry + Ops Events
                    ┌──────────────────────┐
                    │  SQLAlchemy Store     │
                    │  SQLite / Postgres    │
                    └──────────────────────┘
```

---

## Tech Stack

| Layer       | Technology                              |
|-------------|------------------------------------------|
| AI Model    | Claude `claude-sonnet-4-5` (Anthropic API) |
| Backend     | FastAPI + Uvicorn                        |
| Frontend    | Streamlit                                |
| Telemetry   | SQLAlchemy with SQLite or Postgres       |
| Security    | Bearer token auth, trusted hosts, rate limiting |
| Charts      | Plotly + Pandas                          |
| FDA Data    | OpenFDA public REST API                  |
| HTTP Client | `requests` / `httpx`                     |

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

### 4. Add configuration

Copy `.env.example` to `.env` and set at least:

```
ANTHROPIC_API_KEY=sk-ant-...your-key-here...
API_AUTH_TOKEN=change-me
```

### 5. Start the FastAPI backend

```bash
uvicorn src.backend.main:app --reload --port 8000
```

The API will be live at `http://localhost:8000`. The default frontend origin is `http://localhost:8501`.

### 6. Start the Streamlit frontend (new terminal)

```bash
streamlit run src/frontend/app.py
```

The dashboard opens at `http://localhost:8501`.

### 7. Local Postgres option

If you want production-like telemetry locally:

```bash
docker compose up postgres
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/fda_device_intelligence
```

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
| GET    | `/events`  | Recent warning/error telemetry events    |

---

## Security

- API auth via `Authorization: Bearer <API_AUTH_TOKEN>` or `X-API-Key`
- CORS allowlist via `CORS_ALLOWED_ORIGINS`
- Trusted hosts via `TRUSTED_HOSTS`
- In-memory rate limiting via `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW_SECONDS`
- Request IDs returned in `X-Request-ID`

---

## Deployment

- `Dockerfile.backend` builds the FastAPI service
- `Dockerfile.frontend` builds the Streamlit service
- `docker-compose.yml` runs Postgres, backend, and frontend as separate services

Start the full stack with:

```bash
docker compose up --build
```

This brings up:

- Postgres on `localhost:5432`
- Backend on `localhost:8000`
- Frontend on `localhost:8501`

---

## Frontend

The Streamlit app now includes:

- auth-aware backend requests
- cached reads for `/metrics`, `/history`, and `/events`
- structured tool result tables with CSV export
- filtered analytics views for query history
- an operations tab for warning/error telemetry
