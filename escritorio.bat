@echo off
REM ===================================================================
REM  RemotePad - Panel de escritorio
REM  Doble clic: abre la ventana con ajustes, registro y dispositivos.
REM ===================================================================
setlocal
cd /d "%~dp0escritorio"

where pythonw >nul 2>nul
if errorlevel 1 (
    echo  [ERROR] No encuentro Python en el PATH.
    echo  Instalalo desde https://www.python.org/downloads/  ^(marca "Add python.exe to PATH"^)
    echo.
    pause
    exit /b 1
)

REM La primera vez instala lo que falta (pywebview, pystray y Pillow).
pythonw -c "import webview, pystray, PIL" >nul 2>nul
if errorlevel 1 (
    echo  Instalando lo necesario para el panel ^(puede tardar un poco^)...
    python -m pip install --user -r requirements.txt
    if errorlevel 1 (
        echo  [ERROR] No se pudieron instalar las dependencias.
        pause
        exit /b 1
    )
)

start "" pythonw remotepad_escritorio.py %*
