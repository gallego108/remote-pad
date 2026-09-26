@echo off
REM ===================================================================
REM  RemotePad - Abrir el Firewall de Windows
REM
REM  El celular no puede conectarse porque Windows no tiene ninguna
REM  regla de ENTRADA para TCP en el puerto del servidor. Este script
REM  la crea. Pide permisos de administrador (UAC): es obligatorio,
REM  solo el administrador puede tocar el Firewall.
REM ===================================================================
setlocal
set PORT=%1
if "%PORT%"=="" set PORT=8765

echo.
echo  ============================================================
echo   RemotePad - permiso en el Firewall de Windows
echo   Puerto TCP: %PORT%
echo  ============================================================
echo.

REM --- Comprobamos si ya estamos elevados ------------------------------
net session >nul 2>nul
if errorlevel 1 (
    echo  Se necesitan permisos de administrador.
    echo  Se abrira una ventana pidiendo confirmacion: acepta para continuar.
    echo.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%PORT%' -Verb RunAs"
    exit /b
)

echo  Permisos de administrador: correctos.
echo.

REM --- Regla para el puerto exacto -------------------------------------
netsh advfirewall firewall delete rule name="RemotePad TCP %PORT%" >nul 2>nul
netsh advfirewall firewall add rule name="RemotePad TCP %PORT%" dir=in action=allow protocol=TCP localport=%PORT%
if errorlevel 1 (
    echo.
    echo  [ERROR] No se pudo crear la regla. Prueba a ejecutar este archivo
    echo          con el boton derecho -^> "Ejecutar como administrador".
    echo.
    pause
    exit /b 1
)

REM --- Regla para el rango que usa la aplicacion -----------------------
REM  RemotePad puede arrancar en otros puertos con --port, asi que se abre
REM  un rango pequeno para no tener que repetir esto cada vez.
netsh advfirewall firewall delete rule name="RemotePad TCP rango" >nul 2>nul
netsh advfirewall firewall add rule name="RemotePad TCP rango" dir=in action=allow protocol=TCP localport=8765-8799 >nul 2>nul

echo.
echo  ============================================================
echo   LISTO. El celular ya deberia poder conectarse.
echo  ============================================================
echo.
echo   Direcciones de esta PC:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    for /f "tokens=1" %%b in ("%%a") do echo       http://%%b:%PORT%
)
echo.
echo   Si sigue sin funcionar:
echo     - comprueba que el celular esta en la MISMA red WiFi
echo     - si la red esta marcada como "Publica", cambiala a "Privada":
echo         Configuracion -^> Red e Internet -^> WiFi -^> Propiedades
echo     - algunas redes de invitados aislan los equipos entre si
echo.
echo   Para quitar el permiso mas adelante, ejecuta como administrador:
echo     netsh advfirewall firewall delete rule name="RemotePad TCP %PORT%"
echo.
pause
