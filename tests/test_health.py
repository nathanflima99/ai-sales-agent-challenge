"""Fase 1: a aplicação sobe e responde /health mesmo sem credencial de LLM."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import AppError, LLMNotConfiguredError, SQLValidationError
from app.main import create_app


def test_health_ok_without_api_key(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "llm": "unconfigured"}


def test_health_reports_configured_llm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")

    with TestClient(create_app()) as client:
        assert client.get("/health").json()["llm"] == "configured"


def test_settings_defaults_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.openai_api_key is None
    assert settings.llm_configured is False
    assert settings.max_agent_turns == 6


def test_api_key_is_not_exposed_by_repr(monkeypatch):
    """SecretStr precisa mascarar a chave em log, repr e serialização."""
    settings = Settings(_env_file=None, openai_api_key="sk-super-secret")

    assert "sk-super-secret" not in repr(settings)
    assert "sk-super-secret" not in str(settings.model_dump())
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "sk-super-secret"


def test_domain_errors_carry_status_and_code():
    assert issubclass(LLMNotConfiguredError, AppError)
    assert LLMNotConfiguredError("no key").status_code == 503
    assert SQLValidationError("bad sql").code == "sql_validation_error"


def test_app_error_is_translated_without_stack_trace():
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise SQLValidationError("Only SELECT statements are allowed")

    with TestClient(app) as client:
        response = client.get("/boom")

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "sql_validation_error",
            "message": "Only SELECT statements are allowed",
        }
    }
    assert "Traceback" not in response.text
