@echo off
REM ===================================================================
REM  RemotePad - Quitar el codigo de acceso
REM
REM  Desactiva el PIN y el codigo QR: el celular entra directamente.
REM  Lo deja guardado, asi que sigue quitado en los proximos arranques.
REM
REM  AVISO: mientras este quitado, cualquiera conectado a tu misma red
REM  WiFi puede mover el puntero, hacer clic y escribir en esta PC.
REM  Para volver a pedirlo: ejecuta "activar-codigo.bat".
REM ===================================================================
setlocal
cd /d "%~dp0"

echo.
echo  ============================================================
echo   RemotePad - quitar el codigo de acceso (PIN y QR)
echo  ============================================================
echo.

> "server\config.json" echo {
>>"server\config.json" echo   "auth_required": false
>>"server\config.json" echo }

echo  Guardado: server\config.json
type "server\config.json"
echo.
echo  ------------------------------------------------------------
echo   AVISO: mientras este quitado, CUALQUIERA en tu misma WiFi
echo   puede manejar el puntero, hacer clic y escribir en la PC.
echo   Para volver a pedir el codigo, ejecuta activar-codigo.bat
echo  ------------------------------------------------------------
echo.

REM --- Si hay un servidor en marcha, se para para que coja el cambio ---
set ENCONTRADO=
for /f "tokens=5" %%p in ('netstat -ano ^| findstr LISTENING ^| findstr /r ":87[0-9][0-9] :88[0-9][0-9]"') do set ENCONTRADO=1

if defined ENCONTRADO (
    echo  Hay un servidor en marcha: se detiene para aplicar el cambio...
    powershell -NoProfile -Command ^
      "try { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/stop' -TimeoutSec 5 | Out-Null; Write-Host '  Detenido correctamente.' } catch { Write-Host '  No respondia en el puerto 8765.' }"
    echo.
    echo  Ahora arranca de nuevo con  iniciar.bat
    echo  (el celular entrara directamente, sin PIN ni QR)
) else (
    echo  No hay ningun servidor en marcha.
    echo  Arrancalo con  iniciar.bat  y el celular entrara directamente.
)
echo.
pause
