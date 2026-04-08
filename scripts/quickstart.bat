@echo off
setlocal
set ROOT_DIR=%~dp0..
cd /d "%ROOT_DIR%"

where python >nul 2>nul
if errorlevel 1 (
  echo python not found. Please install Python 3.11+ first.
  exit /b 1
)

if not exist ".venv" (
  python -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
python -m pip install -e .[dev]

if not exist "config.toml" (
  copy /Y "config.example.toml" "config.toml" >nul
)

echo.
echo mdcn quickstart is ready.
echo Config file: %ROOT_DIR%\config.toml
echo Launching local config UI...
echo.

python -m mdcn.app.cli config-ui --config config.toml
