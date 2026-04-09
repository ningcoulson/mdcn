@echo off
setlocal
set ROOT_DIR=%~dp0..
cd /d "%ROOT_DIR%"
if "%USERPROFILE%"=="" (
  set STATE_DIR=%ROOT_DIR%\.mdcn
) else (
  set STATE_DIR=%USERPROFILE%\.mdcn
)
set VENV_DIR=%STATE_DIR%\.venv
set STAMP_FILE=%VENV_DIR%\.mdcn_bootstrap_stamp

echo Preparing mdcn...
if not exist "%STATE_DIR%" mkdir "%STATE_DIR%"
echo Python environment: %VENV_DIR%

where python >nul 2>nul
if errorlevel 1 (
  echo python not found. Please install Python 3.11+ first.
  exit /b 1
)

if not exist "%VENV_DIR%" (
  goto CREATE_VENV
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  goto REPAIR_VENV
)

if not exist "%VENV_DIR%\Scripts\pip.exe" (
  goto REPAIR_VENV
)

goto ACTIVATE_VENV

:REPAIR_VENV
echo Repairing broken Python virtual environment...
rmdir /s /q "%VENV_DIR%"

:CREATE_VENV
echo Creating Python virtual environment...
python -m venv "%VENV_DIR%"

:ACTIVATE_VENV
call "%VENV_DIR%\Scripts\activate.bat"

for /f %%i in ('python -c "from pathlib import Path; import hashlib; print(hashlib.sha256(Path('pyproject.toml').read_bytes()).hexdigest())"') do set BOOTSTRAP_HASH=%%i
set NEEDS_INSTALL=1
set RUNTIME_READY=0
python -c "import mdcn, httpx, parsel" >nul 2>nul
if not errorlevel 1 set RUNTIME_READY=1

if exist "%STAMP_FILE%" (
  set /p CURRENT_STAMP=<"%STAMP_FILE%"
  if "%CURRENT_STAMP%"=="%BOOTSTRAP_HASH%" (
    if "%RUNTIME_READY%"=="1" set NEEDS_INSTALL=0
  )
)

if not exist "%STAMP_FILE%" (
  if "%RUNTIME_READY%"=="1" (
    >"%STAMP_FILE%" echo %BOOTSTRAP_HASH%
    set NEEDS_INSTALL=0
  )
)

if "%NEEDS_INSTALL%"=="1" (
  echo Installing or updating dependencies...
  echo This can take 1-3 minutes on first launch.
  python -m pip install --upgrade pip
  python -m pip install -e .[dev]
  >"%STAMP_FILE%" echo %BOOTSTRAP_HASH%
) else (
  echo Python environment is already ready.
)

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
echo Launching local config UI at http://127.0.0.1:8765 ...
echo If the browser does not open automatically, copy this address into your browser.
echo.

python -m mdcn.app.cli config-ui --config config.toml
