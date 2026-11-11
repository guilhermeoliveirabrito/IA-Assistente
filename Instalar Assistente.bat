@echo off
rem Primeira instalacao: cria o ambiente, instala as dependencias, prepara o .env e cria um atalho na Area de Trabalho.
cd /d "%~dp0"
title Instalar o Assistente
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo Nao encontrei o Python. Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH" e rode este arquivo de novo.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Criando o ambiente...
  %PY% -m venv .venv || ( echo Falhou ao criar o ambiente. & pause & exit /b 1 )
)
echo Instalando as dependencias (pode levar alguns minutos)...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt || ( echo Falhou ao instalar as dependencias. & pause & exit /b 1 )
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Criei o arquivo .env. Abra-o no Bloco de Notas e cole sua chave: GEMINI_API_KEY=...
)
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Assistente.lnk'); $s.TargetPath='%~dp0Abrir Assistente.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()" >nul 2>nul
echo.
echo Pronto. Use o atalho "Assistente" na Area de Trabalho ou o arquivo "Abrir Assistente.bat".
pause
