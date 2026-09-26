@echo off
REM ===================================================================
REM  RemotePad - Verificacion completa
REM  Arranca un servidor temporal, ejecuta todas las pruebas y lo para.
REM ===================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set PORT=8791
set LOG=%TEMP%\remotepad_test.log

echo.
echo  ============================================================
echo   RemotePad - comprobando el proyecto
echo  ============================================================
echo.

echo  [1/4] Sintaxis de Python...
python -m py_compile server\app.py server\qr.py server\controller.py server\native_input.py >nul 2>nul
if errorlevel 1 (
    echo        FALLO
    python -m py_compile server\app.py server\qr.py server\controller.py server\native_input.py
    exit /b 1
)
echo        correcta

echo  [2/4] Coherencia de la interfaz (HTML/CSS/JS)...
python tools\check_ui.py >nul 2>nul
if errorlevel 1 (
    echo        FALLO
    python tools\check_ui.py
    exit /b 1
)
echo        correcta

echo  [3/4] Arrancando servidor de pruebas en el puerto %PORT%...
start /b cmd /c "cd server && python app.py --port %PORT% --no-browser > ""%LOG%"" 2>&1"

REM Esperamos a que aparezca el PIN en el registro.
set PIN=
for /l %%i in (1,1,30) do (
    if not defined PIN (
        timeout /t 1 /nobreak >nul
        for /f "tokens=*" %%l in ('findstr /r "PIN DE ACCESO" "%LOG%" 2^>nul') do (
            for /f "tokens=4,5" %%a in ("%%l") do set PIN=%%a%%b
        )
    )
)

if not defined PIN (
    echo        FALLO: el servidor no arranco. Registro:
    type "%LOG%"
    exit /b 1
)
echo        servidor listo (PIN !PIN!)

echo  [4/4] Pruebas de extremo a extremo...
python tools\test_qr.py
if errorlevel 1 set RESULT=1
python tools\test_client.py --port %PORT% --pin !PIN! --cursor
if errorlevel 1 set RESULT=1
python tools\test_drag.py --port %PORT% --pin !PIN!
if errorlevel 1 set RESULT=1
python tools\test_qr_login.py %PORT%
if errorlevel 1 set RESULT=1

REM Paramos el servidor de pruebas.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    taskkill /f /pid %%p >nul 2>nul
)

echo.
if %RESULT%==0 (
    echo  ============================================================
    echo   TODO CORRECTO
    echo  ============================================================
) else (
    echo  ============================================================
    echo   HAY FALLOS - revisa la salida de arriba
    echo  ============================================================
)
exit /b %RESULT%
