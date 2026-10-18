@echo off
rem Run Slim11 Builder from a source checkout (Windows).
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || exit /b 1
  .venv\Scripts\pip install -q -e . || exit /b 1
)
.venv\Scripts\python -m slim11 %*
