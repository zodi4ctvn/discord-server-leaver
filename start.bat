@echo off
setlocal
title Discord Server Leaver
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

rem --- First run: create .venv if missing ---
if not exist ".venv\Scripts\python.exe" (
    echo [TR] Ilk kurulum yapiliyor, lutfen bekleyin...
    echo [EN] Running first-time setup, please wait...
    set "PY_EXE="
    set "PY_ARGS="

    where py >nul 2>&1 && (
        py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && (
            set "PY_EXE=py"
            set "PY_ARGS=-3"
        )
    )
    if not defined PY_EXE (
        for %%V in (314 313 312 311) do (
            if not defined PY_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
                "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
            )
        )
    )
    if not defined PY_EXE (
        where python >nul 2>&1 && (
            python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY_EXE=python"
        )
    )
    if not defined PY_EXE (
        echo [TR][HATA] Python 3.11+ bulunamadi. https://www.python.org/downloads/ adresinden kurun.
        echo [EN][ERROR] Python 3.11+ not found. Install it from https://www.python.org/downloads/
        pause
        exit /b 1
    )

    "%PY_EXE%" %PY_ARGS% -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install -q --upgrade pip || goto :fail
    ".venv\Scripts\python.exe" -m pip install -q -e . || goto :fail
    echo [TR] Kurulum tamamlandi. / [EN] Setup complete.
    echo.
) else (
    rem --- Repair pip or editable package path if folder was moved / partially cleaned ---
    ".venv\Scripts\python.exe" -c "import leaver" >nul 2>&1 || (
        echo [TR] Paketler onariliyor, lutfen bekleyin...
        echo [EN] Repairing packages, please wait...
        ".venv\Scripts\python.exe" -m pip --version >nul 2>&1 || (
            ".venv\Scripts\python.exe" -m ensurepip --upgrade >nul 2>&1 || goto :fail
        )
        ".venv\Scripts\python.exe" -m pip install -q -e . || goto :fail
    )
)

cls
".venv\Scripts\python.exe" -m leaver
echo.
pause
exit /b 0

:fail
echo [TR][HATA] Kurulum basarisiz oldu.
echo [EN][ERROR] Setup failed.
pause
exit /b 1
