from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.analytics.repository import AnalyticsRepository
from app.config import Settings, get_settings
from app.main import create_app

FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "sample_sales.csv"
REAL_DATASET = Path(__file__).parent.parent / "dataset" / "sales.csv"


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Impede que a configuração de um teste vaze para o seguinte."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings_override(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Substitui a configuração da aplicação por uma construída no teste.

    `_env_file=None` é o ponto central: sem ele o `Settings` continuaria lendo o
    `.env` do diretório de trabalho, e um teste "sem chave" passaria a depender de
    o desenvolvedor ter ou não configurado a máquina. O teste precisa afirmar o que
    diz afirmar, em qualquer workspace.
    """

    def _apply(**overrides: Any) -> Settings:
        overrides.setdefault("dataset_path", FIXTURE_DATASET)
        settings = Settings(_env_file=None, **overrides)
        monkeypatch.setattr("app.main.get_settings", lambda: settings)
        return settings

    return _apply


@pytest.fixture
def client(settings_override: Callable[..., Settings]) -> Iterator[TestClient]:
    """Cliente HTTP com a aplicação configurada sem credencial de LLM."""
    settings_override()
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def real_dataset_repository() -> Iterator[AnalyticsRepository]:
    """Repositório sobre o dataset completo do desafio.

    Escopo de sessão porque registrar a view e ler 200k linhas repetidas vezes
    dominaria o tempo da suíte sem aumentar a confiança.
    """
    if not REAL_DATASET.is_file():
        pytest.skip(f"dataset nao encontrado em {REAL_DATASET}")
    repository = AnalyticsRepository.open(REAL_DATASET)
    yield repository
    repository.close()
