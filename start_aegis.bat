@echo off
echo Iniciando entorno de desarrollo de AEGIS...

:: Cargar variables de entorno de forma limpia y sin espacios desde backend/.env
if exist "%~dp0backend\.env" (
    echo Cargando variables de entorno desde backend/.env...
    for /f "usebackq tokens=1,* delims==" %%i in (`powershell -Command "Get-Content '%~dp0backend\.env' | Where-Object { $_ -match '=' -and -not $_.Trim().StartsWith('#') } | ForEach-Object { $k,$v = $_ -split '=', 2; Write-Output ($k.Trim() + '=' + $v.Trim()) }"`) do (
        set "%%i=%%j"
    )
)

:: Detectar la ruta de Python (Entorno virtual local vs Python global del sistema)
set "PYTHON_PATH=python"
if exist "%~dp0backend\.venv\Scripts\python.exe" (
    echo Entorno virtual local venv detectado.
    set "PYTHON_PATH=%~dp0backend\.venv\Scripts\python.exe"
) else if exist "%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\python.exe" (
    echo Python global del sistema detectado en AppData.
    set "PYTHON_PATH=%USERPROFILE%\AppData\Local\Python\pythoncore-3.14-64\python.exe"
) else (
    echo Intentando usar comando 'python' del sistema...
)

echo Levantando contenedores Docker...
docker compose up -d

echo Iniciando worker de Celery...
start "AEGIS Celery" cmd /k "cd backend && "%PYTHON_PATH%" -m celery -A app.workers.celery_app worker --loglevel=info --pool=solo"

echo Iniciando servidor Backend (FastAPI)...
start "AEGIS Backend" cmd /k "cd backend && "%PYTHON_PATH%" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

echo Iniciando Frontend (Next.js)...
start "AEGIS Frontend" cmd /k "cd frontend && npm run dev"

echo Iniciando Tunel Seguro (Ngrok)...
start "AEGIS Tunnel" cmd /k ""%~dp0ngrok.exe" http 8000 --domain=footing-jellied-glamorous.ngrok-free.dev"

echo Todos los servicios han sido iniciados.
