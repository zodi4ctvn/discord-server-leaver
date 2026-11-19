@echo off
setlocal
title Discord Server Leaver
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

rem --- First run: create the virtual environment and install the tool ---
if not exist ".venv\Scripts\dsl.exe" (
    echo Ilk kurulum yapiliyor, lutfen bekleyin...
    set "PY="
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    if not defined PY (
        where py >nul 2>&1 && set "PY=py -3"
    )
    if not defined PY (
        python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
    )
    if not defined PY (
        echo [HATA] Python 3.11+ bulunamadi. https://www.python.org/downloads/ adresinden kurun.
        pause
        exit /b 1
    )
    call %%PY%% -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install -q --upgrade pip || goto :fail
    ".venv\Scripts\python.exe" -m pip install -q -e . || goto :fail
    echo Kurulum tamamlandi.
    echo.
)

cls
".venv\Scripts\dsl.exe"
echo.
pause
exit /b 0

:fail
echo [HATA] Kurulum basarisiz oldu.
pause
exit /b 1
