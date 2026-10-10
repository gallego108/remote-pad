@echo off
REM ===================================================================
REM  RemotePad - Lanzador para Windows
REM  Doble clic en este archivo para iniciar el servidor.
REM ===================================================================
setlocal
cd /d "%~dp0server"

echo.
echo  Comprobando Python...
where python >nul 2>nul
if errorlevel 1 (
    echo  [ERROR] No encuentro Python en el PATH.
    echo  Instalalo desde https://www.python.org/downloads/  ^(marca "Add python.exe to PATH"^)
    echo.
    pause
    exit /b 1
)

echo  Comprobando dependencias...
python -c "import aiohttp" >nul 2>nul
if errorlevel 1 (
    echo  Instalando dependencias necesarias ^(aiohttp^)...
    python -m pip install --user -r requirements.txt
    if errorlevel 1 (
        echo.
        echo  [ERROR] No se pudieron instalar las dependencias.
        echo  Prueba manualmente:  python -m pip install aiohttp
        echo.
        pause
        exit /b 1
    )
)

REM HTTPS es opcional: su dependencia solo se instala si se pide --https.
echo %* | findstr /i /c:"--https" >nul
if not errorlevel 1 (
    python -c "import cryptography" >nul 2>nul
    if errorlevel 1 (
        echo  Instalando lo necesario para HTTPS ^(cryptography^)...
        python -m pip install --user cryptography
    )
)

echo  Iniciando RemotePad...
echo.
python app.py %*
echo.
echo  El servidor se ha detenido.
pause
