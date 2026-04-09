@echo off
setlocal
set ROOT_DIR=%~dp0
cd /d "%ROOT_DIR%"
call "%ROOT_DIR%scripts\quickstart.bat"
set EXIT_CODE=%ERRORLEVEL%
echo.
if "%EXIT_CODE%"=="0" (
  echo mdcn has stopped.
) else (
  echo mdcn failed to start. Exit code: %EXIT_CODE%
)
echo.
pause
exit /b %EXIT_CODE%
