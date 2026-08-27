"""Exceções de domínio.

Toda falha esperada da aplicação herda de `AppError` e carrega o status HTTP e um
código estável. Isso permite um único `exception_handler` no lugar de try/except
espalhado por rota, e garante que nenhum stack trace vaze no corpo da resposta.
"""


class AppError(Exception):
    """Falha esperada da aplicação, traduzível para uma resposta HTTP."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DatasetError(AppError):
    """Dataset ausente, ilegível ou com schema incompatível."""

    status_code = 500
    code = "dataset_error"


class SQLValidationError(AppError):
    """SQL rejeitado pelo guard antes de chegar ao banco."""

    status_code = 400
    code = "sql_validation_error"


class QueryExecutionError(AppError):
    """SQL válido para o guard, mas que falhou na execução."""

    status_code = 400
    code = "query_execution_error"


class LLMError(AppError):
    """Falha na comunicação com o provedor de LLM."""

    status_code = 503
    code = "llm_error"


class LLMNotConfiguredError(LLMError):
    """Nenhuma credencial de LLM configurada."""

    code = "llm_not_configured"


class AgentLoopError(AppError):
    """O agente não convergiu dentro da cota de turnos."""

    status_code = 500
    code = "agent_loop_error"
