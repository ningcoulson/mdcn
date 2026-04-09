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

set CREATED_CONFIG=0
if not exist "config.toml" (
  copy /Y "config.example.toml" "config.toml" >nul
  set CREATED_CONFIG=1
)

echo.
echo mdcn quickstart is ready.
echo Config file: %ROOT_DIR%\config.toml
if "%CREATED_CONFIG%"=="1" (
  echo A new config.toml was created from the example file.
)
echo First-time setup:
echo   1. Fill in your source folder
echo   2. Fill in your target folder
echo   3. Click "保存并开始刮削" in the browser page
echo Launching local config UI...
echo.

python -m mdcn.app.cli config-ui --config config.toml
