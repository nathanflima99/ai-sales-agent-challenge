"""Configuração dos providers sem chamadas de rede."""

from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.agent.model import build_model
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
    assert model.client_kwargs == {
        "headers": {"Authorization": "Bearer ollama-secret"}
    }
    assert "ollama-secret" not in repr(settings)
    assert "ollama-secret" not in str(settings.model_dump())


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
    assert model.client_kwargs == {}


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
