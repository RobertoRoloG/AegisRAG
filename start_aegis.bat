@echo off
title AEGIS - Consola Unificada y Panel de Control
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   Iniciando Consola Unificada de AEGIS...
echo ============================================================

:: Cargar variables de entorno desde backend/.env
if exist "%~dp0backend\.env" (
    for /f "usebackq tokens=1,* delims==" %%i in (`powershell -Command "Get-Content '%~dp0backend\.env' | Where-Object { $_ -match '=' -and -not $_.Trim().StartsWith('#') } | ForEach-Object { $k,$v = $_ -split '=', 2; Write-Output ($k.Trim() + '=' + $v.Trim()) }"`) do (
        set "%%i=%%j"
    )
)

:: Detectar ejecutable de Python
set "PYTHON_PATH=python"
if exist "%~dp0backend\.venv\Scripts\python.exe" (
    "%~dp0backend\.venv\Scripts\python.exe" -c "import sys" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_PATH=%~dp0backend\.venv\Scripts\python.exe"
    )
)

if "%PYTHON_PATH%"=="python" (
    if exist "C:\Python314\python.exe" (
        set "PYTHON_PATH=C:\Python314\python.exe"
    ) else if exist "%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\python.exe" (
        set "PYTHON_PATH=%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\python.exe"
    )
)

:: Ejecutar la consola unificada con supervisor integrado
"%PYTHON_PATH%" "%~dp0aegis_console.py"

pause
