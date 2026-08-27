FROM python:3.11-slim

# Bytecode compilado na imagem, stdout sem buffer para o log estruturado sair
# na hora, e pip silencioso sobre versão nova a cada build.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Dependências antes do código: enquanto o pyproject não mudar, esta camada é
# reaproveitada e um build após editar um .py leva segundos em vez de minutos.
# O pacote stub existe só para o backend conseguir resolver as dependências;
# ele é desinstalado em seguida, e o código real entra na camada de baixo.
COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py \
    && pip install . \
    && pip uninstall -y ai-sales-agent \
    && rm -rf app

COPY app ./app
COPY dataset ./dataset
COPY static ./static

# Usuário sem privilégios: o processo não precisa escrever nada em disco.
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /srv
USER appuser

EXPOSE 8000

# Sem curl na imagem slim, então o healthcheck usa a stdlib. Ele consulta
# /health, que responde mesmo sem LLM configurado — o container é declarado
# saudável quando a API e o dataset estão de pé, não quando há chave.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
