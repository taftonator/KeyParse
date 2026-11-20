@echo off
cd /d "%~dp0"
(
echo === python ===
where python
python --version
where py
py --version
echo === wow registry ===
reg query "HKLM\SOFTWARE\WOW6432Node\Blizzard Entertainment\World of Warcraft" /v InstallPath
echo === done ===
) > check_log.txt 2>&1
