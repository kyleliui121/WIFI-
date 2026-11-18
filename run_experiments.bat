@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0" || exit /b 1
echo [Item 27] Experiment matrix
python -m wifi_sim.experiments --out results\matrix --duration 10 --seeds 42 43 44
set "run_exit=%errorlevel%"
if "%run_exit%"=="0" (
  echo [DONE] Results written to results\matrix
) else (
  echo [FAILED] See the error above.
)
pause
exit /b %run_exit%
