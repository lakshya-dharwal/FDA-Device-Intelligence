"""
Centralized application settings for model selection, pricing, and runtime limits.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_DB = PROJECT_ROOT / "telemetry.db"

MODEL_PRICING = {
    "claude-sonnet-4-5": {
        "input_cost_per_mtok": 3.0,
        "output_cost_per_mtok": 15.0,
    }
}


@dataclass(frozen=True)
class AppSettings:
    environment: str
    log_level: str
    database_url: str
    anthropic_api_key: str | None
    anthropic_model: str
    anthropic_max_tokens: int
    query_timeout_seconds: float
    max_tool_iterations: int
    model_input_cost_per_mtok: float
    model_output_cost_per_mtok: float
    api_auth_token: str | None
    cors_allowed_origins: list[str]
    trusted_hosts: list[str]
    rate_limit_requests: int
    rate_limit_window_seconds: int
    frontend_backend_url: str
    frontend_request_timeout_seconds: int
    frontend_api_token: str | None


def _get_env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return int(raw_value)


def _get_env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return float(raw_value)


def _get_env_list(name: str, default: list[str]) -> list[str]:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _get_model_pricing(model_name: str) -> tuple[float, float]:
    pricing = MODEL_PRICING.get(model_name)
    if not pricing:
        raise ValueError(
            f"No default pricing configured for model '{model_name}'. "
            "Set MODEL_INPUT_COST_PER_MTOK and MODEL_OUTPUT_COST_PER_MTOK to override."
        )
    return pricing["input_cost_per_mtok"], pricing["output_cost_per_mtok"]


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Load and cache runtime settings from the environment."""
    anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    default_input_cost, default_output_cost = _get_model_pricing(anthropic_model)
    api_auth_token = os.getenv("API_AUTH_TOKEN")

    return AppSettings(
        environment=os.getenv("APP_ENV", "development"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        database_url=os.getenv(
            "DATABASE_URL",
            f"sqlite:///{DEFAULT_SQLITE_DB}",
        ),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        anthropic_model=anthropic_model,
        anthropic_max_tokens=_get_env_int("ANTHROPIC_MAX_TOKENS", 4096),
        query_timeout_seconds=_get_env_float("FDA_QUERY_TIMEOUT_SECONDS", 45.0),
        max_tool_iterations=_get_env_int("FDA_QUERY_MAX_TOOL_ITERATIONS", 8),
        model_input_cost_per_mtok=_get_env_float(
            "MODEL_INPUT_COST_PER_MTOK",
            default_input_cost,
        ),
        model_output_cost_per_mtok=_get_env_float(
            "MODEL_OUTPUT_COST_PER_MTOK",
            default_output_cost,
        ),
        api_auth_token=api_auth_token,
        cors_allowed_origins=_get_env_list(
            "CORS_ALLOWED_ORIGINS",
            [
                "http://localhost:8501",
                "http://127.0.0.1:8501",
            ],
        ),
        trusted_hosts=_get_env_list(
            "TRUSTED_HOSTS",
            [
                "testserver",
                "localhost",
                "127.0.0.1",
                "*.localhost",
            ],
        ),
        rate_limit_requests=_get_env_int("RATE_LIMIT_REQUESTS", 60),
        rate_limit_window_seconds=_get_env_int("RATE_LIMIT_WINDOW_SECONDS", 60),
        frontend_backend_url=os.getenv(
            "FRONTEND_BACKEND_URL",
            "http://localhost:8000",
        ),
        frontend_request_timeout_seconds=_get_env_int(
            "FRONTEND_REQUEST_TIMEOUT_SECONDS",
            30,
        ),
        frontend_api_token=os.getenv("FRONTEND_API_TOKEN", api_auth_token),
    )
