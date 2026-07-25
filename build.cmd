@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0build.py" %*
) else (
    py -3 "%~dp0build.py" %*
)
