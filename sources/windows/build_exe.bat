@echo off
rem Builds dist\NGT_Studio (Windows 64-bit, Python 3.12 from python.org required)
cd /d "%~dp0.."
python windows\build_exe.py
pause
