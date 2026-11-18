@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0" || exit /b 1
echo [Item 28] Delay improvement and low-priority throughput
python -m tools.analyze_28 --results results\matrix --out results\analysis28
set "run_exit=%errorlevel%"
if "%run_exit%"=="0" (
  echo [DONE] Results written to results\analysis28
) else (
  echo [FAILED] See the error above.
)
pause
exit /b %run_exit%
