@echo off
rem Atualiza o Assistente para a versao mais recente do GitHub. Seus dados (.env, data, memory, credenciais) nao sao tocados.
cd /d "%~dp0"
title Atualizar o Assistente
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)
echo Feche o Assistente antes de continuar (se estiver aberto).
pause
"%PY%" -m assistente.servicos.atualizador
echo.
pause
