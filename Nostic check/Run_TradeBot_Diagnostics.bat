@echo off
setlocal

set "SCRIPT=%~dp0TradeBot_Diagnostic_Collector.ps1"

if not exist "%SCRIPT%" (
    echo ERROR: Could not find:
    echo %SCRIPT%
    echo.
    echo Put this launcher in the same folder as TradeBot_Diagnostic_Collector.ps1
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"

echo.
echo Finished or stopped with an error above.
pause
