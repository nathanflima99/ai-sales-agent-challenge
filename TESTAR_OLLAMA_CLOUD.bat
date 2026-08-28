@echo off
setlocal
cd /d "%~dp0"

echo AI Sales Agent - teste automatico com Ollama Cloud
echo.
echo Voce so precisara colar sua OLLAMA_API_KEY.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_ollama_cloud.ps1"

if errorlevel 1 (
  echo.
  echo O teste terminou com erro. Veja a mensagem acima.
  pause
  exit /b 1
)

echo.
echo Configuracao concluida.
pause
