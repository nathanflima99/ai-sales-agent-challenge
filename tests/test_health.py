"""Fase 1: a aplicação sobe e responde /health mesmo sem credencial de LLM."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import AgentLoopError, AppError, LLMNotConfiguredError, SQLValidationError
from app.main import create_app


def test_health_ok_without_api_key(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "llm": "unconfigured"}


def test_health_reports_configured_llm(settings_override):
    settings_override(openai_api_key="sk-test-not-a-real-key")

    with TestClient(create_app()) as client:
        assert client.get("/health").json()["llm"] == "configured"


def test_settings_defaults_without_api_key():
    settings = Settings(_env_file=None)

    assert settings.openai_api_key is None
    assert settings.llm_configured is False
    assert settings.max_agent_turns == 6


def test_api_key_is_not_exposed_by_repr():
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


def test_client_error_keeps_actionable_message():
    """Em 4xx a mensagem é acionável e deve chegar ao cliente."""
    app = create_app()

    @app.get("/boom-4xx")
    def boom() -> None:
        raise SQLValidationError("Only SELECT statements are allowed")

    with TestClient(app) as client:
        response = client.get("/boom-4xx")

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "sql_validation_error",
            "message": "Only SELECT statements are allowed",
        }
    }
    assert "Traceback" not in response.text


def test_server_error_does_not_leak_internal_detail():
    """Em 5xx a mensagem de domínio pode conter caminho ou detalhe de infra."""
    app = create_app()

    @app.get("/boom-5xx")
    def boom() -> None:
        raise AgentLoopError("failed reading /srv/secret/dataset/sales.csv")

    with TestClient(app) as client:
        response = client.get("/boom-5xx")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "agent_loop_error", "message": "Internal server error"}
    }
    assert "/srv/secret" not in response.text
    assert "Traceback" not in response.text


def test_llm_not_configured_keeps_actionable_message():
    """503 de configuração é 5xx, mas a mensagem é a instrução — deve chegar."""
    app = create_app()

    @app.get("/boom-503")
    def boom() -> None:
        raise LLMNotConfiguredError("OPENAI_API_KEY is not set")

    with TestClient(app) as client:
        response = client.get("/boom-503")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "llm_not_configured", "message": "OPENAI_API_KEY is not set"}
    }


def test_blank_api_key_counts_as_unconfigured():
    """`docker compose` com variável não definida no host injeta string vazia."""
    for blank in ("", "   "):
        settings = Settings(_env_file=None, openai_api_key=blank)

        assert settings.openai_api_key is None
        assert settings.llm_configured is False
