@echo off
rem craft-automation app launcher for Windows. Double-click this file.
rem Keep this file ASCII-only: cmd.exe reads it in the console code page.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 app\launch.py
) else (
  python app\launch.py
)
if errorlevel 9009 echo Python 3.10 or later is required: https://www.python.org/downloads/ ^(check "Add python.exe to PATH"^)
if errorlevel 1 pause
