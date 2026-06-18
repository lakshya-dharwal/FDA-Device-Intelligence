from src.backend import settings


def test_get_settings_uses_defaults(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MAX_TOKENS", raising=False)
    monkeypatch.delenv("FDA_QUERY_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("FDA_QUERY_MAX_TOOL_ITERATIONS", raising=False)
    monkeypatch.delenv("MODEL_INPUT_COST_PER_MTOK", raising=False)
    monkeypatch.delenv("MODEL_OUTPUT_COST_PER_MTOK", raising=False)
    settings.get_settings.cache_clear()

    app_settings = settings.get_settings()

    assert app_settings.anthropic_model == "claude-sonnet-4-5"
    assert app_settings.anthropic_max_tokens == 4096
    assert app_settings.query_timeout_seconds == 45.0
    assert app_settings.max_tool_iterations == 8
    assert app_settings.model_input_cost_per_mtok == 3.0
    assert app_settings.model_output_cost_per_mtok == 15.0


def test_get_settings_respects_environment_overrides(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    monkeypatch.setenv("ANTHROPIC_MAX_TOKENS", "2048")
    monkeypatch.setenv("FDA_QUERY_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("FDA_QUERY_MAX_TOOL_ITERATIONS", "3")
    monkeypatch.setenv("MODEL_INPUT_COST_PER_MTOK", "7.5")
    monkeypatch.setenv("MODEL_OUTPUT_COST_PER_MTOK", "25.0")
    settings.get_settings.cache_clear()

    app_settings = settings.get_settings()

    assert app_settings.anthropic_model == "claude-sonnet-4-5"
    assert app_settings.anthropic_max_tokens == 2048
    assert app_settings.query_timeout_seconds == 12.5
    assert app_settings.max_tool_iterations == 3
    assert app_settings.model_input_cost_per_mtok == 7.5
    assert app_settings.model_output_cost_per_mtok == 25.0
