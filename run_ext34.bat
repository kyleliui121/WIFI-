@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set "ns3_csv=%~1"
if defined ns3_csv set "ns3_csv=%~f1"
cd /d "%~dp0" || exit /b 1
if not defined ns3_csv set "ns3_csv=data\extensions\34\ns3_crosscheck.csv"

python -c "import simpy, scipy, numpy, matplotlib, docx" >nul 2>&1
if errorlevel 1 (
    echo [FAILED] Install dependencies with python -m pip install -r requirements-report.txt
    goto failed
)
if not exist "%ns3_csv%" (
    echo [FAILED] Missing ns-3 CSV "%ns3_csv%"
    goto failed
)

set "output=results\ext34"
echo [Extension 3] Four-AC simulation and BK AIFSN sweep
python -m wifi_sim.ext34 --out "%output%" --duration 10 --seeds 42 43 44 || goto failed
python -m tools.aifs_sensitivity --out "%output%" || goto failed
echo [Extension 4] Comparing the supplied ns-3 CSV
python -m tools.build_report --results "%output%" --ns3-csv "%ns3_csv%" || goto failed
echo [DONE] Tables, figures and Word report written to "%output%"
pause
exit /b 0

:failed
echo See the error above.
pause
exit /b 1
