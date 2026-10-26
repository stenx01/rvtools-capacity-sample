@echo off
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements.txt
echo.
echo Setup complete.
echo 1. Copy weekly RVTools .xlsx files into data\raw
echo 2. .\rvcap.bat ingest
echo 3. .\rvcap.bat report --period monthly
