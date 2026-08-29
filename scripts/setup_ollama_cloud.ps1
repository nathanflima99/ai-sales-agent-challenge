param(
    [switch]$GoldenSet
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Fail([string]$Message) {
    Write-Host "`nERRO: $Message" -ForegroundColor Red
    exit 1
}

Write-Host "AI Sales Agent - configuracao automatica do Ollama Cloud" -ForegroundColor Green
Write-Host "Voce so precisa informar sua OLLAMA_API_KEY. A chave nao sera exibida na tela."

# 1. Localiza Python.
$PythonBootstrap = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonBootstrap = @("py", "-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonBootstrap = @("python")
} else {
    Fail "Python 3.11+ nao foi encontrado. Instale Python e execute novamente."
}

Write-Step "Verificando Python"
if ($PythonBootstrap.Count -eq 2) {
    & $PythonBootstrap[0] $PythonBootstrap[1] --version
} else {
    & $PythonBootstrap[0] --version
}
if ($LASTEXITCODE -ne 0) {
    Fail "Nao foi possivel executar o Python."
}

# 2. Le a chave sem ecoar no terminal.
Write-Step "Informe sua API key do Ollama Cloud"
$SecureKey = Read-Host "OLLAMA_API_KEY" -AsSecureString
$Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
try {
    $ApiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
}
if ([string]::IsNullOrWhiteSpace($ApiKey)) {
    Fail "A API key nao pode ficar vazia."
}

# 3. Valida a chave e descobre automaticamente um Qwen 3.5 disponivel.
Write-Step "Validando a chave e consultando modelos disponiveis"
$Headers = @{ Authorization = "Bearer $ApiKey" }
try {
    $Tags = Invoke-RestMethod -Method Get -Uri "https://ollama.com/api/tags" -Headers $Headers -TimeoutSec 30
} catch {
    Fail "Ollama Cloud recusou a conexao/chave: $($_.Exception.Message)"
}

$Models = @($Tags.models)
if ($Models.Count -eq 0) {
    Fail "A conta respondeu, mas nenhum modelo foi retornado por /api/tags."
}

$Preferred = $Models | Where-Object { $_.name -eq "qwen3.5:397b" } | Select-Object -First 1
if (-not $Preferred) {
    $Preferred = $Models | Where-Object { $_.name -like "qwen3.5*" } | Select-Object -First 1
}
if (-not $Preferred) {
    $Available = ($Models | ForEach-Object { $_.name }) -join ", "
    Fail "Nenhum Qwen 3.5 foi encontrado para esta conta. Modelos retornados: $Available"
}
$ModelName = [string]$Preferred.name
Write-Host "Modelo selecionado automaticamente: $ModelName" -ForegroundColor Green

# 4. Cria o ambiente virtual se necessario.
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Step "Criando .venv"
    if ($PythonBootstrap.Count -eq 2) {
        & $PythonBootstrap[0] $PythonBootstrap[1] -m venv .venv
    } else {
        & $PythonBootstrap[0] -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) {
        Fail "Falha ao criar o ambiente virtual."
    }
}

# 5. Instala/atualiza as dependencias do projeto.
Write-Step "Instalando dependencias"
& $VenvPython -m pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) {
    Fail "Falha ao instalar as dependencias."
}

# 6. Cria .env local. Nunca grava a chave no repositorio.
Write-Step "Criando .env local"
$EnvPath = Join-Path $RepoRoot ".env"
# So o que e especifico da nuvem. Repetir os defaults aqui ja causou desvio: este
# arquivo ficou com MAX_AGENT_TURNS=6 e OLLAMA_THINKING=false depois que as duas
# coisas mudaram em app/config.py, e o .env vence o default - entao a instalacao
# guiada entregava silenciosamente a configuracao antiga. O que nao esta aqui vem
# de app/config.py e acompanha as medicoes.
$EnvText = @"
LLM_PROVIDER=ollama
LLM_MODEL=$ModelName
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_API_KEY=$ApiKey
LLM_TIMEOUT_SECONDS=600
"@
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($EnvPath, $EnvText, $Utf8NoBom)
Write-Host ".env criado. Ele esta no .gitignore e nao deve ser commitado." -ForegroundColor Green

# A variavel com a chave nao e mais necessaria em memoria apos gravar o .env.
$ApiKey = $null
$SecureKey = $null
$Headers = $null

# 7. Executa um smoke test deterministico rapido antes de subir a API.
Write-Step "Rodando testes de configuracao/provider"
& $VenvPython -m pytest tests/test_model.py -q
if ($LASTEXITCODE -ne 0) {
    Fail "Os testes de configuracao/provider falharam."
}

# 8. Sobe o Sales Agent em background.
Write-Step "Iniciando Sales Agent em http://127.0.0.1:8000"
$ServerArgs = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000")
$Server = Start-Process -FilePath $VenvPython -ArgumentList $ServerArgs -WorkingDirectory $RepoRoot -PassThru

$Ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if ($Server.HasExited) {
        Fail "O servidor encerrou durante a inicializacao."
    }
    try {
        $Health = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3
        if ($Health.status -eq "ok") {
            $Ready = $true
            break
        }
    } catch {
        # Ainda inicializando.
    }
}
if (-not $Ready) {
    try { Stop-Process -Id $Server.Id -Force -ErrorAction SilentlyContinue } catch {}
    Fail "O /health nao ficou pronto em 30 segundos."
}

Write-Host "Health OK: provider=$($Health.provider), model=$($Health.model), llm=$($Health.llm)" -ForegroundColor Green

# 9. Faz uma pergunta conhecida para validar LLM -> tool -> DuckDB -> resposta.
Write-Step "Executando smoke test real do agente"
$AskBody = @{ question = "Qual produto foi mais vendido?" } | ConvertTo-Json
try {
    $Answer = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/ask" `
        -ContentType "application/json" -Body $AskBody -TimeoutSec 600
} catch {
    try { Stop-Process -Id $Server.Id -Force -ErrorAction SilentlyContinue } catch {}
    Fail "O /ask falhou: $($_.Exception.Message)"
}

Write-Host "`nResposta do agente:" -ForegroundColor Green
Write-Host $Answer.answer
Write-Host "`nTurnos: $($Answer.metadata.turns) | Tempo: $([math]::Round($Answer.metadata.total_ms / 1000, 1)) s"

if ($Answer.answer -notmatch "Product_1359") {
    Write-Warning "O agente respondeu, mas o smoke test nao encontrou Product_1359 na resposta. Rode o golden set antes de aprovar a mudanca."
} else {
    Write-Host "Smoke test aprovado: Product_1359 encontrado." -ForegroundColor Green
}

# 10. Opcionalmente roda o golden set completo, sem pedir novas entradas.
if ($GoldenSet) {
    Write-Step "Rodando golden set completo"
    & $VenvPython evals/run_evals.py
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "O golden set terminou com pelo menos um caso reprovado."
    }
}

Write-Step "Abrindo a interface"
Start-Process "http://127.0.0.1:8000"

Write-Host "`nPRONTO." -ForegroundColor Green
Write-Host "O Sales Agent ficou rodando em http://127.0.0.1:8000"
Write-Host "Para encerrar, finalize o processo Python/uvicorn (PID $($Server.Id))."
if (-not $GoldenSet) {
    Write-Host "Para rodar depois o golden set completo:"
    Write-Host ".\.venv\Scripts\python.exe evals\run_evals.py"
}
