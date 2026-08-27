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

    @property
    def expose_message(self) -> bool:
        """Se a mensagem pode ser devolvida ao cliente.

        Erros 4xx são acionáveis por quem chamou — o guard de SQL precisa explicar
        o que rejeitou. Erros 5xx podem carregar caminho de arquivo ou detalhe de
        infraestrutura, então o padrão é esconder. Subclasses cuja mensagem é
        seguramente pública sobrescrevem isto.
        """
        return self.status_code < 500


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
    """Nenhuma credencial de LLM configurada.

    A mensagem é devolvida ao cliente apesar do status 5xx: ela diz como
    configurar a aplicação e não revela nada sobre o servidor. Esconder isso
    transformaria um erro de operação evidente num 500 opaco.
    """

    code = "llm_not_configured"

    @property
    def expose_message(self) -> bool:
        return True


class AgentLoopError(AppError):
    """O agente não convergiu dentro da cota de turnos."""

    status_code = 500
    code = "agent_loop_error"
