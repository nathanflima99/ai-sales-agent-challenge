"""Configuração dos providers sem chamadas de rede."""

import httpx
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.agent.model import BearerAuth, build_model
from app.config import Settings


def test_ollama_defaults_to_thinking_disabled() -> None:
    settings = Settings(_env_file=None, llm_provider="ollama")

    model = build_model(settings)

    assert isinstance(model, ChatOllama)
    assert settings.ollama_thinking is False
    assert model.reasoning is False


def test_ollama_cloud_sends_bearer_api_key() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        llm_model="qwen3.5:397b",
        ollama_base_url="https://ollama.com",
        ollama_api_key="ollama-secret",
    )

    model = build_model(settings)

    assert isinstance(model, ChatOllama)
    auth = model.client_kwargs["auth"]
    assert isinstance(auth, BearerAuth)
    assert "ollama-secret" not in repr(settings)
    assert "ollama-secret" not in str(settings.model_dump())


def test_bearer_auth_signs_the_request_without_leaking_the_key() -> None:
    """A chave precisa chegar ao servidor sem sobrar em `repr`.

    Guardar o header pronto em `client_kwargs` materializaria a chave numa
    string comum dentro do modelo, e ela reapareceria em `repr(model)` — bastaria
    um log de depuração com o objeto para vazá-la.
    """
    settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        ollama_base_url="https://ollama.com",
        ollama_api_key="ollama-secret",
    )

    model = build_model(settings)
    request = httpx.Request("POST", "https://ollama.com/api/chat")
    signed = next(model.client_kwargs["auth"].auth_flow(request))

    assert signed.headers["Authorization"] == "Bearer ollama-secret"
    assert "ollama-secret" not in repr(model)
    assert "ollama-secret" not in repr(model.client_kwargs)


def test_ollama_receives_the_configured_timeout() -> None:
    """`ChatOllama` não expõe `timeout`; ele vai pelo cliente httpx.

    Sem isto, `LLM_TIMEOUT_SECONDS` valeria só para a OpenAI e uma requisição
    pendurada seguraria uma thread do pool do FastAPI sem limite.
    """
    settings = Settings(_env_file=None, llm_provider="ollama", llm_timeout_seconds=600)

    model = build_model(settings)

    assert model.client_kwargs["timeout"] == 600


def test_direct_ollama_cloud_without_key_is_unconfigured() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        ollama_base_url="https://ollama.com",
    )

    assert settings.ollama_is_direct_cloud is True
    assert settings.ollama_api_key is None
    assert settings.llm_configured is False


def test_local_ollama_does_not_require_api_key() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="ollama",
        ollama_base_url="http://localhost:11434",
    )

    model = build_model(settings)

    assert settings.llm_configured is True
    assert isinstance(model, ChatOllama)
    # Sem chave, o único ajuste de cliente é o timeout.
    assert "auth" not in model.client_kwargs
    assert model.client_kwargs["timeout"] == settings.llm_timeout_seconds


def test_ollama_settings_are_loaded_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_MODEL", "qwen3.5:397b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.com")
    monkeypatch.setenv("OLLAMA_API_KEY", "cloud-key")
    monkeypatch.setenv("OLLAMA_THINKING", "false")

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "ollama"
    assert settings.resolved_model == "qwen3.5:397b"
    assert settings.ollama_base_url == "https://ollama.com"
    assert settings.ollama_api_key is not None
    assert settings.ollama_api_key.get_secret_value() == "cloud-key"
    assert settings.ollama_thinking is False
    assert settings.llm_configured is True


def test_openai_builder_is_not_affected_by_ollama_options() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="openai",
        openai_api_key="sk-test-not-real",
        ollama_api_key="ollama-secret",
        ollama_thinking=True,
    )

    model = build_model(settings)

    assert isinstance(model, ChatOpenAI)
