import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Impede que a configuração de um teste vaze para o seguinte."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch):
    """Cliente HTTP sem OPENAI_API_KEY definida."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app()) as test_client:
        yield test_client
