@echo off
rem Abre o Assistente sem deixar uma janela preta aberta.
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" app.py
) else (
  start "" pythonw app.py
)
