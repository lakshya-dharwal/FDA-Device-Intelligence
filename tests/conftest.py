import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backend import telemetry
from src.backend import claude_client, settings
from src.backend.main import app


@pytest.fixture(autouse=True)
def isolated_telemetry_db(tmp_path, monkeypatch):
    db_path = tmp_path / "telemetry.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv(
        "TRUSTED_HOSTS",
        "testserver,localhost,127.0.0.1,*.localhost",
    )
    settings.get_settings.cache_clear()
    telemetry.get_engine.cache_clear()
    telemetry.get_session_factory.cache_clear()
    telemetry.init_db()
    return db_path


@pytest.fixture(autouse=True)
def clear_cached_settings():
    settings.get_settings.cache_clear()
    claude_client.get_anthropic_client.cache_clear()
    telemetry.get_engine.cache_clear()
    telemetry.get_session_factory.cache_clear()
    yield
    settings.get_settings.cache_clear()
    claude_client.get_anthropic_client.cache_clear()
    telemetry.get_engine.cache_clear()
    telemetry.get_session_factory.cache_clear()


@pytest.fixture
def api_client():
    def request(method: str, path: str, **kwargs):
        async def run_request():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(run_request())

    return request
