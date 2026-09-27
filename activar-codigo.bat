@echo off
REM ===================================================================
REM  RemotePad - Volver a pedir el codigo de acceso
REM
REM  Reactiva el PIN y el codigo QR. Se genera un PIN nuevo.
REM  Lo deja guardado, asi que sigue activado en los proximos arranques.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo.
echo  ============================================================
echo   RemotePad - volver a pedir el codigo de acceso
echo  ============================================================
echo.

> "server\config.json" echo {
>>"server\config.json" echo   "auth_required": true
>>"server\config.json" echo }

echo  Guardado: server\config.json
type "server\config.json"
echo.
echo  ------------------------------------------------------------
echo   El PIN y el codigo QR vuelven a pedirse. Los celulares que ya
echo   estaban dentro siguen dentro; a los nuevos se les pedira.
echo  ------------------------------------------------------------
echo.

set ENCONTRADO=
for /f "tokens=5" %%p in ('netstat -ano ^| findstr LISTENING ^| findstr /r ":87[0-9][0-9] :88[0-9][0-9]"') do set ENCONTRADO=1

if defined ENCONTRADO (
    echo  Hay un servidor en marcha: se detiene para aplicar el cambio...
    powershell -NoProfile -Command ^
      "try { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/api/stop' -TimeoutSec 5 | Out-Null; Write-Host '  Detenido correctamente.' } catch { Write-Host '  No respondia en el puerto 8765.' }"
    echo.
    echo  Ahora arranca de nuevo con  iniciar.bat
) else (
    echo  No hay ningun servidor en marcha.
    echo  Arrancalo con  iniciar.bat
)
echo.
pause
