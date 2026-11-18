@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0" || exit /b 1
echo [Item 26] NPCA verification and switch-delay sweep
python -m tools.demo_npca --duration 10 --seeds 42 43 44 --out results\npca
set "run_exit=%errorlevel%"
if "%run_exit%"=="0" (
  echo [DONE] Results written to results\npca
) else (
  echo [FAILED] See the error above.
)
pause
exit /b %run_exit%
