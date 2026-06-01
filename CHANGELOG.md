# Changelog

All notable changes to the FDA Device Intelligence Platform are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Central configuration** (`src/config.py`): immutable, env-driven `Settings`
  singleton for the Anthropic model/tokens/pricing, agentic iteration cap,
  OpenFDA base URL/timeout, telemetry DB path, frontend API URL, and log level.
- **Logging** (`src/logging_config.py`): `get_logger()` with idempotent root
  configuration; structured logging added across all modules (no more silent paths).
- **Bounded agentic loop**: `MAX_AGENT_ITERATIONS` cap so a runaway tool-use
  loop can never accrue unbounded Anthropic cost.
- **pytest suite** (`tests/`): 37 tests at ~89% coverage covering FDA tools,
  telemetry, the agentic loop, and all FastAPI endpoints — fully mocked/offline.
- **Developer tooling**: `requirements-dev.txt`, `pytest.ini` (coverage config),
  `.env.example`, and this `CHANGELOG.md`.

### Changed
- **`fda_tools.py`**: extracted a shared `_query_openfda()` helper; now
  distinguishes Timeout / ConnectionError / HTTPError / JSON-decode failures,
  treats HTTP 404 as an empty result set, clamps `limit` to OpenFDA's 1–1000
  range, escapes quotes in search terms, and reads defensively for nested
  adverse-event fields.
- **`claude_client.py`**: lazy, validated `get_client()` that raises a clear
  error when `ANTHROPIC_API_KEY` is missing; Anthropic API errors are caught and
  re-raised as `ClaudeClientError`; the client is injectable for testing;
  model/tokens/pricing now come from config.
- **`telemetry.py`**: replaced deprecated `datetime.utcnow()` with
  timezone-aware `datetime.now(timezone.utc)`; wrapped all DB operations in
  error handling so telemetry can never break a successful query; DB path from config.
- **`main.py`**: migrated from the deprecated `@app.on_event` to the `lifespan`
  context manager; added query-length validation (3–500 chars); maps
  `ClaudeClientError` to HTTP 502 with a useful message; endpoint summaries for `/docs`.
- **`frontend/app.py`**: backend URL is now read from `FDA_API_URL` so the same
  app targets localhost in dev and Cloud Run in production.
- **`README.md`**: rewritten as production-grade docs — problem statement,
  Mermaid architecture diagram, tech-stack and config tables, API reference with
  request/response examples, and an honest Known Limitations section.

### Fixed
- Unbounded `while True` agentic loop that could loop (and bill) forever.
- Bare HTTP 500s on Anthropic billing/auth failures — now surfaced as 502 with context.
- Architecture/reality mismatch: telemetry is documented honestly as SQLite in
  V1 with Firestore as the explicit V2 swap target.

## [1.0.0] — Initial build

### Added
- Three OpenFDA tools (recalls, adverse events, classifications) as plain
  functions and MCP (FastMCP) tools.
- Claude agentic loop translating natural-language questions into tool calls.
- FastAPI backend (`/health`, `/query`, `/metrics`, `/history`) with CORS.
- SQLite telemetry logging per-query cost, latency, and token usage.
- Streamlit frontend with Query and Analytics tabs.
- Initial README with architecture diagram and setup instructions.
