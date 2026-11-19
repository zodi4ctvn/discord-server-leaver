@echo off
setlocal
title Discord Server Leaver
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

rem --- First run: create .venv if missing ---
if not exist ".venv\Scripts\python.exe" (
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
) else (
    rem --- Repair pip or editable package path if folder was moved / partially cleaned ---
    ".venv\Scripts\python.exe" -c "import leaver" >nul 2>&1 || (
        echo Paketler onariliyor, lutfen bekleyin...
        ".venv\Scripts\python.exe" -m pip --version >nul 2>&1 || (
            ".venv\Scripts\python.exe" -m ensurepip --upgrade >nul 2>&1 || goto :fail
        )
        ".venv\Scripts\python.exe" -m pip install -q -e . || goto :fail
    )
)

cls
".venv\Scripts\python.exe" -m leaver.main
echo.
pause
exit /b 0

:fail
echo [HATA] Kurulum basarisiz oldu.
pause
exit /b 1
