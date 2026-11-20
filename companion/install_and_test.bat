@echo off
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
(
echo === install python ===
if exist "%PY%" (echo already installed) else (
  winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
)
echo === python version ===
"%PY%" --version
echo === pip install ===
"%PY%" -m pip install --disable-pip-version-check -r requirements.txt
echo === lookup test ===
"%PY%" companion.py lookup Taftonator-Dalaran
echo === done ===
) > install_log.txt 2>&1
