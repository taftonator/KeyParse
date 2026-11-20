@echo off
rem Builds dist\KeyParseCompanion.exe from companion.py, then smoke-tests it. Output goes to build_log.txt.
cd /d "%~dp0"
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
(
echo === install build tools ===
"%PY%" -m pip install --disable-pip-version-check --quiet pyinstaller requests
echo === build ===
"%PY%" -m PyInstaller --noconfirm --clean --onefile --console --name KeyParseCompanion --distpath dist --workpath build --specpath build companion.py
echo build exit code %errorlevel%
echo === smoke test: look up one player with the exe, using your key in %%LOCALAPPDATA%%\KeyParse ===
dist\KeyParseCompanion.exe lookup Taftonator-Dalaran
echo test exit code %errorlevel%
echo === done ===
) > build_log.txt 2>&1
