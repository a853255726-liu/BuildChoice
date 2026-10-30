@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\gate_audit.py serve
  goto done
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 scripts\gate_audit.py serve
) else (
  python scripts\gate_audit.py serve
)
:done
if errorlevel 1 pause
