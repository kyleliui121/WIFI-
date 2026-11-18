@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0" || exit /b 1
echo [Optional items 1 and 2] Frame errors and hidden terminals
python -m wifi_sim.extensions
set "run_exit=%errorlevel%"
if not "%run_exit%"=="0" goto failed
python -m tools.analyze_extensions
set "run_exit=%errorlevel%"
if not "%run_exit%"=="0" goto failed
echo [DONE] Results written to results\extensions
pause
exit /b 0

:failed
echo [FAILED] See the error above.
pause
exit /b %run_exit%
