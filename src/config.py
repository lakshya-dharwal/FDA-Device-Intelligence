"""
Central configuration for the FDA Device Intelligence Platform.

All environment-driven settings and tunable constants live here so the rest
of the codebase never reaches for os.getenv() directly or hardcodes magic
values. Import `settings` (a module-level singleton) wherever config is needed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Load .env once, at import time, for the whole process.
load_dotenv()


def _get_float(name: str, default: float) -> float:
    """Read a float env var, falling back to a default on missing/invalid input."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    """Read an int env var, falling back to a default on missing/invalid input."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# Project root = two levels up from this file (src/config.py -> project root).
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@dataclass(frozen=True)
class Settings:
    """Immutable application settings, populated from environment variables."""

    # ── Anthropic / Claude ────────────────────────────────────────────────
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    claude_model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5"))
    max_tokens: int = field(default_factory=lambda: _get_int("CLAUDE_MAX_TOKENS", 4096))

    # Hard cap on agentic tool-use rounds, so a misbehaving loop can never
    # run up unbounded cost. Each iteration is one Claude API call.
    max_agent_iterations: int = field(default_factory=lambda: _get_int("MAX_AGENT_ITERATIONS", 10))

    # Claude pricing (USD per million tokens). Defaults track sonnet pricing.
    input_cost_per_mtok: float = field(default_factory=lambda: _get_float("INPUT_COST_PER_MTOK", 3.00))
    output_cost_per_mtok: float = field(default_factory=lambda: _get_float("OUTPUT_COST_PER_MTOK", 15.00))

    # ── OpenFDA ───────────────────────────────────────────────────────────
    openfda_base: str = field(default_factory=lambda: os.getenv("OPENFDA_BASE", "https://api.fda.gov"))
    openfda_timeout: float = field(default_factory=lambda: _get_float("OPENFDA_TIMEOUT", 10.0))

    # ── Telemetry (SQLite in V1; Firestore is the V2 swap target) ─────────
    # Backend selector: "sqlite" (local/dev/test) or "firestore" (Cloud Run).
    telemetry_backend: str = field(
        default_factory=lambda: os.getenv("TELEMETRY_BACKEND", "sqlite").lower()
    )
    db_path: str = field(
        default_factory=lambda: os.getenv("TELEMETRY_DB_PATH", os.path.join(_PROJECT_ROOT, "telemetry.db"))
    )
    # Firestore collection name used when telemetry_backend == "firestore".
    firestore_collection: str = field(
        default_factory=lambda: os.getenv("FIRESTORE_COLLECTION", "queries")
    )

    # ── Frontend → backend wiring ─────────────────────────────────────────
    # The Streamlit app reads this so the same code points at localhost in
    # dev and a Cloud Run URL in production.
    api_url: str = field(default_factory=lambda: os.getenv("FDA_API_URL", "http://localhost:8000"))

    # ── Logging ───────────────────────────────────────────────────────────
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    @property
    def has_anthropic_key(self) -> bool:
        """True if an Anthropic API key is configured."""
        return bool(self.anthropic_api_key)


# Module-level singleton imported across the codebase.
settings = Settings()
